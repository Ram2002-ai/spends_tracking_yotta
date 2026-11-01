# Household Finance Synthetic Data Generator

End-to-end synthetic data for the workflow **categorise transactions → map recurring payments →
compare household spending against budgets**. Pure Python standard library (3.9+), no installs needed.
Same generator for every scale; fixed seed `20261022`; byte-for-byte reproducible.

| Scale | Users | Transactions | Time (approx.) |
|---|---|---|---|
| `tiny` (tests) | 30 | 12,000 | < 1 s |
| `starter` | 100 | 30,000 | ~1 s |
| `full` (spec) | 1,000 | 500,000 (12 months of 2026) | ~20 s + export |

## Run it

```bash
python -m hfsynth generate --scale full --out output          # CSV + JSONL + SQL + docs + manifest
python -m hfsynth generate --scale starter --out output_starter
python -m hfsynth validate --out output                        # re-validate the exported CSVs
python -m hfsynth repro --scale starter --out output_repro     # generate twice, compare SHA-256
python -m hfsynth docs                                         # writes docs/DATA_DICTIONARY.md, docs/schema.sql
python -m unittest discover -s tests -v                        # 25 tests
```
Options: `--users N --txns N` (exact counts), `--seed S`, `--formats csv,json,sql`.
Windows: `run_all.bat` does docs + tests + starter + full + reproducibility in one go.

## Setup, configure, verify (for reviewers)

1. **Install**: Python 3.9+ only. There are no third-party dependencies, so `pip install` is not needed.
2. **Configure**: all tunables are in `hfsynth/config.py` (seed, anomaly rates, skip rate, unresolved-descriptor rate); scale via `--scale`.
3. **Run**: `python -m hfsynth generate --scale full --out output`.
4. **Verify key behaviour** (each should print PASS / identical):
   * `python -m unittest discover -s tests -v` - 25 tests, including negative tests that must fail on corrupted data.
   * `python -m hfsynth validate --out output` - 84 checks re-run on the exported CSVs.
   * `python -m hfsynth repro --scale starter --out output_repro` - two runs, identical SHA-256 per file.
   * Open `output/docs/evaluation_summary.md` - categorisation, spend, recurring and exception metrics.
   * Load `output/sql/seed.sql` into SQLite with `PRAGMA foreign_keys=ON`; `PRAGMA foreign_key_check` returns nothing.

## Submission documents
* [`docs/DECISIONS.md`](docs/DECISIONS.md) - problem reading, assumptions, decisions and trade-offs, testing, limitations.
* [`docs/AI_USAGE.md`](docs/AI_USAGE.md) - where AI was used, how heavily, and what I reviewed.
* [`docs/PROMPT_HISTORY.md`](docs/PROMPT_HISTORY.md) - prompt history.
* `tools/make_commits.bat` - builds a step-by-step commit history.

## What you get (`output/`)

| Path | Content |
|---|---|
| `data/*.csv`, `*.jsonl` | 15 input tables (see `docs/DATA_DICTIONARY.md`) |
| `ground_truth/*.csv`, `*.jsonl` | labels, anomaly registry, recurring occurrences, latent persona — **never features** |
| `sql/seed.sql`, `sql/ground_truth.sql` | DDL + batched INSERTs (loads in SQLite with `PRAGMA foreign_keys=ON`) |
| `docs/` | data dictionary, schema.sql, `validation_summary.md/json`, `evaluation_summary.md/json` |
| `manifest.json` | seed, parameters, command, row counts, SHA-256 of every file, source manifest |

## Design

**Entities** (PK / FK / cardinality in the dictionary): `user_profile` 1:N `account` 1:N `transaction`;
`merchant` 1:N `merchant_alias`; `merchant` N:M `category` via **bridge** `merchant_category`;
`category_rule` (effective-dated, versioned); `recurring_series` + `recurring_series_event`;
`budget` + `budget_event`; `insight`; `exception_case` + `case_event`.
Append-only history: `transaction`, `*_event` tables — nothing is overwritten.

**Generation order** (every stage has its own seeded RNG stream):
1. Master data: categories, 145 merchants + aliases, rules, users, accounts.
2. Recurring series (salary, rent, utilities, insurance, subscriptions, savings) with lifecycle
   events (raise, price change, cancellation, job change) → scheduled ledger rows.
