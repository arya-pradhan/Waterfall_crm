"""JSON API for the React app. Runs on the user's own machine (bound to 127.0.0.1 by `outreach serve`).

Every endpoint reads or writes the same SQLite file the CLI uses; searches run in jobs.py's
background worker so a request never waits on treg.
"""

import datetime as dt
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db, drafting, jobs

load_dotenv()

Status = Literal["new", "contacted", "replied", "meeting", "closed"]

LATEST_SCORE = """(SELECT score FROM scores s WHERE s.entity_type = 'person' AND s.entity_id = p.id ORDER BY s.id DESC LIMIT 1)"""
LATEST_REASON = """(SELECT reason FROM scores s WHERE s.entity_type = 'person' AND s.entity_id = p.id ORDER BY s.id DESC LIMIT 1)"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = db.connect(jobs.db_path)
    jobs.recover(conn)  # mark cut-off jobs paused, restart queued ones
    conn.close()
    yield


app = FastAPI(title="Waterfall CRM", lifespan=lifespan)


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(jobs.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Depends(get_conn)


def _one(conn: sqlite3.Connection, sql: str, *args) -> dict:
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise HTTPException(404, "not found")
    return dict(row)


# ---------------------------------------------------------------- setup + searches


class SearchIn(BaseModel):
    query: str = Field(min_length=2, examples=["HVAC contractor"])
    locations: list[str] = Field(min_length=1, examples=[["Austin, TX, USA"]])
    per_location: int = Field(20, ge=1, le=500)
    max_spend: float | None = Field(None, gt=0, description="USD cap for this search; default = estimate + 20%")


class ResumeIn(BaseModel):
    max_spend: float | None = Field(None, gt=0)


@app.get("/api/health")
def health():
    return {"treg_configured": bool(os.environ.get("TREG_TOKEN"))}


_balance_cache: dict = {"at": 0.0, "value": None}
LOW_BALANCE_USD = 0.25


@app.get("/api/balance")
def balance():
    """Remaining treg balance for the corner chip. Cached 30s so page polling doesn't hammer treg."""
    if time.monotonic() - _balance_cache["at"] > 30 or _balance_cache["value"] is None:
        try:
            _balance_cache["value"] = {"balance_usd": jobs.client_factory().balance_usd(), "error": None}
        except Exception as e:  # show the problem in the chip instead of breaking the page
            _balance_cache["value"] = {"balance_usd": None, "error": str(e)[:200]}
        _balance_cache["at"] = time.monotonic()
    v = _balance_cache["value"]
    return {**v, "low": v["balance_usd"] is not None and v["balance_usd"] < LOW_BALANCE_USD}


@app.post("/api/estimate")
def estimate(body: SearchIn, conn: sqlite3.Connection = Conn):
    return jobs.estimate(conn, body.locations, body.per_location)


@app.post("/api/searches", status_code=201)
def start_search(body: SearchIn, conn: sqlite3.Connection = Conn):
    if not os.environ.get("TREG_TOKEN"):
        raise HTTPException(400, "TREG_TOKEN is not set — add it to .env and restart")
    cap = body.max_spend or jobs.estimate(conn, body.locations, body.per_location)["suggested_cap_usd"]
    job_id = jobs.create(conn, body.query.strip(), [l.strip() for l in body.locations if l.strip()], body.per_location, cap)
    jobs.submit(job_id)
    return jobs.get(conn, job_id)


@app.get("/api/jobs")
def list_jobs(conn: sqlite3.Connection = Conn):
    return [jobs.get(conn, r["id"]) for r in conn.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 50")]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, conn: sqlite3.Connection = Conn):
    job = jobs.get(conn, job_id)
    if job is None:
        raise HTTPException(404, "not found")
    return job


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: int, body: ResumeIn, conn: sqlite3.Connection = Conn):
    job = get_job(job_id, conn)
    if job["status"] not in ("paused", "failed"):
        raise HTTPException(409, f"job is {job['status']}, not paused")
    jobs.resume(conn, job_id, body.max_spend)
    return jobs.get(conn, job_id)


# ---------------------------------------------------------------- groups + outreach table


@app.get("/api/groups")
def list_groups(conn: sqlite3.Connection = Conn):
    rows = conn.execute("""
        SELECT k.id, k.kind, k.query, k.locations, k.created_at,
               (SELECT COUNT(*) FROM campaign_companies cc WHERE cc.campaign_id = k.id) AS companies,
               (SELECT COUNT(*) FROM people p JOIN campaign_companies cc ON cc.company_id = p.company_id
                WHERE cc.campaign_id = k.id) AS contacts,
               (SELECT COUNT(*) FROM people p JOIN campaign_companies cc ON cc.company_id = p.company_id
                WHERE cc.campaign_id = k.id AND p.email IS NOT NULL) AS emails,
               (SELECT status FROM jobs j WHERE j.campaign_id = k.id ORDER BY j.id DESC LIMIT 1) AS job_status,
               (SELECT id FROM jobs j WHERE j.campaign_id = k.id ORDER BY j.id DESC LIMIT 1) AS job_id
        FROM campaigns k ORDER BY k.id DESC""").fetchall()
    out = []
    for r in rows:
        g = dict(r)
        g["locations"] = json.loads(g["locations"]) if g["locations"] else []
        g["progress"] = jobs.progress(conn, g["id"])
        out.append(g)
    return out


