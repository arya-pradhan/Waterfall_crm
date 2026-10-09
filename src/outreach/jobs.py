"""Background searches: one job at a time, in a worker thread inside the server.

A job runs one group through the pipeline: Maps -> people -> emails + verify -> score.
State lives in the `jobs` table, and progress is counted from the data itself, so closing the
browser tab changes nothing. If the server stops mid-run, the job is marked paused on the next
start; resuming re-runs the steps, which skip finished rows and replay fetched answers from the
cache for free.
"""

import json
import queue
import sqlite3
import threading
from typing import Any

from . import db, pipeline, providers
from .budget import Budget, BudgetExceeded
from .treg_client import OutOfBalance, TregClient

client_factory = TregClient  # tests swap in a fake
db_path: str | None = None  # None -> OUTREACH_DB / data/outreach.db

_queue: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


# ---------------------------------------------------------------- lifecycle


def create(conn: sqlite3.Connection, query: str, locations: list[str], per_location: int, max_spend_usd: float) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (query, locations, per_location, max_spend_micro) VALUES (?, ?, ?, ?)",
        (query, json.dumps(locations), per_location, int(round(max_spend_usd * 1e6))),
    )
    conn.commit()
    return cur.lastrowid


def submit(job_id: int) -> None:
    """Queue a job for the worker thread (started on first use)."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work_forever, name="outreach-jobs", daemon=True)
            _worker.start()
    _queue.put(job_id)


def recover(conn: sqlite3.Connection) -> None:
    """On server start: a job that was 'running' was cut off; queued jobs still need running."""
    conn.execute("UPDATE jobs SET status = 'paused', message = 'server stopped mid-run — resume to continue', "
                 "updated_at = CURRENT_TIMESTAMP WHERE status = 'running'")
    conn.commit()
    for row in conn.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY id"):
        submit(row["id"])


def resume(conn: sqlite3.Connection, job_id: int, max_spend_usd: float | None = None) -> None:
    fields: dict[str, Any] = {"status": "queued", "message": "queued to resume"}
    if max_spend_usd is not None:
        fields["max_spend_micro"] = int(round(max_spend_usd * 1e6))
    _set(conn, job_id, **fields)
    submit(job_id)


def _work_forever() -> None:
    while True:
        job_id = _queue.get()
        try:
            run(job_id)
        finally:
            _queue.task_done()


# ---------------------------------------------------------------- the run


def run(job_id: int) -> None:
    conn = db.connect(db_path)
    try:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None or job["status"] not in ("queued", "paused"):
            return  # already done, or picked up twice
        remaining = job["max_spend_micro"] - job["spent_micro"]
        if remaining <= 0:
            _set(conn, job_id, status="paused", message="spending cap reached — raise it to continue")
            return
        budget, spent_before = Budget(remaining / 1e6), job["spent_micro"]

        def say(msg: str) -> None:
            _set(conn, job_id, message=msg, spent_micro=spent_before + budget.spent_micro)

        _set(conn, job_id, status="running", message="starting")
        try:
            client = client_factory()
            campaign_id = job["campaign_id"]
            if campaign_id is None:
                campaign_id = db.create_campaign(conn, "maps", job["query"], json.loads(job["locations"]))
                _set(conn, job_id, campaign_id=campaign_id)
            everything = 1_000_000  # the group is the limit; budget is the brake

            _set(conn, job_id, stage="maps")
            pipeline.maps_campaign(conn, client, budget, job["query"], json.loads(job["locations"]),
                                   job["per_location"], say=say, campaign_id=campaign_id)
            _set(conn, job_id, stage="people")
            pipeline.find_people(conn, client, budget, limit=everything, keep=1, say=say, campaign_id=campaign_id)
            _set(conn, job_id, stage="emails")
            pipeline.enrich_emails(conn, client, budget, limit=everything, say=say, campaign_id=campaign_id)
            _set(conn, job_id, stage="scoring")
            pipeline.score_people(conn, campaign_id)
            leftover = _unsettled(conn, campaign_id)
            if leftover:
                _set(conn, job_id, status="paused", message=f"{leftover} lookups hit provider errors — resume to retry")
            else:
                _set(conn, job_id, status="done", stage="done", message="finished")
        except BudgetExceeded as e:
            _set(conn, job_id, status="paused", message=f"paused: {e}")
        except OutOfBalance as e:
            body = e.body if isinstance(e.body, dict) else {}
            _set(conn, job_id, status="paused", message=f"treg balance too low — top up ({body.get('topup_url', 'treg.to')})")
        except Exception as e:  # keep the worker alive; show the error on the job
            _set(conn, job_id, status="failed", message=f"{type(e).__name__}: {e}"[:500])
        finally:
            _set(conn, job_id, spent_micro=spent_before + budget.spent_micro)
    finally:
        conn.close()


def _unsettled(conn: sqlite3.Connection, campaign_id: int) -> int:
    """Rows a provider error left open (they'll be retried on resume)."""
    return conn.execute("""
        SELECT (SELECT COUNT(*) FROM companies c JOIN campaign_companies cc ON cc.company_id = c.id
                WHERE cc.campaign_id = ? AND c.domain IS NOT NULL AND c.people_searched_at IS NULL)
             + (SELECT COUNT(*) FROM people p JOIN campaign_companies cc ON cc.company_id = p.company_id
                JOIN companies c ON c.id = p.company_id
                WHERE cc.campaign_id = ? AND p.enriched_at IS NULL AND c.domain IS NOT NULL)""", (campaign_id, campaign_id)).fetchone()[0]


def _set(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    db.update(conn, "jobs", job_id, **fields, updated_at=conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0])


# ---------------------------------------------------------------- reading


def get(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    job["locations"] = json.loads(job["locations"])
    job["spent_usd"] = job.pop("spent_micro") / 1e6
    job["max_spend_usd"] = job.pop("max_spend_micro") / 1e6
    job["progress"] = progress(conn, job["campaign_id"]) if job["campaign_id"] else None
    return job


def progress(conn: sqlite3.Connection, campaign_id: int) -> dict:
    """Counted from the group's rows, so it's right even after a restart."""
    r = conn.execute("""
        SELECT COUNT(*) AS companies,
               SUM(c.domain IS NOT NULL) AS with_domain,
               SUM(c.domain IS NOT NULL AND c.people_searched_at IS NOT NULL) AS people_searched
        FROM companies c JOIN campaign_companies cc ON cc.company_id = c.id WHERE cc.campaign_id = ?""",
        (campaign_id,)).fetchone()
    p = conn.execute("""
        SELECT COUNT(*) AS contacts, SUM(p.enriched_at IS NOT NULL) AS enriched,
               SUM(p.email IS NOT NULL) AS emails, SUM(p.email_verified = 1) AS verified
        FROM people p JOIN campaign_companies cc ON cc.company_id = p.company_id WHERE cc.campaign_id = ?""",
        (campaign_id,)).fetchone()
    return {k: (v or 0) for k, v in {**dict(r), **dict(p)}.items()}


# ---------------------------------------------------------------- estimate

# Used until there's history to average. Rough, from the first real run (2026-10-07).
DEFAULTS = {"domain_rate": 0.9, "contact_rate": 0.8, "email_cost": 5000, "verify_cost": 1100,
            "maps_ms": 8000, "people_ms": 600, "email_ms": 6000}


def estimate(conn: sqlite3.Connection, locations: list[str], per_location: int) -> dict:
    """Cost and time for a new search, from averages of past live (non-cache, non-benchmark) calls."""
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    live = "cache_hit = 0 AND mode = 'waterfall'"
    searched = q("SELECT COUNT(*) FROM companies WHERE people_searched_at IS NOT NULL")
    history = searched >= 10
    h = dict(DEFAULTS)
    if history:
        h["domain_rate"] = q("SELECT AVG(domain IS NOT NULL) FROM companies")
        h["contact_rate"] = q("""SELECT AVG(id IN (SELECT company_id FROM people)) FROM companies
                                 WHERE people_searched_at IS NOT NULL""")
        people_asked = q(f"SELECT COUNT(DISTINCT entity_id) FROM enrichment_attempts WHERE capability='email_find' AND {live}") or 1
        h["email_cost"] = q(f"SELECT COALESCE(SUM(cost_micro),0) FROM enrichment_attempts WHERE capability='email_find' AND {live}") / people_asked
        h["verify_cost"] = q(f"SELECT COALESCE(SUM(cost_micro),0) FROM enrichment_attempts WHERE capability='email_verify' AND {live}") / people_asked
        h["email_ms"] = q(f"""SELECT COALESCE(SUM(latency_ms),0) FROM enrichment_attempts
                              WHERE capability IN ('email_find','email_verify') AND {live}""") / people_asked
        h["people_ms"] = q(f"SELECT COALESCE(SUM(latency_ms),0) FROM enrichment_attempts WHERE capability='people_find' AND {live}") / searched
        h["maps_ms"] = q(f"SELECT AVG(latency_ms) FROM enrichment_attempts WHERE capability='maps_search' AND {live} AND hit = 1") or DEFAULTS["maps_ms"]

    pages = len(locations) * -(-per_location // pipeline.PAGE)  # ceil
    companies = len(locations) * per_location
    contacts = companies * h["domain_rate"] * h["contact_rate"]
    maps_cost = pages * providers.MAPS[0].est_cost_micro
    cost = maps_cost + contacts * (h["email_cost"] + h["verify_cost"])
    ms = pages * h["maps_ms"] + companies * h["domain_rate"] * h["people_ms"] + contacts * h["email_ms"]
    return {
        "companies": companies,
        "contacts": round(contacts),
        "cost_usd": round(cost / 1e6, 4),
        "minutes": round(ms / 60000, 1),
        "suggested_cap_usd": round(max(0.01, cost / 1e6 * 1.2), 2),
        "basis": "your past runs" if history else "catalog defaults",
        "note": "Upper bound on companies: Maps may return fewer for small towns or narrow categories.",
    }
