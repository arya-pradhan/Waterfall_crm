# Waterfall report

Total spend through treg: **$0.3213** · cache replays (free): 17

## Email finding

| # | Provider | Attempts | Hit rate | Errors | Avg latency | Cost / attempt | Cost / hit | Checked | Accuracy | Cost / correct hit |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `quickenrich.people.email.find` | 29 | 62% | 0 | 356 ms | $0.0030 | $0.0048 | 0 | — | — |
| 2 | `trykitt.people.email.find` | 15 | 33% | 0 | 4790 ms | $0.0017 | $0.0050 | 0 | — | — |
| 3 | `tomba.people.email.find` | 15 | 40% | 0 | 10216 ms | $0.0036 | $0.0089 | 0 | — | — |
| 4 | `hunter.people.email.find` | 15 | 33% | 0 | 2742 ms | $0.0082 | $0.0245 | 0 | — | — |

**Head-to-head** — the same 15 people asked of every provider (8 found by at least one). Unique = found by this provider only:

| Provider | Found | Hit rate | Unique finds | Cost / hit |
|---|---|---|---|---|
| `quickenrich.people.email.find` | 4/15 | 27% | 0 | $0.0048 |
| `trykitt.people.email.find` | 5/15 | 33% | 0 | $0.0050 |
| `tomba.people.email.find` | 6/15 | 40% | 1 | $0.0089 |
| `hunter.people.email.find` | 5/15 | 33% | 2 | $0.0245 |

**Agreement with the majority answer** (people where 2+ providers answered):

- `trykitt.people.email.find`: 5/5 (100%)
- `tomba.people.email.find`: 5/5 (100%)
- `quickenrich.people.email.find`: 4/4 (100%)
- `hunter.people.email.find`: 3/3 (100%)

## People at a company

| # | Provider | Attempts | Hit rate | Errors | Avg latency | Cost / attempt | Cost / hit | Checked | Accuracy | Cost / correct hit |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `quickenrich.people.search` | 36 | 72% | 0 | 307 ms | $0.0000 | $0.0000 | 0 | — | — |
| 2 | `dropleads.people.search` | 10 | 10% | 0 | 1525 ms | $0.0000 | $0.0000 | 0 | — | — |
| 3 | `leadsforge.people.search` | 9 | 22% | 0 | 774 ms | $0.0000 | $0.0000 | 0 | — | — |

## Email verification

| # | Provider | Attempts | Hit rate | Errors | Avg latency | Cost / attempt | Cost / hit | Checked | Accuracy | Cost / correct hit |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `treg.people.email.verify` | 22 | 100% | 0 | 4645 ms | $0.0014 | $0.0014 | 0 | — | — |

## Google Maps sourcing

| # | Provider | Attempts | Hit rate | Errors | Avg latency | Cost / attempt | Cost / hit | Checked | Accuracy | Cost / correct hit |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `litescrape.google.serp.maps` | 1 | 100% | 0 | 11834 ms | $0.0001 | $0.0001 | 0 | — | — |
| 2 | `anyapi.google.serp.maps` | 4 | 25% | 3 | 8002 ms | $0.0004 | $0.0018 | 0 | — | — |

## Pipeline funnel

| Stage | Count |
|---|---|
| Companies sourced | 40 |
| …with a usable domain | 36 |
| …with ≥1 contact found | 29 |
| Contacts | 29 |
| …with an email | 22 |
| …email verified valid | 15 |
| …flagged wrong-company risk | 2 |
| Drafted | 0 |
| Contacted | 0 |
| Replied | 0 |
| Meeting | 0 |

_Hit rate ≠ accuracy. Accuracy comes from hand-checked samples (`outreach check`); cost per correct hit = cost per hit ÷ accuracy, and that is what should set provider order._
