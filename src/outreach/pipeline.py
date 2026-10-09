"""Pipeline steps: source companies -> find people -> find + verify emails.

Each step works on rows not yet processed, so re-running continues where the last run stopped
(the Integrus queue idea, minus the spreadsheet). Budget/balance errors propagate to the CLI.
"""

import csv
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path

from . import db, providers, scoring, waterfall
from .budget import Budget
from .treg_client import TregClient

Progress = Callable[[str], None]


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


PAGE = 20  # Maps results per page


def maps_campaign(conn: sqlite3.Connection, client: TregClient, budget: Budget, query: str,
                  metros: list[str], limit: int = 20, say: Progress = print,
                  campaign_id: int | None = None) -> int:
    """Up to `limit` places per metro, fetched a page at a time. Pass campaign_id to resume a group:
    pages already fetched replay from the cache for free."""
    if campaign_id is None:
        campaign_id = db.create_campaign(conn, "maps", query, metros)
    run_id = new_run_id()
    for metro in metros:
        found = added = 0
        for start in range(0, limit, PAGE):
            out = waterfall.run(conn, client, budget, providers.MAPS,
                                {"query": query, "location": metro, "limit": min(PAGE, limit - start), "start": start},
                                entity_type="campaign", entity_id=campaign_id, run_id=run_id)
            rows = (out.hit or [])[: limit - found]
            for row in rows:
                _, created = db.upsert_company(conn, campaign_id, {**row, "location": metro})
                added += created
            found += len(rows)
            if len(out.hit or []) < PAGE:  # last page (or a miss): Maps has no more for this metro
                break
        say(f"{metro}: {found} places, {added} new companies")
    return campaign_id


def import_csv(conn: sqlite3.Connection, path: Path, say: Progress = print) -> int:
    """Columns: company, domain, [person_name, title, notes]. One row per person (or per company)."""
    campaign_id = db.create_campaign(conn, "list", path.name, None)
    companies = people = 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("company"):
                continue
            domain = providers.domain_of(row.get("domain")) if row.get("domain") else None
            company_id, created = db.upsert_company(
                conn, campaign_id, {"name": row["company"], "domain": domain, "notes": row.get("notes") or None})
            companies += created
            if row.get("person_name"):
                first, _, last = row["person_name"].partition(" ")
                _, created = db.add_person(conn, company_id, {
                    "name": row["person_name"], "first_name": first, "last_name": last or None,
                    "title": row.get("title") or None})
                people += created
    say(f"imported {companies} new companies, {people} new people (campaign {campaign_id})")
    return campaign_id


def _in_group(campaign_id: int | None, company_col: str) -> tuple[str, tuple]:
    """SQL filter limiting a step to one group's companies (or every company when campaign_id is None)."""
    if campaign_id is None:
        return "", ()
    return f" AND {company_col} IN (SELECT company_id FROM campaign_companies WHERE campaign_id = ?)", (campaign_id,)


def find_people(conn: sqlite3.Connection, client: TregClient, budget: Budget, *, limit: int = 50,
                keep: int = 2, say: Progress = print, campaign_id: int | None = None) -> None:
    run_id = new_run_id()
    group_sql, group_args = _in_group(campaign_id, "id")
    companies = conn.execute(
        f"SELECT * FROM companies WHERE domain IS NOT NULL AND people_searched_at IS NULL{group_sql} ORDER BY id LIMIT ?",
        (*group_args, limit)).fetchall()
    for c in companies:
        out = waterfall.run(conn, client, budget, providers.PEOPLE, {"domain": c["domain"], "per_company": 5},
                            entity_type="company", entity_id=c["id"], run_id=run_id)
        kept = scoring.rank_people(out.hit or [])[:keep]
        for p in kept:
            db.add_person(conn, c["id"], p)
        if out.settled:
            db.update(conn, "companies", c["id"], people_searched_at=_now(conn))
        who = ", ".join(f"{p['name']} ({p['title'] or '?'})" for p in kept) or ("nobody" if out.settled else "ERROR, will retry")
        src = out.provider.tool_id if out.provider else "-"
        say(f"{c['name']} [{c['domain']}] -> {who}  via {src}")


def enrich_emails(conn: sqlite3.Connection, client: TregClient, budget: Budget, *, limit: int = 50,
                  verify: bool = True, benchmark: bool = False, say: Progress = print,
                  campaign_id: int | None = None) -> None:
    """benchmark=True asks every provider about every person (head-to-head data for the report)."""
    run_id = new_run_id()
    # Benchmark targets people the waterfall already answered: misses were already asked of every provider.
    where = "p.enriched_at IS NULL" if not benchmark else "p.email IS NOT NULL"
    group_sql, group_args = _in_group(campaign_id, "c.id")
    people = conn.execute(f"""
        SELECT p.*, c.domain FROM people p JOIN companies c ON c.id = p.company_id
        WHERE {where} AND c.domain IS NOT NULL{group_sql} ORDER BY p.id LIMIT ?""", (*group_args, limit)).fetchall()
    for p in people:
        out = waterfall.run(conn, client, budget, providers.EMAIL, dict(p),
                            entity_type="person", entity_id=p["id"], run_id=run_id, stop_on_hit=not benchmark)
        fields = {"enriched_at": _now(conn)} if out.settled else {}
        if out.hit and not p["email"]:
            fields.update(email=out.hit["email"], source_provider=out.provider.tool_id,
                          linkedin_url=p["linkedin_url"] or out.hit.get("linkedin_url"))
        email = fields.get("email") or p["email"]
        if verify and email and p["email_status"] is None:
            v = waterfall.run(conn, client, budget, providers.VERIFY, {"email": email},
                              entity_type="person", entity_id=p["id"], run_id=run_id)
            if v.hit:
                fields.update(email_verified=int(v.hit["valid"]), email_status=v.hit["status"])
        if fields:
            db.update(conn, "people", p["id"], **fields)
        status = fields.get("email_status") or ("" if out.settled else "ERROR, will retry")
        say(f"{p['name']} [{p['domain']}] -> {email or 'no email'} {status}  "
            f"via {out.provider.tool_id if out.provider else '-'}")


def score_people(conn: sqlite3.Connection, campaign_id: int | None = None) -> int:
    """Append a fresh score + reason for each contact (the latest row is the current score)."""
    group_sql, group_args = _in_group(campaign_id, "c.id")
    rows = conn.execute(f"""SELECT p.*, c.domain, c.address, c.location, c.rating, c.review_count
                            FROM people p JOIN companies c ON c.id = p.company_id WHERE 1=1{group_sql}""",
                        group_args).fetchall()
    for r in rows:
        s, why = scoring.score_person(dict(r), dict(r))
        conn.execute("INSERT INTO scores (entity_type, entity_id, score, reason) VALUES ('person', ?, ?, ?)", (r["id"], s, why))
    conn.commit()
    return len(rows)


def _now(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
