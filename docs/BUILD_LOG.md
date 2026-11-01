# Build log and engineering overview

Status: complete, all quality gates green. Implementation was produced with an AI assistant under my direction
(see [AI_USAGE.md](AI_USAGE.md) and [PROMPT_HISTORY.md](PROMPT_HISTORY.md)); rationale is in [DECISIONS.md](DECISIONS.md).

## 1. Goal
Deterministic synthetic data for *categorise transactions → map recurring payments → compare spend with budgets*:
1,000 users, 500,000 transactions, 12 months, labelled anomalies, separate ground truth, full validation.

## 2. Architecture
```
reference.py / config.py   taxonomy, merchants, spending model, tunables
        │
catalog.py ── merchants, aliases, effective-dated rules, classifier (system under test)
recurring.py ─ series model + shared schedule logic
        │
generate.py ── staged ledger build ─► derive.py ── budgets, detection rules, cases, insights
        │                                   │
schema.py (single source of truth) ◄── validate.py / evaluate.py ──► export.py ──► cli.py
```
Design principles: one schema registry feeding dictionary, DDL, loader and validation; integer cents internally;
per-stage seeded RNG streams; derived values computed from source rows; ground truth physically separated.

## 3. Modules
| Module | Responsibility |
|---|---|
| `schema.py` | 15 input + 4 ground-truth tables, relationships, DDL, data dictionary |
| `catalog.py` | 145 merchants, 214 aliases, 60 effective-dated rules, normaliser and classifier |
| `recurring.py` | Salary, rent, utility, insurance, subscription, savings series and schedules |
| `generate.py` | Users/accounts → scheduled rows → purchases → edge cases → card statements → duplicates → IDs/balances |
| `derive.py` | Budgets and adjustments, detection rules CR1–CR5, case workflow, insights |
| `validate.py` | 86 integrity, reconciliation, lifecycle and labelling checks |
| `evaluate.py` | Categorisation, merchant resolution, spend reconciliation, recurring and exception metrics |
| `export.py` | CSV / JSONL / SQL, manifest with SHA-256, CSV loader, reproducibility check |

## 4. Milestones
| # | Milestone | Outcome |
|---|---|---|
| M1 | Reference data and config | Taxonomy, merchants, spending and seasonality model |
| M2 | Schema registry | Dictionary, DDL and validation from one definition |
| M3 | Catalog and rule engine | Alias resolution, rule drift, ambiguity |
| M4 | Generator | Exact 500,000 rows; derived balances and card payments |
| M5 | Edge cases E1–E5 | Injected after clean baseline, each labelled |
| M6 | Derived layers | Budgets, cases with event history, insights |
| M7 | Validation and evaluation | Negative tests prove checks can fail |
| M8 | Packaging | Exporters, manifest, reproducibility, docs, commit plan |

## 5. Quality gates
| Gate | Command | Result |
|---|---|---|
| Unit and integration tests | `python -m unittest discover -s tests` | 25 pass |
| Data validation | `python -m hfsynth validate --out output` | 84/84 on exported CSV (86 in-memory) |
| Reproducibility | `python -m hfsynth repro --scale starter` | identical SHA-256 per file |
| SQL load | `seed.sql` into SQLite, foreign keys on | `foreign_key_check` empty |

## 6. Measured results (full scale)
Categorisation accuracy ≈ 0.94 (clean 1.00, ambiguous ≈ 0.59, unresolvable ≈ 0.46); spend WAPE 9.4 % naive/UTC vs
6.5 % ledger-policy; recurring detector P ≈ 0.99 / R ≈ 0.99; 1,707 skipped occurrences all flagged; generation ≈ 13 s.

## 7. Defects found and fixed during build
Non-unique rule priority assumption; microsecond timestamps; refund-after-closure false positive; unlabelled natural
timezone crossings; reserved word `transaction` in SQL.

## 8. Known limitations and roadmap
Single year and US time zones; baseline (non-ML) categoriser and detector; no fees or interest. Next steps: multi-year
generation, configurable anomaly profiles, CI workflow running tests and `repro`, a Parquet exporter.