@app.get("/api/groups/{group_id}/contacts")
def group_contacts(group_id: int, conn: sqlite3.Connection = Conn):
    """One row per contact; companies with nobody found still get a row (person fields null)."""
    _one(conn, "SELECT id FROM campaigns WHERE id = ?", group_id)
    rows = conn.execute(f"""
        SELECT c.id AS company_id, c.name AS company, c.domain, c.website, c.phone, c.location, c.category,
               c.rating, c.review_count,
               p.id AS person_id, p.name, p.title, p.email, p.email_status, p.linkedin_url, p.status,
               p.follow_up_date, {LATEST_SCORE} AS score, {LATEST_REASON} AS score_reason
        FROM campaign_companies cc JOIN companies c ON c.id = cc.company_id
        LEFT JOIN people p ON p.company_id = c.id
        WHERE cc.campaign_id = ?
        ORDER BY score DESC NULLS LAST, c.name""", (group_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- company profile


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


def _person_rows(conn: sqlite3.Connection, where: str, *args) -> list[dict]:
    rows = conn.execute(f"""
        SELECT p.*, c.name AS company, {LATEST_SCORE} AS score, {LATEST_REASON} AS score_reason
        FROM people p JOIN companies c ON c.id = p.company_id WHERE {where}
        ORDER BY score DESC NULLS LAST, p.id""", args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/companies/{company_id}")
def company_profile(company_id: int, conn: sqlite3.Connection = Conn):
    company = _one(conn, "SELECT * FROM companies WHERE id = ?", company_id)
    company["people"] = _person_rows(conn, "p.company_id = ?", company_id)
    for person in company["people"]:
        person["activity"] = [dict(r) for r in conn.execute(
            "SELECT kind, note, created_at FROM activity WHERE person_id = ? ORDER BY id DESC", (person["id"],))]
    company["notes"] = [dict(r) for r in conn.execute(
        "SELECT id, note, created_at FROM company_notes WHERE company_id = ? ORDER BY id DESC", (company_id,))]
    company["groups"] = [dict(r) for r in conn.execute("""
        SELECT k.id, k.query FROM campaigns k JOIN campaign_companies cc ON cc.campaign_id = k.id
        WHERE cc.company_id = ?""", (company_id,))]
    return company


@app.post("/api/companies/{company_id}/notes", status_code=201)
def add_company_note(company_id: int, body: NoteIn, conn: sqlite3.Connection = Conn):
    _one(conn, "SELECT id FROM companies WHERE id = ?", company_id)
    cur = conn.execute("INSERT INTO company_notes (company_id, note) VALUES (?, ?)", (company_id, body.text))
    conn.commit()
    return _one(conn, "SELECT id, note, created_at FROM company_notes WHERE id = ?", cur.lastrowid)


# ---------------------------------------------------------------- CRM


class PersonPatch(BaseModel):
    status: Status | None = None
    follow_up_date: dt.date | None = None  # send null to clear


@app.get("/api/people")
def list_people(status: Status | None = None, conn: sqlite3.Connection = Conn):
    """The CRM board: every contact, filterable by stage."""
    return _person_rows(conn, "p.status = ?", status) if status else _person_rows(conn, "1 = 1")


@app.get("/api/upcoming")
def upcoming(limit: int = 8, conn: sqlite3.Connection = Conn):
    """Home's "Up next": open contacts with the nearest follow-up (or meeting) date, overdue first."""
    rows = _person_rows(conn, "p.follow_up_date IS NOT NULL AND p.status != 'closed'")
    rows.sort(key=lambda r: r["follow_up_date"])
    today = dt.date.today()
    for r in rows:
        r["days_until"] = (dt.date.fromisoformat(r["follow_up_date"]) - today).days
    return rows[:limit]


@app.patch("/api/people/{person_id}")
def update_person(person_id: int, body: PersonPatch, conn: sqlite3.Connection = Conn):
    _one(conn, "SELECT id FROM people WHERE id = ?", person_id)
    changes = body.model_dump(include=body.model_fields_set)
    if "status" in changes and changes["status"] is None:
        raise HTTPException(422, "status can't be cleared")
    if "follow_up_date" in changes and changes["follow_up_date"]:
        changes["follow_up_date"] = changes["follow_up_date"].isoformat()
    if changes:
        db.update(conn, "people", person_id, **changes)
        for k, v in changes.items():
            db.log_activity(conn, person_id, f"{k}:{v}" if k == "status" else k, None if k == "status" else v)
    return _person_rows(conn, "p.id = ?", person_id)[0]


@app.post("/api/people/{person_id}/notes", status_code=201)
def add_person_note(person_id: int, body: NoteIn, conn: sqlite3.Connection = Conn):
    _one(conn, "SELECT id FROM people WHERE id = ?", person_id)
    db.log_activity(conn, person_id, "note", body.text)
    return {"ok": True}


@app.get("/api/people/{person_id}/draft")
def person_draft(person_id: int, conn: sqlite3.Connection = Conn):
    """Template draft for the user to copy. Never sent from here."""
    try:
        return {"draft": drafting.render(conn, person_id)}
    except KeyError:
        raise HTTPException(404, "not found")
