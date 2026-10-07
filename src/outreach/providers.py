"""Per-capability provider configs: how to ask each treg endpoint, and how to read its answer.

Every parser was written against a real response saved in docs/samples/<tool_id>.json.
A parser returns None for a miss; the waterfall treats anything else as a candidate hit.
List order is the waterfall order.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

Entity = dict[str, Any]
Request = dict[str, Any]  # {"method": ..., "query": ..., "body": ..., "headers": ...}


@dataclass(frozen=True)
class Provider:
    capability: str
    tool_id: str
    build: Callable[[Entity], Request | None]  # None = this provider can't use the inputs we have
    parse: Callable[[Any], Any]  # None = miss
    est_cost_micro: int  # catalog price per hit, used for the pre-call budget check


def _na(v: Any) -> Any:
    """Providers spell 'nothing' as 'N/A', '', or null."""
    return None if v in (None, "", "N/A", "n/a") else v


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Websites on Maps listings that are not the business's own domain.
NON_COMPANY_DOMAINS = {
    "facebook.com", "instagram.com", "yelp.com", "google.com", "business.site", "linktr.ee",
    "nextdoor.com", "angi.com", "homeadvisor.com", "bbb.org", "linkedin.com", "x.com", "twitter.com",
}


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "//" in url else f"//{url}").hostname or ""
    host = host.lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    if any(host == d or host.endswith("." + d) for d in NON_COMPANY_DOMAINS):
        return None
    return host


# ---------------------------------------------------------------- maps_search
# entity: {"query": "HVAC contractor", "location": "Abilene, TX, USA", "limit": 20}
# hit: list of company dicts


def _anyapi_maps_parse(data: Any) -> list[dict] | None:
    out = (data or {}).get("output") or {}
    items = (out.get("data") or {}).get("items") or []
    rows = [
        {
            "name": it.get("name"),
            "website": it.get("website"),
            "domain": domain_of(it.get("website")),
            "phone": it.get("phone"),
            "address": it.get("address"),
            "category": it.get("category"),
            "rating": it.get("rating"),
            "review_count": it.get("reviewCount"),
            "place_id": it.get("placeId"),
            "maps_url": it.get("url"),
        }
        for it in items
        if it.get("name") and not it.get("permanentlyClosed")
    ]
    return rows or None


def _litescrape_maps_parse(data: Any) -> list[dict] | None:
    items = (data or {}).get("local_results") or []
    rows = [
        {
            "name": it.get("title"),
            "website": it.get("website"),
            "domain": domain_of(it.get("website")),
            "phone": it.get("phone"),
            "address": it.get("address"),
            "category": it.get("type"),
            "rating": it.get("rating"),
            "review_count": it.get("reviews"),
            "place_id": it.get("place_id"),
            "maps_url": f"https://www.google.com/maps/place/?q=place_id:{it['place_id']}" if it.get("place_id") else None,
        }
        for it in items
        if it.get("title")
    ]
    return rows or None


MAPS = [
    Provider(
        "maps_search",
        "litescrape.google.serp.maps",
        # Location rides inside q ("HVAC contractor in Austin, TX"); one page = up to 20 places.
        lambda e: {"method": "GET", "query": {"q": f"{e['query']} in {e['location']}", "type": "search", "timeout": 60}},
        _litescrape_maps_parse,
        150,
    ),
    Provider(
        "maps_search",
        "anyapi.google.serp.maps",
        lambda e: {"method": "POST", "body": {"query": e["query"], "location": e["location"], "limit": e.get("limit", 20)}},
        _anyapi_maps_parse,
        1750,
    ),
]

# ---------------------------------------------------------------- people_find
# entity: company row {"domain": ..., "name": ...}; hit: list of person dicts


def _person(first, last, title, linkedin, company_location=None) -> dict:
    first, last = _na(first), _na(last)
    return {
        "first_name": first,
        "last_name": last,
        "name": " ".join(p for p in (first, last) if p) or None,
        "title": _na(title),
        "linkedin_url": _na(linkedin),
        "company_location": company_location,
    }


def _quickenrich_people_parse(data: Any) -> list[dict] | None:
    rows = [
        _person(
            r.get("first_name"), r.get("last_name"), r.get("title"), r.get("employee_linkedin"),
            ", ".join(x for x in (_na(r.get("city")), _na(r.get("region_code"))) if x) or None,
        )
        for r in (data or {}).get("data") or []
    ]
    return [r for r in rows if r["name"]] or None


def _dropleads_people_parse(data: Any) -> list[dict] | None:
    leads = ((data or {}).get("data") or {}).get("leads") or []
    rows = [_person(r.get("firstName"), r.get("lastName"), r.get("title"), r.get("linkedinUrl")) for r in leads]
    return [r for r in rows if r["name"]] or None


def _leadsforge_people_parse(data: Any) -> list[dict] | None:
    rows = []
    for r in (data or {}).get("leads") or []:
        loc = ((r.get("company") or {}).get("location")) or {}
        rows.append(_person(
            r.get("firstName"), r.get("lastName"), r.get("jobTitle"), r.get("linkedinUrl"),
            ", ".join(x for x in (loc.get("city"), loc.get("state")) if x) or None,
        ))
    return [r for r in rows if r["name"]] or None


def _with_domain(build: Callable[[str, int], Request]) -> Callable[[Entity], Request | None]:
    return lambda e: build(e["domain"], e.get("per_company", 5)) if e.get("domain") else None


PEOPLE = [
    Provider(
        "people_find",
        "quickenrich.people.search",
        _with_domain(lambda d, n: {"method": "POST", "body": {"company_url": {"include": [d], "exclude": []}, "per_page": n}}),
        _quickenrich_people_parse,
        0,
    ),
    Provider(
        "people_find",
        "dropleads.people.search",
        _with_domain(lambda d, n: {"method": "POST", "body": {"filters": {"companyDomains": [d]}, "pagination": {"page": 1, "limit": n}}}),
        _dropleads_people_parse,
        0,
    ),
    Provider(
        "people_find",
        "leadsforge.people.search",
        _with_domain(lambda d, n: {"method": "POST", "body": {"companyDomains": {"include": [d]}, "limit": n}}),
        _leadsforge_people_parse,
        0,
    ),
]

# ---------------------------------------------------------------- email_find
# entity: {"first_name", "last_name", "name", "domain", "linkedin_url"}
# hit: {"email", "provider_verified": bool|None, "confidence": int|None, "linkedin_url"}


def _email_hit(email: Any, verified: bool | None = None, confidence: Any = None, linkedin: Any = None) -> dict | None:
    email = _na(email)
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        return None
    return {"email": email.lower(), "provider_verified": verified, "confidence": confidence, "linkedin_url": _na(linkedin)}


def _quickenrich_email_parse(data: Any) -> dict | None:
    d = (data or {}).get("data") or {}
    if not isinstance(d, dict):
        return None
    return _email_hit(d.get("email"), bool(_na(d.get("email_verification_date"))) or None, None, d.get("employee_linkedin"))


def _trykitt_email_parse(data: Any) -> dict | None:
    d = data or {}
    return _email_hit(d.get("email"), d.get("validity") == "valid" if d.get("validity") else None)


def _tomba_email_parse(data: Any) -> dict | None:
    d = (data or {}).get("data") or {}
    status = (d.get("verification") or {}).get("status")
    return _email_hit(d.get("email"), status == "valid" if status else None, d.get("score"), d.get("linkedin"))


def _hunter_email_parse(data: Any) -> dict | None:
    d = (data or {}).get("data") or {}
    status = (d.get("verification") or {}).get("status")
    return _email_hit(d.get("email"), status == "valid" if status else None, d.get("score"), d.get("linkedin_url"))


def _needs(*keys: str):
    def wrap(build: Callable[[Entity], Request]) -> Callable[[Entity], Request | None]:
        return lambda e: build(e) if all(e.get(k) for k in keys) else None
    return wrap


EMAIL = [
    Provider(
        "email_find",
        "quickenrich.people.email.find",
        _needs("domain", "first_name", "last_name")(
            lambda e: {"method": "GET", "query": {"company_url": e["domain"], "first_name": e["first_name"], "last_name": e["last_name"]}}
        ),
        _quickenrich_email_parse,
        4834,
    ),
    Provider(
        "email_find",
        "trykitt.people.email.find",
        _needs("domain", "name")(lambda e: {"method": "POST", "body": {"fullName": e["name"], "domain": e["domain"], "realtime": True}}),
        _trykitt_email_parse,
        5000,
    ),
    Provider(
        "email_find",
        "tomba.people.email.find",
        _needs("domain", "name")(lambda e: {"method": "GET", "query": {"domain": e["domain"], "full_name": e["name"]}}),
        _tomba_email_parse,
        8900,
    ),
    Provider(
        "email_find",
        "hunter.people.email.find",
        _needs("domain", "name")(lambda e: {"method": "GET", "query": {"domain": e["domain"], "full_name": e["name"]}}),
        _hunter_email_parse,
        24500,
    ),
]

# ---------------------------------------------------------------- email_verify
# Routed: treg picks the cheapest verifier. We only need the verdict, not a comparison.


def _verify_parse(data: Any) -> dict | None:
    out = (data or {}).get("output") or {}
    if "status" not in out:
        return None
    served = ((data or {}).get("_treg") or {}).get("served_by")
    return {"valid": bool(out.get("valid")), "status": out["status"], "served_by": served}


VERIFY = [
    Provider(
        "email_verify",
        "treg.people.email.verify",
        _needs("email")(lambda e: {"method": "POST", "body": {"email": e["email"]}, "headers": {"X-Treg-Route-Max-Cost": "0.01"}}),
        _verify_parse,
        2000,
    ),
]

BY_CAPABILITY = {"maps_search": MAPS, "people_find": PEOPLE, "email_find": EMAIL, "email_verify": VERIFY}
