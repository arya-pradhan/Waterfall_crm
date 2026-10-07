"""Markdown report: per-provider waterfall stats, accuracy, agreement, funnel."""

import sqlite3
from collections import Counter, defaultdict

from . import providers

CAPABILITY_TITLES = {
    "email_find": "Email finding",
    "people_find": "People at a company",
    "email_verify": "Email verification",
    "maps_search": "Google Maps sourcing",
}


def provider_stats(conn: sqlite3.Connection, capability: str) -> list[dict]:
    """Live calls only: cache replays are free re-reads of an attempt already counted."""
    rows = conn.execute("""
        SELECT a.tool_id,
               COUNT(*) AS attempts,
               SUM(a.hit) AS hits,
               SUM(a.status_code NOT BETWEEN 200 AND 299) AS errors,
               AVG(a.latency_ms) AS avg_latency,
               SUM(a.cost_micro) AS cost,
               SUM(ac.correct IS NOT NULL) AS checked,
               SUM(ac.correct = 1) AS correct
        FROM enrichment_attempts a LEFT JOIN accuracy_checks ac ON ac.attempt_id = a.id
        WHERE a.capability = ? AND a.cache_hit = 0
        GROUP BY a.tool_id""", (capability,)).fetchall()
    order = [p.tool_id for p in providers.BY_CAPABILITY.get(capability, [])]
    out = []
    for r in rows:
        d = dict(r)
        d["rank"] = order.index(d["tool_id"]) + 1 if d["tool_id"] in order else None
        d["hit_rate"] = d["hits"] / d["attempts"] if d["attempts"] else None
        d["cost_per_attempt"] = d["cost"] / d["attempts"] if d["attempts"] else None
        d["cost_per_hit"] = d["cost"] / d["hits"] if d["hits"] else None
        d["accuracy"] = d["correct"] / d["checked"] if d["checked"] else None
        d["cost_per_correct"] = (d["cost_per_hit"] / d["accuracy"]) if d["cost_per_hit"] and d["accuracy"] else None
        out.append(d)
    return sorted(out, key=lambda d: (d["rank"] is None, d["rank"] or 0))


def agreement(conn: sqlite3.Connection, capability: str = "email_find") -> dict[str, tuple[int, int]]:
    """For entities where 2+ providers answered: how often each provider matched the majority answer."""
    by_entity: dict[int, dict[str, str]] = defaultdict(dict)
    for r in conn.execute("""SELECT entity_id, tool_id, lower(value) AS v FROM enrichment_attempts
                             WHERE capability = ? AND hit = 1""", (capability,)):
        by_entity[r["entity_id"]][r["tool_id"]] = r["v"]
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for answers in by_entity.values():
        if len(answers) < 2:
            continue
        majority, n = Counter(answers.values()).most_common(1)[0]
        if n < 2:
            continue  # no consensus to compare against
        for tool, v in answers.items():
            tally[tool][0] += v == majority
            tally[tool][1] += 1
    return {k: (v[0], v[1]) for k, v in tally.items()}


def head_to_head(conn: sqlite3.Connection, capability: str = "email_find") -> tuple[int, int, list[dict]]:
    """Only entities that EVERY current provider was asked about (live), so hit rates are comparable.

    In waterfall mode the later providers only see what earlier ones missed — the hard cases —
    so their raw hit rates are biased low. This view removes that bias.
    """
    tools = [p.tool_id for p in providers.BY_CAPABILITY[capability]]
    rows = conn.execute(f"""
        SELECT entity_id, tool_id, MAX(hit) AS hit, MAX(cost_micro) AS cost
        FROM enrichment_attempts
        WHERE capability = ? AND cache_hit = 0 AND tool_id IN ({','.join('?' * len(tools))})
        GROUP BY entity_id, tool_id""", (capability, *tools)).fetchall()
    by_entity: dict[int, dict[str, sqlite3.Row]] = defaultdict(dict)
    for r in rows:
        by_entity[r["entity_id"]][r["tool_id"]] = r
    full = {e: answers for e, answers in by_entity.items() if len(answers) == len(tools)}
    n = len(full)
    out = []
    for t in tools:
        hits = sum(a[t]["hit"] for a in full.values())
        unique = sum(a[t]["hit"] and sum(x["hit"] for x in a.values()) == 1 for a in full.values())
        cost = sum(a[t]["cost"] for a in full.values())
        out.append({"tool_id": t, "hits": hits, "unique": unique, "cost": cost,
                    "hit_rate": hits / n if n else None, "cost_per_hit": cost / hits if hits else None})
    found_any = sum(any(x["hit"] for x in a.values()) for a in full.values())
    return n, found_any, out


