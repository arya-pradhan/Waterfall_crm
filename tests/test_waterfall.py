import pytest

from outreach import waterfall
from outreach.budget import Budget, BudgetExceeded
from outreach.providers import EMAIL_RE
from outreach.treg_client import OutOfBalance

from .conftest import FakeClient, email_provider

A, B, C = (email_provider(t) for t in ("a.find", "b.find", "c.find"))
PERSON = {"name": "Fred Bilbo"}


def attempts(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM enrichment_attempts ORDER BY id")]


def go(conn, client, providers, budget=None, **kw):
    return waterfall.run(conn, client, budget or Budget(1.0), providers, PERSON,
                         entity_type="person", entity_id=1, run_id="r1", **kw)


def test_stops_at_first_hit_and_logs_misses(conn):
    client = FakeClient({"a.find": (200, {"email": None}, 0), "b.find": (200, {"email": "f@x.com"}, 5000)})
    out = go(conn, client, [A, B, C])
    assert out.hit == {"email": "f@x.com"} and out.provider is B
    assert client.calls == ["a.find", "b.find"]
    log = attempts(conn)
    assert [(r["tool_id"], r["hit"], r["rank"], r["cost_micro"]) for r in log] == [
        ("a.find", 0, 1, 0), ("b.find", 1, 2, 5000)]
    assert log[1]["value"] == "f@x.com"


def test_errors_fall_through(conn):
    client = FakeClient({"a.find": (503, {"error": "provider_capacity_unavailable"}, 0), "b.find": (200, {"email": "f@x.com"}, 5000)})
    out = go(conn, client, [A, B])
    assert out.provider is B
    assert attempts(conn)[0]["status_code"] == 503


def test_validation_rejects_bad_value(conn):
    client = FakeClient({"a.find": (200, {"email": "not-an-email"}, 5000), "b.find": (200, {"email": "f@x.com"}, 5000)})
    out = go(conn, client, [A, B], validate=lambda h: bool(EMAIL_RE.match(h["email"])))
    assert out.provider is B
    assert attempts(conn)[0]["hit"] == 0 and attempts(conn)[0]["cost_micro"] == 5000  # paid for a bad answer


def test_skips_providers_missing_inputs(conn):
    needs_domain = email_provider("d.find")
    needs_domain = needs_domain.__class__(needs_domain.capability, "d.find", lambda e: None, needs_domain.parse, 1)
    client = FakeClient({"a.find": (200, {"email": "f@x.com"}, 5000)})
    go(conn, client, [needs_domain, A])
    assert client.calls == ["a.find"]
    assert [r["tool_id"] for r in attempts(conn)] == ["a.find"]


def test_cache_means_second_run_is_free(conn):
    client = FakeClient({"a.find": (200, {"email": "f@x.com"}, 5000)})
    go(conn, client, [A])
    budget = Budget(1.0)
    out = go(conn, client, [A], budget=budget)
    assert out.hit == {"email": "f@x.com"}
    assert client.calls == ["a.find"]  # not called again
    assert budget.spent_micro == 0
    assert attempts(conn)[1]["cache_hit"] == 1 and attempts(conn)[1]["cost_micro"] == 0


def test_errors_are_not_cached(conn):
    client = FakeClient({"a.find": (500, None, 0)})
    go(conn, client, [A])
    go(conn, client, [A])
    assert client.calls == ["a.find", "a.find"]


def test_402_stops_run_and_is_logged(conn):
    client = FakeClient({"a.find": 402, "b.find": (200, {"email": "f@x.com"}, 5000)})
    with pytest.raises(OutOfBalance):
        go(conn, client, [A, B])
    assert client.calls == ["a.find"]
    assert attempts(conn)[0]["status_code"] == 402


def test_budget_refuses_before_calling(conn):
    client = FakeClient({"a.find": (200, {"email": None}, 0), "b.find": (200, {"email": "f@x.com"}, 5000)})
    with pytest.raises(BudgetExceeded):
        go(conn, client, [A, B], budget=Budget(0.004))  # each est. $0.005
    assert client.calls == []


def test_benchmark_mode_runs_everyone(conn):
    client = FakeClient({t: (200, {"email": "f@x.com"}, 5000) for t in ("a.find", "b.find", "c.find")})
    out = go(conn, client, [A, B, C], stop_on_hit=False)
    assert out.provider is A
    assert client.calls == ["a.find", "b.find", "c.find"]
    assert sum(r["hit"] for r in attempts(conn)) == 3
