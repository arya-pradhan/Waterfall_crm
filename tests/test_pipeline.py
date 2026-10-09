"""End to end on a fake treg that replays the real responses in docs/samples/."""

import json
from pathlib import Path

from outreach import db, pipeline, report, scoring
from outreach.budget import Budget

from .conftest import FakeClient

SAMPLES = Path(__file__).parent.parent / "docs" / "samples"


def real(tool_id, cost):
    return (200, json.loads((SAMPLES / f"{tool_id}.json").read_text()), cost)


def fake_treg():
    return FakeClient({
        "litescrape.google.serp.maps": (503, {"detail": "saturated"}, 0),  # forces the Maps fallback
        "anyapi.google.serp.maps": real("anyapi.google.serp.maps", 1750),
        "quickenrich.people.search": real("quickenrich.people.search", 0),
        "dropleads.people.search": real("dropleads.people.search", 0),
        "leadsforge.people.search": real("leadsforge.people.search", 0),
        "quickenrich.people.email.find": (200, {"success": False, "data": []}, 0),  # miss
        "trykitt.people.email.find": real("trykitt.people.email.find", 5000),
        "tomba.people.email.find": real("tomba.people.email.find", 8900),
        "hunter.people.email.find": real("hunter.people.email.find", 24500),
        "treg.people.email.verify": real("treg.people.email.verify", 1500),
    })


def quiet(_):
    pass


def test_full_pipeline(conn):
    client, budget = fake_treg(), Budget(1.0)
    pipeline.maps_campaign(conn, client, budget, "HVAC contractor", ["Abilene, TX, USA"], say=quiet)
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 5

    # every company with a domain gets the same canned people answer; dedupe is per company
    pipeline.find_people(conn, client, budget, keep=2, say=quiet)
    people = conn.execute("SELECT name, title FROM people WHERE company_id = 1 ORDER BY id").fetchall()
    assert [p["title"] for p in people] == ["Owner", "Supervisor de mantenimiento"]  # owner first, untitled last

    pipeline.enrich_emails(conn, client, budget, limit=1, say=quiet)
    p = conn.execute("SELECT * FROM people WHERE id = 1").fetchone()
    assert p["source_provider"] == "trykitt.people.email.find"  # quickenrich missed first
    assert p["email_verified"] == 1 and p["email_status"] == "valid"

    # finish everyone; a second pass has nothing left to do and costs nothing
    pipeline.enrich_emails(conn, client, budget, say=quiet)
    spent, calls = budget.spent_micro, len(client.calls)
    pipeline.enrich_emails(conn, client, budget, say=quiet)
    assert (budget.spent_micro, len(client.calls)) == (spent, calls)


def test_benchmark_and_report(conn):
    client, budget = fake_treg(), Budget(1.0)
    pipeline.maps_campaign(conn, client, budget, "HVAC contractor", ["Abilene, TX, USA"], say=quiet)
    pipeline.find_people(conn, client, budget, limit=1, keep=1, say=quiet)
    pipeline.enrich_emails(conn, client, budget, limit=1, say=quiet)  # waterfall: stops at trykitt
    pipeline.enrich_emails(conn, client, budget, limit=1, benchmark=True, say=quiet)  # then ask everyone

    stats = {s["tool_id"]: s for s in report.provider_stats(conn, "email_find")}
    assert stats["quickenrich.people.email.find"]["hit_rate"] == 0
    assert stats["hunter.people.email.find"]["cost_per_hit"] == 24500
    assert [s["rank"] for s in report.provider_stats(conn, "email_find")] == [1, 2, 3, 4]

    # mark tomba's answer wrong, kitt's right -> accuracy + cost per correct hit
    ids = {r["tool_id"]: r["id"] for r in conn.execute("SELECT id, tool_id FROM enrichment_attempts WHERE capability='email_find' AND hit=1 AND cache_hit=0")}
    conn.execute("INSERT INTO accuracy_checks (attempt_id, correct) VALUES (?, 1)", (ids["trykitt.people.email.find"],))
    conn.execute("INSERT INTO accuracy_checks (attempt_id, correct) VALUES (?, 0)", (ids["tomba.people.email.find"],))
    stats = {s["tool_id"]: s for s in report.provider_stats(conn, "email_find")}
    assert stats["trykitt.people.email.find"]["accuracy"] == 1.0
    assert stats["trykitt.people.email.find"]["cost_per_correct"] == 5000
    assert stats["tomba.people.email.find"]["accuracy"] == 0.0
    assert stats["tomba.people.email.find"]["cost_per_correct"] is None

    assert report.agreement(conn)["hunter.people.email.find"] == (1, 1)
    md = report.render(conn)
    assert "| 2 | `trykitt.people.email.find` | 1 | 100%" in md


def test_company_dedupe(conn):
    a, new_a = db.upsert_company(conn, None, {"name": "Acme", "domain": "acme.com"})
    b, new_b = db.upsert_company(conn, None, {"name": "ACME Inc", "domain": "acme.com"})
    c, new_c = db.upsert_company(conn, None, {"name": "No Site", "place_id": "P1"})
    d, new_d = db.upsert_company(conn, None, {"name": "No Site 2", "place_id": "P1"})
    assert (a, new_a, new_b, new_d) == (b, True, False, False) and c == d


def test_csv_import(conn, tmp_path):
    f = tmp_path / "leads.csv"
    f.write_text("Company,Domain,Person_Name,Title\nStripe,https://stripe.com/,Jane Doe,University Recruiter\nStripe,stripe.com,,\n")
    pipeline.import_csv(conn, f, say=quiet)
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
    p = conn.execute("SELECT * FROM people").fetchone()
    assert (p["first_name"], p["last_name"], p["title"]) == ("Jane", "Doe", "University Recruiter")


def test_location_conflict_flags_wrong_company():
    company = {"address": "4413 Sayles Blvd, Abilene, TX 79605", "review_count": 2678, "rating": 4.9}
    person = {"title": "Owner", "email": "x@y.com", "email_verified": 1, "company_location": "Summerfield, NC"}
    s, why = scoring.score_person(person, company)
    assert "WRONG-COMPANY RISK" in why
    clean, _ = scoring.score_person({**person, "company_location": "Abilene, TX"}, company)
    assert clean - s == 30


def test_off_domain_email_penalized():
    company = {"domain": "precisionheatac.com"}
    on, _ = scoring.score_person({"title": "Owner", "email": "c@precisionheatac.com", "email_verified": 1}, company)
    off, why = scoring.score_person({"title": "Owner", "email": "c@precision-hvac.com", "email_verified": 1}, company)
    assert on - off == 15 and "≠ company domain" in why


def test_state_parsing():
    assert scoring.state_of("4413 Sayles Blvd, Abilene, TX 79605") == "TX"
    assert scoring.state_of("Abilene, TX, USA") == "TX"
    assert scoring.state_of("Summerfield, North Carolina") == "NC"
    assert scoring.state_of(None) is None


def test_title_ranking():
    ppl = [{"title": "Project Manager"}, {"title": None}, {"title": "Business Owner"}]
    assert [p["title"] for p in scoring.rank_people(ppl)] == ["Business Owner", "Project Manager", None]
    assert scoring.title_points("Senior Vice President Integrations")[0] == 20
    assert scoring.title_points("President")[0] == 40
