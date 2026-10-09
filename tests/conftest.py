import pytest

from outreach import db
from outreach.providers import Provider
from outreach.treg_client import OutOfBalance, Result


class FakeClient:
    """Scripted treg: answers[tool_id] is a (status, data, cost_micro) tuple, or 402 to raise."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def balance_usd(self):
        return 0.42

    def call(self, tool_id, *, method="POST", query=None, body=None, headers=None):
        self.calls.append(tool_id)
        ans = self.answers[tool_id]
        if ans == 402:
            raise OutOfBalance({"balance_micro": 0})
        status, data, cost = ans
        ok = 200 <= status < 300
        return Result(tool_id, ok, status, data, latency_ms=10, cost_micro=cost, call_id="c1",
                      error=None if ok else "err")


def email_provider(tool_id, cost=5000):
    return Provider(
        "email_find",
        tool_id,
        lambda e: {"method": "POST", "body": {"name": e["name"]}} if e.get("name") else None,
        lambda d: {"email": d["email"]} if d and d.get("email") else None,
        cost,
    )


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()
