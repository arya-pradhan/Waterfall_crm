"""Try providers in order until one returns a result that passes validation.

Every attempt is logged — hits, misses, errors, and cache replays — because that log is
what the report (and the provider-order decision) is built from.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db
from .budget import Budget
from .providers import Entity, Provider
from .treg_client import OutOfBalance, TregClient


@dataclass
class Outcome:
    hit: Any = None
    provider: Provider | None = None
    attempt_id: int | None = None
    attempts: list[int] = field(default_factory=list)


def run(
    conn: sqlite3.Connection,
    client: TregClient,
    budget: Budget,
    providers: list[Provider],
    entity: Entity,
    *,
    entity_type: str,
    entity_id: int | None,
    run_id: str,
    validate: Callable[[Any], bool] = lambda _: True,
    stop_on_hit: bool = True,
) -> Outcome:
    """stop_on_hit=False runs every provider (head-to-head benchmark); the first hit is still returned."""
    outcome = Outcome()
    for rank, p in enumerate(providers, start=1):
        request = p.build(entity)
        if request is None:  # missing the inputs this provider needs; not an attempt
            continue
        key = db.cache_key(p.tool_id, request)
        cached = db.cache_get(conn, key)
        log = dict(
            run_id=run_id, entity_type=entity_type, entity_id=entity_id, capability=p.capability,
            provider=p.tool_id.split(".")[0], tool_id=p.tool_id, rank=rank,
        )
        if cached is not None:
            data, ok, status = cached, True, 200
            log.update(latency_ms=0, cost_micro=0, cache_hit=1, status_code=200)
        else:
            budget.check(p.est_cost_micro)
            try:
                res = client.call(p.tool_id, method=request["method"], query=request.get("query"),
                                  body=request.get("body"), headers=request.get("headers"))
            except OutOfBalance as e:
                db.log_attempt(conn, **log, hit=0, status_code=402, error=json.dumps(e.body)[:500])
                raise
            budget.spend(res.cost_micro)
            data, ok, status = res.data, res.ok, res.status
            log.update(latency_ms=res.latency_ms, cost_micro=res.cost_micro, status_code=res.status,
                       call_id=res.call_id, error=res.error)
            if ok:
                db.cache_put(conn, key, p.tool_id, request, data)

        parsed = p.parse(data) if ok else None
        hit = parsed is not None and validate(parsed)
        attempt_id = db.log_attempt(conn, **log, hit=int(hit), value=_summary(parsed) if hit else None)
        outcome.attempts.append(attempt_id)
        if hit and outcome.hit is None:
            outcome.hit, outcome.provider, outcome.attempt_id = parsed, p, attempt_id
            if stop_on_hit:
                break
    return outcome


def _summary(parsed: Any) -> str:
    """The value we'd hand-check later: an email, or a short list of names."""
    if isinstance(parsed, dict):
        return parsed.get("email") or parsed.get("status") or json.dumps(parsed)[:200]
    if isinstance(parsed, list):
        return f"{len(parsed)}: " + "; ".join(str(r.get("name")) for r in parsed[:5])
    return str(parsed)[:200]
