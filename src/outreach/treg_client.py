"""The only module that talks to treg. Everything else sees `Result`."""

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


class OutOfBalance(Exception):
    """HTTP 402 from treg: the team balance (or a route cost ceiling) refused the call."""

    def __init__(self, body: Any):
        self.body = body
        super().__init__(f"treg refused the call for balance: {body}")


@dataclass
class Result:
    tool_id: str
    ok: bool
    status: int
    data: Any
    latency_ms: int
    cost_micro: int
    call_id: str | None = None
    served_by: str | None = None
    error: str | None = None


class TregClient:
    def __init__(self, token: str | None = None, base: str | None = None, http: httpx.Client | None = None):
        self.token = token or os.environ.get("TREG_TOKEN", "")
        self.base = (base or os.environ.get("TREG_BASE", "https://treg.to")).rstrip("/")
        if not self.token:
            raise RuntimeError("TREG_TOKEN is not set (copy .env.example to .env)")
        self.http = http or httpx.Client(timeout=60)

    def call(
        self,
        tool_id: str,
        *,
        method: str = "POST",
        query: dict | None = None,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> Result:
        start = time.monotonic()
        try:
            r = self.http.request(
                method,
                f"{self.base}/call/{tool_id}",
                params=query,
                json=body if method != "GET" else None,
                headers={"X-Treg-Token": self.token, **(headers or {})},
            )
        except httpx.HTTPError as e:
            return Result(tool_id, False, 0, None, _ms(start), 0, error=f"network: {e}")
        latency = _ms(start)
        try:
            data = r.json()
        except ValueError:
            data = r.text
        if r.status_code == 402:
            raise OutOfBalance(data)
        ok = 200 <= r.status_code < 300
        return Result(
            tool_id=tool_id,
            ok=ok,
            status=r.status_code,
            data=data,
            latency_ms=latency,
            cost_micro=int(r.headers.get("X-Treg-Cost-Micro") or 0),
            call_id=r.headers.get("X-Treg-Call-Id"),
            served_by=r.headers.get("X-Treg-Served-By"),
            error=None if ok else (r.headers.get("X-Treg-Error") or str(data)[:300]),
        )


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
