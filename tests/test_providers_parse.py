import json
from pathlib import Path

import pytest

from outreach import providers as P

SAMPLES = Path(__file__).parent.parent / "docs" / "samples"


def sample(tool_id):
    return json.loads((SAMPLES / f"{tool_id}.json").read_text())


def by_id(tool_id):
    return next(p for ps in P.BY_CAPABILITY.values() for p in ps if p.tool_id == tool_id)


def test_maps_parse():
    rows = by_id("anyapi.google.serp.maps").parse(sample("anyapi.google.serp.maps"))
    assert len(rows) == 5
    assert rows[0]["name"] == "Quality Cooling, Heating & Plumbing"
    assert rows[0]["domain"] == "qualitycool.com"
    assert rows[0]["review_count"] == 2678
    no_site = next(r for r in rows if r["name"].startswith("Cutting Edge"))
    assert no_site["domain"] is None


def test_litescrape_maps_parse():
    rows = by_id("litescrape.google.serp.maps").parse(sample("litescrape.google.serp.maps"))
    assert len(rows) == 20
    assert rows[0]["domain"] == "coolmenow.com"  # utm params stripped
    assert rows[0]["review_count"] == 3860
    assert sum(r["domain"] is None for r in rows) == 1


@pytest.mark.parametrize("tool_id", ["quickenrich.people.search", "dropleads.people.search", "leadsforge.people.search"])
def test_people_parse(tool_id):
    rows = by_id(tool_id).parse(sample(tool_id))
    assert rows and all(r["name"] for r in rows)


def test_people_parse_cleans_na():
    rows = by_id("quickenrich.people.search").parse(sample("quickenrich.people.search"))
    shelly = rows[0]
    assert shelly["title"] == "Owner"
    assert shelly["linkedin_url"] is None  # "N/A" upstream
    assert shelly["company_location"] == "Summerfield, NC"


@pytest.mark.parametrize(
    "tool_id",
    ["quickenrich.people.email.find", "trykitt.people.email.find", "tomba.people.email.find", "hunter.people.email.find"],
)
def test_email_parse_hit(tool_id):
    hit = by_id(tool_id).parse(sample(tool_id))
    assert hit["email"] == "fbilbo@qualitycool.com"


@pytest.mark.parametrize(
    "tool_id,miss",
    [
        ("trykitt.people.email.find", {"email": "no-results-found"}),
        ("tomba.people.email.find", {"data": {"email": None, "score": 0}}),
        ("hunter.people.email.find", {"data": {"email": None}}),
        ("quickenrich.people.email.find", {"success": False, "data": []}),
    ],
)
def test_email_parse_miss(tool_id, miss):
    assert by_id(tool_id).parse(miss) is None


def test_people_miss():
    assert by_id("quickenrich.people.search").parse({"data": []}) is None
    assert by_id("dropleads.people.search").parse({"data": {"leads": []}}) is None


def test_verify_parse():
    v = by_id("treg.people.email.verify").parse(sample("treg.people.email.verify"))
    assert v == {"valid": True, "status": "valid", "served_by": "trykitt.people.email.verify"}


def test_build_skips_missing_inputs():
    qe = by_id("quickenrich.people.email.find")
    assert qe.build({"name": "Fred", "domain": "x.com"}) is None  # needs first+last
    assert by_id("trykitt.people.email.find").build({"name": "Fred Bilbo", "domain": "x.com"})["body"]["fullName"] == "Fred Bilbo"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.Example.com/path?q=1", "example.com"),
        ("example.com", "example.com"),
        ("https://www.facebook.com/somebiz", None),
        ("https://somebiz.business.site/", None),
        (None, None),
    ],
)
def test_domain_of(url, expected):
    assert P.domain_of(url) == expected
