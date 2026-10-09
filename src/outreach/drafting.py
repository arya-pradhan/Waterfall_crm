"""Template drafts. Drafts only: nothing in this project sends a message."""

import os
import sqlite3
from pathlib import Path
from string import Template

TEMPLATES = Path(__file__).parent / "templates"


def available() -> list[str]:
    return sorted(p.stem for p in TEMPLATES.glob("*.txt"))


def render(conn: sqlite3.Connection, person_id: int, template: str | None = None) -> str:
    row = conn.execute("""
        SELECT p.*, c.name AS company, c.category, c.rating, c.review_count, c.location, c.domain
        FROM people p JOIN companies c ON c.id = p.company_id
        WHERE p.id = ?""", (person_id,)).fetchone()
    if row is None:
        raise KeyError(f"no person {person_id}")
    name = template or "smb_owner"
    signal = conn.execute(
        "SELECT detail FROM signals WHERE company_id = ? ORDER BY detected_at DESC LIMIT 1", (row["company_id"],)
    ).fetchone()
    fields = {
        "first_name": row["first_name"] or row["name"].split()[0],
        "company": row["company"],
        "category": row["category"] or "local",
        "city": (row["location"] or "").split(",")[0] or "your area",
        "rating": row["rating"] or "",
        "review_count": row["review_count"] or "",
        "title": row["title"] or "",
        "signal": signal["detail"] if signal else "",
        "sender_name": os.environ.get("OUTREACH_SENDER_NAME", "[your name]"),
        "sender_pitch": os.environ.get("OUTREACH_SENDER_PITCH", "[one line about you]"),
    }
    return Template((TEMPLATES / f"{name}.txt").read_text()).safe_substitute(fields).strip() + "\n"


def save(conn: sqlite3.Connection, person_id: int, draft: str, channel: str = "email") -> int:
    cur = conn.execute("INSERT INTO outreach (person_id, draft, channel) VALUES (?, ?, ?)", (person_id, draft, channel))
    conn.commit()
    return cur.lastrowid