3. Discretionary purchases (persona, income, seasonality, ambiguous merchants, unresolvable descriptors).
4. Labelled edge cases → 5. card payments **derived from statements** → 6. transfer duplicates.
7. IDs assigned chronologically (`TXN-2026-00000001`), categorisation by the rule engine,
   running balances and opening balances **derived** from the ledger.
8. Budgets from the user's plan + series amounts → cases from detection rules → insights from aggregations.

Outcomes are rule-derived, not independently random: e.g. card payment = statement balance (min $5),
budgets for rent/utilities/insurance/subscriptions come from the series amounts, insights from spend vs budget,
case resolution from a fixed per-type workflow (no label leakage).

**IDs**: `USR-000001`, `ACC-<user-id>-01`, `TXN-2026-00000001`, `BUD-<user-id>-2026-01-<category-code>`, `REC-000001`.

## Edge cases (all labelled in `ground_truth/gt_issue.csv`)

| # | Case | How it appears | Detection / label |
|---|---|---|---|
| E1 | Transfer counted as spending twice | extra `PURCHASE` row duplicating a transfer-out leg, descriptor not categorisable → `UNC` (spending) | rule CR1; `TRANSFER_DOUBLE_COUNT` |
| E2 | Refund treated as new expense | credit row typed `PURCHASE` (positive amount) | rule CR2; `REFUND_MISCLASSIFIED` |
| E3 | Recurring series skips incorrectly | interior occurrence of an ACTIVE monthly series not posted | rule CR5; `RECURRING_SKIPPED` + `gt_recurring_occurrence` |
| E4 | Timezone boundary | last local evening of a month → UTC month differs; local date stored separately | `TZ_BOUNDARY` (forced + natural crossings) |
| E5 | Budget categories ≠ taxonomy | ~4% of users carry legacy codes (`GROC`…), FK intentionally not enforced | rule CR4; `BUDGET_CATEGORY_MISMATCH` |

Validation proves labelled == observable for each case and that **no unlabelled instances** exist.
Other coverage: partial refunds, refunds after merchant closure, merchants opening/closing mid-year, rule
drift (`MARKET` keyword SHP→GRO on 1 Feb), ambiguous multi-category merchants, unresolvable aliases,
annual subscriptions (single occurrence → boundary for detectors), job changes, price changes.

## Reference rules used for evaluation
* **Ledger-policy spend**: exclude internal transfers and income; refunds net against spend (sign-based);
  bucket by **local** month; drop rows flagged CR1.  **Naive spend**: `|amount|` of `PURCHASE`/`RECURRING_DEBIT`, bucketed by **UTC** month.
* Truth spend = signed `true_spend_amount` in `gt_transaction`.

## Validation (86 checks) and measured results (full scale)
PK uniqueness, FK integrity, enums, ID patterns, types, required fields, date ordering, balance reconciliation
(`balance_after`, `closing_balance`), transfer net-zero, refund limits, card-payment derivation, lifecycle
(series/cases/budgets/merchants), duplicate rows, rule effective dates, edge-case labelling, ground-truth separation.
Typical full-scale results (`docs/evaluation_summary.md`): categorisation accuracy ≈ 0.94 (clean rows 1.00,
ambiguous merchants ≈ 0.59, unresolvable descriptors ≈ 0.46), spend WAPE naive/UTC ≈ 0.094 vs ledger-policy ≈ 0.065,
recurring baseline detector P ≈ 0.99 / R ≈ 0.99, CR1/CR2/CR5 P=R=1.0.

## Reproducibility
`python -m hfsynth repro` runs the pipeline twice and compares row counts and SHA-256 of every file
(`reproducibility_report.md`). Per-stage `random.Random("<seed>:<stage>:<id>")` streams; no dependence on
dict/set ordering, wall-clock time or platform.

## Provenance / lawful use
100% synthetic. No external, scraped or personal data; business names are fictional; MCC codes and US DST
rules are used only as public schema/logic inspiration. `manifest.json → source_manifest` records this.

## Layout
```
hfsynth/  config.py reference.py ids.py timeutil.py schema.py catalog.py recurring.py
          generate.py derive.py validate.py evaluate.py export.py cli.py
tests/    test_hfsynth.py        docs/  DATA_DICTIONARY.md, schema.sql (via `python -m hfsynth docs`)
```