def funnel(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return [
        ("Companies sourced", q("SELECT COUNT(*) FROM companies")),
        ("…with a usable domain", q("SELECT COUNT(*) FROM companies WHERE domain IS NOT NULL")),
        ("…with ≥1 contact found", q("SELECT COUNT(DISTINCT company_id) FROM people")),
        ("Contacts", q("SELECT COUNT(*) FROM people")),
        ("…with an email", q("SELECT COUNT(*) FROM people WHERE email IS NOT NULL")),
        ("…email verified valid", q("SELECT COUNT(*) FROM people WHERE email_verified = 1")),
        ("…flagged wrong-company risk", q("SELECT COUNT(DISTINCT entity_id) FROM scores WHERE entity_type='person' AND reason LIKE '%WRONG-COMPANY%' AND id IN (SELECT MAX(id) FROM scores GROUP BY entity_type, entity_id)")),
        ("Drafted", q("SELECT COUNT(DISTINCT person_id) FROM outreach")),
        ("Contacted", q("SELECT COUNT(*) FROM people WHERE status IN ('contacted','replied','meeting','closed')")),
        ("Replied", q("SELECT COUNT(*) FROM people WHERE status IN ('replied','meeting','closed')")),
        ("Meeting", q("SELECT COUNT(*) FROM people WHERE status IN ('meeting','closed')")),
    ]


def _usd(micro: float | None, digits: int = 4) -> str:
    return "—" if micro is None else f"${micro / 1e6:.{digits}f}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def render(conn: sqlite3.Connection) -> str:
    total = conn.execute("SELECT COALESCE(SUM(cost_micro), 0) FROM enrichment_attempts").fetchone()[0]
    replays = conn.execute("SELECT COUNT(*) FROM enrichment_attempts WHERE cache_hit = 1").fetchone()[0]
    lines = [
        "# Waterfall report",
        "",
        f"Total spend through treg: **{_usd(total)}** · cache replays (free): {replays}",
        "",
    ]
    agree = agreement(conn)
    for cap, title in CAPABILITY_TITLES.items():
        stats = provider_stats(conn, cap)
        if not stats:
            continue
        lines += [
            f"## {title}",
            "",
            "| # | Provider | Attempts | Hit rate | Errors | Avg latency | Cost / attempt | Cost / hit | Checked | Accuracy | Cost / correct hit |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in stats:
            lines.append(
                f"| {s['rank'] or '–'} | `{s['tool_id']}` | {s['attempts']} | {_pct(s['hit_rate'])} | {s['errors']} "
                f"| {s['avg_latency']:.0f} ms | {_usd(s['cost_per_attempt'])} | {_usd(s['cost_per_hit'])} "
                f"| {s['checked']} | {_pct(s['accuracy'])} | {_usd(s['cost_per_correct'])} |"
            )
        if cap == "email_find":
            n, found_any, h2h = head_to_head(conn, cap)
            if n:
                lines += [
                    "",
                    f"**Head-to-head** — the same {n} people asked of every provider "
                    f"({found_any} found by at least one). Unique = found by this provider only:",
                    "",
                    "| Provider | Found | Hit rate | Unique finds | Cost / hit |",
                    "|---|---|---|---|---|",
                ]
                lines += [f"| `{h['tool_id']}` | {h['hits']}/{n} | {_pct(h['hit_rate'])} | {h['unique']} "
                          f"| {_usd(h['cost_per_hit'])} |" for h in h2h]
        if cap == "email_find" and agree:
            lines += ["", "**Agreement with the majority answer** (people where 2+ providers answered):", ""]
            for tool, (ok, n) in sorted(agree.items(), key=lambda kv: -kv[1][1]):
                lines.append(f"- `{tool}`: {ok}/{n} ({ok / n:.0%})")
        lines.append("")
    lines += ["## Pipeline funnel", "", "| Stage | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in funnel(conn)]
    lines += [
        "",
        "_Hit rate ≠ accuracy. Accuracy comes from hand-checked samples (`outreach check`); "
        "cost per correct hit = cost per hit ÷ accuracy, and that is what should set provider order._",
        "",
    ]
    return "\n".join(lines)
