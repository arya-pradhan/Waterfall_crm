"""SQLite schema and queries. One connection per CLI invocation."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('maps', 'list')),
  query TEXT,
  locations TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER REFERENCES campaigns(id),
  name TEXT NOT NULL,
  domain TEXT,
  website TEXT,
  phone TEXT,
  address TEXT,
  location TEXT,
  category TEXT,
  rating REAL,
  review_count INTEGER,
  place_id TEXT,
  maps_url TEXT,
  size TEXT,
  industry TEXT,
  notes TEXT,
  people_searched_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS companies_domain ON companies(domain);
CREATE UNIQUE INDEX IF NOT EXISTS companies_place ON companies(place_id);
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  first_name TEXT,
  last_name TEXT,
  name TEXT NOT NULL,
  title TEXT,
  linkedin_url TEXT,
  company_location TEXT,
  email TEXT,
  email_verified INTEGER,
  email_status TEXT,
  source_provider TEXT,
  enriched_at TEXT,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'replied', 'meeting', 'closed')),
  follow_up_date TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (company_id, name)
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  type TEXT NOT NULL,
  detail TEXT,
  url TEXT,
  detected_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS enrichment_attempts (
  id INTEGER PRIMARY KEY,
  run_id TEXT,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  capability TEXT NOT NULL,
  provider TEXT NOT NULL,
  tool_id TEXT NOT NULL,
  rank INTEGER,
  hit INTEGER NOT NULL,
  value TEXT,
  latency_ms INTEGER,
  cost_micro INTEGER NOT NULL DEFAULT 0,
  cache_hit INTEGER NOT NULL DEFAULT 0,
  status_code INTEGER,
  call_id TEXT,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS accuracy_checks (
  attempt_id INTEGER PRIMARY KEY REFERENCES enrichment_attempts(id),
  correct INTEGER NOT NULL,
  note TEXT,
  checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS api_cache (
  key TEXT PRIMARY KEY,
  tool_id TEXT NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  score INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS outreach (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id),
  draft TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'email',
  status TEXT NOT NULL DEFAULT 'drafted' CHECK (status IN ('drafted', 'sent_manually', 'replied')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id),
  kind TEXT NOT NULL,
  note TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

STATUSES = ("new", "contacted", "replied", "meeting", "closed")


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or os.environ.get("OUTREACH_DB", "data/outreach.db")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- cache


def cache_key(tool_id: str, request: dict) -> str:
    return hashlib.sha256(f"{tool_id}\n{json.dumps(request, sort_keys=True)}".encode()).hexdigest()


def cache_get(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute("SELECT response_json FROM api_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(conn: sqlite3.Connection, key: str, tool_id: str, request: dict, response: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (key, tool_id, request_json, response_json) VALUES (?, ?, ?, ?)",
        (key, tool_id, json.dumps(request, sort_keys=True), json.dumps(response)),
    )
    conn.commit()


# ---------------------------------------------------------------- writes


def log_attempt(conn: sqlite3.Connection, **row: Any) -> int:
    cols = ", ".join(row)
    cur = conn.execute(f"INSERT INTO enrichment_attempts ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    conn.commit()
    return cur.lastrowid


def create_campaign(conn: sqlite3.Connection, kind: str, query: str | None, locations: list[str] | None) -> int:
    cur = conn.execute(
        "INSERT INTO campaigns (kind, query, locations) VALUES (?, ?, ?)",
        (kind, query, json.dumps(locations) if locations else None),
    )
    conn.commit()
    return cur.lastrowid


COMPANY_COLS = ("name", "domain", "website", "phone", "address", "location", "category", "rating",
                "review_count", "place_id", "maps_url", "size", "industry", "notes")


def upsert_company(conn: sqlite3.Connection, campaign_id: int | None, c: dict) -> tuple[int, bool]:
    """Insert unless a company with the same domain (or Maps place_id) exists. Returns (id, created)."""
    for col in ("domain", "place_id"):
        if c.get(col):
            row = conn.execute(f"SELECT id FROM companies WHERE {col} = ?", (c[col],)).fetchone()
            if row:
                return row["id"], False
    if not c.get("domain") and not c.get("place_id"):
        row = conn.execute("SELECT id FROM companies WHERE lower(name) = lower(?)", (c["name"],)).fetchone()
        if row:
            return row["id"], False
    vals = {k: c.get(k) for k in COMPANY_COLS}
    cur = conn.execute(
        f"INSERT INTO companies (campaign_id, {', '.join(vals)}) VALUES (?, {', '.join('?' * len(vals))})",
        (campaign_id, *vals.values()),
    )
    conn.commit()
    return cur.lastrowid, True


def add_person(conn: sqlite3.Connection, company_id: int, p: dict) -> tuple[int, bool]:
    row = conn.execute("SELECT id FROM people WHERE company_id = ? AND lower(name) = lower(?)", (company_id, p["name"])).fetchone()
    if row:
        return row["id"], False
    cur = conn.execute(
        """INSERT INTO people (company_id, first_name, last_name, name, title, linkedin_url, company_location, email)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (company_id, p.get("first_name"), p.get("last_name"), p["name"], p.get("title"),
         p.get("linkedin_url"), p.get("company_location"), p.get("email")),
    )
    conn.commit()
    return cur.lastrowid, True


def update(conn: sqlite3.Connection, table: str, id_: int, **fields: Any) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), id_))
    conn.commit()


def log_activity(conn: sqlite3.Connection, person_id: int, kind: str, note: str | None = None) -> None:
    conn.execute("INSERT INTO activity (person_id, kind, note) VALUES (?, ?, ?)", (person_id, kind, note))
    conn.commit()
