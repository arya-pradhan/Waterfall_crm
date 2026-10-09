# Waterfall CRM — project brief

Outreach pipeline + thin CRM built on treg:
**source (Google Maps or CSV) -> find people -> waterfall email enrichment -> verify -> score -> draft -> track -> report**

Lineage: this rebuilds the Integrus n8n pipeline (`~/Documents/Integrus/pipeline/`: form -> Apify Google Maps scraper per metro -> Google Sheets) as code on treg, then adds what Integrus stopped short of: contacts, emails, verification, scoring, drafts, CRM, and a per-provider report.

Purpose: portfolio project for a Clay (GTM data enrichment) recruiter screen. It demonstrates waterfall enrichment, signal-based prospecting, and the hard problems: **data accuracy and cost per correct hit**.

## Commands
```
uv run pytest
uv run outreach serve                     # builds web/ then serves UI + API at http://127.0.0.1:8000
npm --prefix web run dev                  # UI dev server with live reload at :5173 (proxies /api to :8000)
npm --prefix web run typecheck
uv run outreach campaign "HVAC contractor" -m "Abilene, TX, USA" -m "Austin, TX, USA" --max-spend 0.02
uv run outreach import leads.csv          # company, domain, [person_name, title, notes]
uv run outreach find-people --keep 2
uv run outreach enrich --max-spend 0.25   # --benchmark asks every provider
uv run outreach check                     # hand-verify hits -> accuracy
uv run outreach score && uv run outreach list --reasons
uv run outreach draft <person_id>
uv run outreach mark <id> contacted | follow-up <id> +5 | due | note <id> "..."
uv run outreach report                    # -> docs/report.md
uv run outreach export                    # -> data/contacts.csv (paste into Sheets)
uv run outreach balance
```

## Layout
- `src/outreach/treg_client.py` — the ONLY module that talks to treg (httpx -> `POST|GET https://treg.to/call/<tool_id>`)
- `providers.py` — per-capability provider lists (list order = waterfall order), request builders, parsers written against `docs/samples/*.json`
- `waterfall.py` — try in order, stop at first validated hit, log every attempt, read/write `api_cache`
- `budget.py` — per-run `--max-spend`; a call is refused before it's made if its catalog price would cross the cap
- `pipeline.py` — campaign/import/find_people/enrich steps; each only processes rows not yet done (re-runs resume)
- `scoring.py`, `drafting.py` (+ `templates/`), `report.py`, `db.py`, `cli.py`
- `api.py` — FastAPI JSON API for the UI; also serves the built UI from `web/dist`. `jobs.py` — background search worker (one at a time; pause/resume; estimates)
- `web/` — React + TypeScript + Vite UI (`src/api.ts` is its only door to the API; `public/cities.txt` feeds city autocomplete)

## treg facts (verified with real calls, 2026-10-07)
- Auth: header `X-Treg-Token`; this token bakes in team `prysma` (no `X-Treg-Org` needed).
- Response headers: `X-Treg-Cost-Micro` (actual charge — matched `treg balance` exactly), `X-Treg-Call-Id`, `X-Treg-Error` (treg's own refusals only), `X-Treg-Served-By` (routed endpoints).
- 402 = out of balance -> stop the run. 503 `provider_capacity_unavailable` -> next provider. A 4xx is usually our params.
- Providers in use (prices per hit; misses free unless noted):
  - maps: `anyapi.google.serp.maps` POST `{query, location, limit<=20}` $0.00175/call. Don't send `placeMinimumStars`/`website` filters (pricier source).
  - people (all $0): `quickenrich.people.search`, `dropleads.people.search`, `leadsforge.people.search` (needs `limit`).
    `getleadsio.people.decision_makers` returned nothing for SMBs and its `limit` defaults to 5000 billed records — not used.
  - email: `quickenrich.people.email.find` GET $0.00483 (needs first+last) -> `trykitt` POST $0.005 -> `tomba` GET $0.0089 -> `hunter` GET $0.0245.
  - verify: routed `treg.people.email.verify` with `X-Treg-Route-Max-Cost: 0.01` (served by trykitt, $0.0015).
- **Known data-quality trap:** people providers matched `qualitycool.com` to a company in Summerfield, NC, while the Maps listing is in Abilene, TX. Domain-only matching can attach the wrong company's people; `scoring.location_conflict` flags it.

## Guardrails
- Never put the token or any secret in code or git. `.env` (gitignored) holds `TREG_TOKEN`; `.env.example` documents it.
- Drafts only. Nothing sends email or messages; the user sends manually and runs `outreach mark <id> contacted`.
- No LinkedIn or platform scraping. Provider APIs via treg, user-supplied data, and public pages only.
- Spend small (started with $1.00 of credit). Always pass `--max-spend`; caching means re-runs never pay twice. Check `outreach balance` often.
- Don't guess response formats: make a real call, save it to `docs/samples/<tool_id>.json`, and write the parser plus a test against it.

## Original brief (condensed)
- Goal: signal -> enrich (provider waterfall) -> score -> draft outreach -> track in a thin CRM. The interesting work is upstream: per-provider hit rate, cost, and latency, logged and reported.
- Lead type: local businesses by category + metro (the Integrus use case); a CSV list of companies can also be imported.
- Report = per provider: attempts, hit rate, avg latency, cost/attempt, cost/hit, rank, plus hand-checked accuracy. Never report hit rate alone as "quality".
- MVP done when: 30–50 real leads enriched through a 3–4 provider waterfall; every attempt logged; a report with hit rate, cost/hit, latency, and accuracy per provider; leads scored with reasons; drafts for the top ones; CRM status/notes/follow-ups; a README with results and lessons.
- Stretch: signal ingestion (career-page watcher, the treg `lead-signals` skill), routed `treg.people.email.find` as a baseline vs. our own waterfall, a simple web view.
- Interview line: "Hit rate isn't the same as accuracy, and cost per correct result is what actually decides provider order."
