# Waterfall CRM

A small outreach pipeline with a provider waterfall at its core, built on [treg](https://treg.to) (one token, many data vendors, pay per call):

```
Google Maps (business type × metro)  ─┐
CSV target list (e.g. internships)   ─┴─> companies ─> people search ─> email waterfall ─> verify ─> score ─> draft ─> thin CRM
                                                         (3 providers)    (4 providers)                              │
                                          every attempt logged: provider · hit/miss · cost · latency ───────> report.md
```

It started as a rebuild of an n8n + Apify + Google Sheets lead scraper (business type + metro → a sheet of businesses). That version stopped at a list of company names. This one carries on to the decision-maker, a verified email, a reason to reach out, and a record of what happened, and it measures every data vendor along the way.

## Quick start

```bash
uv sync
cp .env.example .env            # add TREG_TOKEN
uv run outreach campaign "HVAC contractor" -m "Abilene, TX, USA" -m "Austin, TX, USA" --max-spend 0.01
uv run outreach find-people --keep 1
uv run outreach enrich --max-spend 0.35
uv run outreach check            # hand-verify a sample -> accuracy
uv run outreach score && uv run outreach list --reasons
uv run outreach draft 14         # prints + saves a draft; never sends
uv run outreach mark 14 contacted && uv run outreach follow-up 14 +5
uv run outreach report           # -> docs/report.md
uv run outreach export           # -> data/contacts.csv (paste into Google Sheets)
```

## How the waterfall works

- Providers for each job are an ordered list in [`providers.py`](src/outreach/providers.py). Each one has a request builder, a parser written against a **real saved response** ([`docs/samples/`](docs/samples)), and its catalog price.
- [`waterfall.py`](src/outreach/waterfall.py) skips providers missing the inputs they need, tries the rest in order, and stops at the first answer that passes validation. It logs **every** attempt (hit, miss, error, cache replay) with the actual charge from treg's `X-Treg-Cost-Micro` header.
- `--max-spend` refuses a call *before* it is made if its price would cross the cap. A 402 stops the run cleanly. Responses are cached, so re-runs never pay twice.
- A row is only marked done when the waterfall *settles*, meaning a hit or a clean miss from everyone. If a provider errored, the row is retried next run.
- `enrich --benchmark` asks every provider about the same people. The report uses this for a fair head-to-head comparison (see below).

## Results: first run (HVAC contractors, Abilene + Austin, TX)

| Stage | Count |
|---|---|
| Businesses from Google Maps | 40 |
| …with their own website/domain | 36 (90%) |
| …with a decision-maker found | 29 (81%) |
| …with an email | 22 (76%) |
| …email verified deliverable | 15 (52%); 4 more are catch-all ("valid-risky") |

**Spend:** $0.18 for the production email waterfall plus verification (≈ $0.008 per email found, $0.012 per verified contact), plus $0.14 for the head-to-head benchmark. People search was free and Maps cost $0.002 in total. Full tables are in [`docs/report.md`](docs/report.md).

**Email providers, waterfall order** (`quickenrich` → `trykitt` → `tomba` → `hunter`):

| Provider | Cost / hit | Avg latency | Head-to-head (same 15 people) | Unique finds |
|---|---|---|---|---|
| quickenrich | $0.0048 | 0.4 s | 4 / 15 | 0 |
| trykitt | $0.0050 | 4.8 s | 5 / 15 | 0 |
| tomba | $0.0089 | 10.2 s | 6 / 15 | 1 |
| hunter | $0.0245 | 2.7 s | 5 / 15 | 2 |

## What I learned

1. **Raw waterfall hit rates are biased by order.** In production, providers 2–4 only see the people #1 missed, which are the hard cases. To compare vendors fairly you have to ask all of them about the same people. That is what `--benchmark` and the head-to-head table do.
2. **Agreement is cheap evidence; single-source answers are the risk.** Whenever 2+ providers found an email, they agreed 100% of the time. The answers worth checking are the ones only one vendor returned: hunter's 2 unique finds cost 5× more, and one of them is on a *different domain* from the business.
3. **"Verified" ≠ correct.** A verifier confirms a mailbox exists, not that it belongs to this person at this business. Two verified emails were on domains that don't match the company's website (`precision-hvac.com` vs `precisionheatac.com`). Scoring flags this.
4. **Matching on domain alone attaches the wrong company.** People providers placed `qualitycool.com` in North Carolina, while the Maps listing is a different Quality Cooling in Texas. Franchise listings (Goettl, Service Experts) link to a national domain, so you get a corporate SVP instead of the local owner. Comparing the provider's company location with the Maps address catches these (`WRONG-COMPANY RISK`).
5. **Order by cost per *correct* hit, not cost per hit.** The report computes cost per correct hit from hand-checked samples (`outreach check`). Hunter's extra unique finds only justify its place in the waterfall if they turn out to be right.
6. **Infrastructure fails too.** One Maps vendor returned the same 503 three times in a row. A second vendor in the list, plus never marking errored rows as done, turned that into a non-event.

## Design choices

- **Drafts only.** Nothing sends email. A human reviews, sends manually, and runs `outreach mark <id> contacted`. This keeps a person in the loop and avoids spam and CAN-SPAM problems.
- **No platform scraping.** Data comes from vendor APIs via treg and public Maps listings. Contact data stays local in the gitignored `data/` folder.
- **SQLite is the source of truth.** CSV export covers the "I want it in a Sheet" case without Google auth.
- **One module talks to treg** ([`treg_client.py`](src/outreach/treg_client.py)), so the transport or vendor can be swapped.

## Next

- Hand-check about 20 hits with `outreach check` to fill in the accuracy column.
- Internship campaign: `outreach import targets.csv` (company, domain), with recruiter and eng-manager titles ranked first.
- Signals: hiring and funding events per company (treg `lead-signals` ideas) feeding scoring and the draft's `$signal`.
- Baseline: compare our waterfall against treg's routed `treg.people.email.find` on the same people.
