"""Rule-based fit scores. Every point comes with a reason a human can read."""

import re

DECISION_MAKER = ("owner", "founder", "co-founder", "ceo", "president", "principal", "partner", "general manager")
SENIOR = ("director", "vp", "vice president", "head", "chief", "manager")

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def title_points(title: str | None) -> tuple[int, str]:
    t = (title or "").lower().replace("vice president", "vp")  # else "president" matches VPs
    if not t:
        return 0, "no title"
    if any(re.search(rf"\b{re.escape(k)}\b", t) for k in DECISION_MAKER):
        return 40, f"decision-maker ({title})"
    if any(re.search(rf"\b{re.escape(k)}\b", t) for k in SENIOR):
        return 20, f"senior ({title})"
    return 5, f"other role ({title})"


def state_of(text: str | None) -> str | None:
    """'…, Abilene, TX 79605' -> TX; 'Summerfield, North Carolina' -> NC."""
    if not text:
        return None
    m = re.findall(r"\b([A-Z]{2})\b(?:\s+\d{5})?(?:,?\s*(?:USA|United States))?\s*$", text.strip())
    if m:
        return m[-1]
    low = text.lower()
    for name, code in STATES.items():
        if re.search(rf"\b{name}\b", low):
            return code
    return None


def location_conflict(company: dict, person: dict) -> str | None:
    """Where we found the business vs. where the data provider thinks the company is."""
    ours = state_of(company.get("address")) or state_of(company.get("location"))
    theirs = state_of(person.get("company_location"))
    if ours and theirs and ours != theirs:
        return f"provider places company in {theirs}, Maps listing is in {ours}"
    return None


def rank_people(people: list[dict]) -> list[dict]:
    return sorted(people, key=lambda p: -title_points(p.get("title"))[0])


def score_person(person: dict, company: dict) -> tuple[int, str]:
    pts, reasons = 0, []

    p, why = title_points(person.get("title"))
    pts += p
    reasons.append(why)

    if person.get("email") and person.get("email_verified"):
        pts += 30
        reasons.append("verified email")
    elif person.get("email"):
        pts += 10
        reasons.append(f"unverified email ({person.get('email_status') or 'not checked'})")
    else:
        reasons.append("no email")

    if person.get("linkedin_url"):
        pts += 5
        reasons.append("has LinkedIn")

    reviews, rating = company.get("review_count") or 0, company.get("rating") or 0
    if reviews:
        # established local businesses: many reviews, good rating
        biz = min(15, reviews // 50) + (10 if rating >= 4.5 else 5 if rating >= 4.0 else 0)
        pts += biz
        reasons.append(f"{rating}★ / {reviews} reviews")

    email, domain = person.get("email") or "", company.get("domain")
    if email and domain and not email.lower().endswith("@" + domain) and not email.lower().endswith("." + domain):
        # "valid" only means the mailbox exists — not that it belongs to this business
        pts -= 15
        reasons.append(f"email domain {email.split('@')[-1]} ≠ company domain {domain}")

    conflict = location_conflict(company, person)
    if conflict:
        pts -= 30
        reasons.append(f"WRONG-COMPANY RISK: {conflict}")

    return max(0, min(100, pts)), "; ".join(reasons)
