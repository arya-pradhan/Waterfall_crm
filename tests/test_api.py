"""API + background jobs against a fake treg replaying the real samples. Jobs run synchronously here."""

import pytest
from fastapi.testclient import TestClient

from outreach import api, db, jobs

from .conftest import FakeClient
from .test_pipeline import real


def fake_treg():
    return FakeClient({
        "litescrape.google.serp.maps": real("litescrape.google.serp.maps", 150),
        "anyapi.google.serp.maps": real("anyapi.google.serp.maps", 1750),
        "quickenrich.people.search": real("quickenrich.people.search", 0),
        "dropleads.people.search": real("dropleads.people.search", 0),
        "leadsforge.people.search": real("leadsforge.people.search", 0),
        "quickenrich.people.email.find": real("quickenrich.people.email.find", 4834),
        "trykitt.people.email.find": real("trykitt.people.email.find", 5000),
        "tomba.people.email.find": real("tomba.people.email.find", 8900),
        "hunter.people.email.find": real("hunter.people.email.find", 24500),
        "treg.people.email.verify": real("treg.people.email.verify", 1500),
    })


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = fake_treg()
    monkeypatch.setenv("TREG_TOKEN", "test-token")
    monkeypatch.setattr(jobs, "db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(jobs, "client_factory", lambda: fake)
    monkeypatch.setattr(jobs, "submit", jobs.run)  # run inline instead of on the worker thread
    with TestClient(api.app) as http:
        yield http, fake


SEARCH = {"query": "HVAC contractor", "locations": ["Austin, TX, USA"], "per_location": 20}


def test_search_to_crm(env):
    http, fake = env
    est = http.post("/api/estimate", json=SEARCH).json()
    assert est["companies"] == 20 and est["basis"] == "catalog defaults" and est["cost_usd"] > 0

    job = http.post("/api/searches", json={**SEARCH, "max_spend": 1.0}).json()
    assert job["status"] == "done", job["message"]
    assert job["progress"]["companies"] == 20
    assert job["progress"]["emails"] > 0 and job["spent_usd"] > 0

    groups = http.get("/api/groups").json()
    assert groups[0]["companies"] == 20 and groups[0]["job_status"] == "done"

    rows = http.get(f"/api/groups/{groups[0]['id']}/contacts").json()
    contact = next(r for r in rows if r["person_id"])
    assert contact["score"] is not None and contact["email"]
    assert any(r["person_id"] is None for r in rows)  # the business with no website still shows

    cid, pid = contact["company_id"], contact["person_id"]
    assert http.post(f"/api/companies/{cid}/notes", json={"text": "family-owned, 3 trucks"}).status_code == 201
    profile = http.get(f"/api/companies/{cid}").json()
    assert profile["notes"][0]["note"] == "family-owned, 3 trucks"
    assert profile["people"][0]["id"] == pid and profile["groups"][0]["id"] == groups[0]["id"]

    person = http.patch(f"/api/people/{pid}", json={"status": "contacted", "follow_up_date": "2026-10-15"}).json()
    assert person["status"] == "contacted" and person["follow_up_date"] == "2026-10-15"
    assert [p["id"] for p in http.get("/api/people", params={"status": "contacted"}).json()] == [pid]
    assert http.patch(f"/api/people/{pid}", json={"follow_up_date": None}).json()["follow_up_date"] is None
    assert "Subject:" in http.get(f"/api/people/{pid}/draft").json()["draft"]


def test_budget_pause_then_resume_without_repaying(env):
    http, fake = env
    job = http.post("/api/searches", json={**SEARCH, "max_spend": 0.001}).json()  # maps fits, emails don't
    assert job["status"] == "paused" and "max-spend" in job["message"]
    assert job["progress"]["companies"] == 20

    job = http.post(f"/api/jobs/{job['id']}/resume", json={"max_spend": 1.0}).json()
    assert job["status"] == "done"
    assert fake.calls.count("litescrape.google.serp.maps") == 1  # page replayed from cache on resume


def test_server_restart_pauses_cut_off_jobs(env, monkeypatch):
    http, _ = env
    conn = db.connect(jobs.db_path)
    job_id = jobs.create(conn, "HVAC contractor", ["Austin, TX, USA"], 20, 1.0)
    db.update(conn, "jobs", job_id, status="running")
    monkeypatch.setattr(jobs, "submit", lambda _id: None)
    jobs.recover(conn)
    assert jobs.get(conn, job_id)["status"] == "paused"


def test_validation(env, monkeypatch):
    http, _ = env
    assert http.patch("/api/people/999", json={"status": "contacted"}).status_code == 404
    assert http.get("/api/companies/999").status_code == 404
    assert http.post("/api/estimate", json={**SEARCH, "locations": []}).status_code == 422
    monkeypatch.delenv("TREG_TOKEN")
    assert http.post("/api/searches", json=SEARCH).status_code == 400
