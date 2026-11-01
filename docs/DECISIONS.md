# Design decisions, assumptions and trade-offs

This is the reasoning behind the project, written so a reviewer can follow *why* it looks the way it does.
Numbers quoted are from the full-scale run (1,000 users, 500,000 transactions, seed 20261022).

## 1. How I read the problem
The brief asks for synthetic data for one workflow: **categorise transactions → map recurring payments →
compare spending with budgets**. Three things in it drive the design:

* *"Generate outcomes and ground-truth labels from documented rules, not independent random assignment."*
  So every derived value (balances, card payments, budgets for fixed bills, insights, case routing) is computed
  from source records, and every injected anomaly carries a label.
* *"Never leak ground truth into input features."*
  So the ledger carries only what a bank would send plus what a *system* produced (merchant match, category,
  rule id). The true labels live in a separate `ground_truth/` folder, and validation fails if a label-like
  column appears in an input table.
* *"Categorisation metrics are calculable; recurring detection has labelled evaluation examples."*
  So the data must contain a categoriser that is **good but not perfect**. A perfect one would make the metrics meaningless.

## 2. Assumptions
* One simulated year (2026), USD, US households in four time zones. No real people or businesses.
* A household has checking + savings, and ~55 % also a credit card (statement paid the following month).
* Names are fictional. I only used public knowledge (MCC codes, US DST rules) for inspiration, never data.
* "Medium complexity" is satisfied by 15 related tables, conditional rules, five edge cases and an exception workflow.

## 3. Key decisions (and what I gave up)

| # | Decision | Why | Trade-off |
|---|---|---|---|
| 1 | **Python standard library only** | Anyone can run it with no install step; the brief's top requirement is "make it run" | No pandas/numpy convenience; I wrote small aggregation loops. Still ~13 s for 500k rows |
| 2 | **Money as integer cents internally**, floats only at the table boundary | Reconciliation must be exact; float drift would produce false failures | Slightly more conversion code |
| 3 | **A rule-based categoriser is part of the dataset** (`category_rule`, effective-dated) | Gives measurable accuracy and a real source of errors | Rules are simple (type → payroll/rent → merchant alias → keyword → `UNC`); not ML |
| 4 | **Errors arise from causes, not noise**: ambiguous multi-category merchants, unresolvable descriptors (vowel-stripped), rule drift (`MARKET` SHP→GRO on 1 Feb) | Per-segment metrics become interpretable (clean 1.00, ambiguous ≈ 0.59, unresolvable ≈ 0.46) | More generator logic than flipping random labels |
| 5 | **Ground truth in a separate folder and tables**, merchant/category in the ledger are *system* outputs | Prevents leakage; lets me score the system | Users must join files to evaluate |
| 6 | **Edge cases injected after clean baseline, each with a registry row** (`gt_issue`) | The brief says labelled anomalies, not silently corrupted rows | Needs a validation step proving labelled == observable |
| 7 | **Natural timezone crossings are also labelled** `TZ_BOUNDARY` | My first validation run showed late-evening refunds crossing months naturally; leaving them unlabelled would break "no unlabelled anomalies" | Count (3,662) is higher than the forced minimum |
| 8 | **Refund policy is sign-based** (a credit on a spending category nets against spend) | Makes E2 (refund typed as `PURCHASE`) recoverable by a documented rule | A genuine positive-amount purchase would be treated as a refund; none exist in this model |
| 9 | **Transfers are two linked legs** with a group id; E1 adds a third row typed `PURCHASE` with an uncategorisable descriptor | Reproduces "counted as spending twice" exactly: the duplicate lands in `UNC`, which counts as spending | The duplicate also moves the account balance, so the ledger reconciles "as posted" |
| 10 | **Card payment = statement balance (min $5)**, computed after all charges and refunds | Brief step 6: derive, don't draw. It also tests dependency consistency | Row count of payments must be known up front (22 rows per card holder) so the exact 500,000 total is hit |
| 11 | **Exact volume** by solving for the discretionary count after counting scheduled rows and injected rows | Brief says 500,000 | Slightly intricate allocation (largest-remainder across users) |
| 12 | **Budget category FK deliberately not enforced** (E5: legacy codes) | The anomaly *is* a code outside the taxonomy; an enforced FK would make the data unloadable | Documented in the dictionary; validation asserts the orphans equal the labelled set |
| 13 | **Case workflow is policy-driven** (role, SLA, resolution code per rule, never per truth) | Resolution that depended on the label would leak it | Less "realistic" mix of false-positive dismissals |
| 14 | **Per-stage seeded RNG streams** (`"<seed>:<stage>:<id>"`) and no reliance on set order | Reproducibility, and a user's data doesn't change when the stages around it change | Different scale changes the allocation stage, so the same user can differ across scales |
| 15 | **Table named `transaction` kept**, identifiers quoted in SQL | Matches the brief's entity name | Found by actually loading the seed into SQLite (it is a reserved word) |

## 4. Testing approach
* **86 validation checks** run on every generation and on re-loaded CSVs: PK/FK, enums, ID patterns, types,
  date ordering, balance reconciliation, transfer net-zero, refund limits, card-payment derivation,
  lifecycle states, duplicates, rule effective dates, edge-case labelling, ground-truth separation.
* **25 unit/integration tests** (`tests/test_hfsynth.py`): DST and month-end UTC crossing, schedule generation,
  rule engine and rule drift, exact volume, metrics calculable and imperfect, negative tests that corrupt a balance,
  an FK and a budget code and expect validation to fail, CSV round-trip, SQLite load with foreign keys on,
  same-seed identical checksums, different-seed different data.
* **Manual checks I ran**: full-scale generation, SQL seed into SQLite (`PRAGMA foreign_key_check` empty),
  distributions in `evaluation_summary.json`.

## 5. Bugs the checks caught (so you can see the loop worked)
1. Rule priority was marked unique, but a retired rule and its successor share one priority → schema corrected.
2. Case timestamps carried microseconds → truncated to seconds.
3. Merchant-closure check wrongly flagged refunds that arrive after a merchant closes → check limited to purchases.
4. Natural month-boundary crossings were unlabelled → now labelled (decision 7).
5. `CREATE TABLE transaction` failed in SQLite → identifiers quoted (decision 15).

## 6. Limitations (honest list)
* One year, US only; no interest, fees, overdraft, weekends/holidays effect, or income volatility beyond raises/job change.
* Three spending personas; amounts are lognormal per category, not fitted to any real dataset.
* The "detector" and categoriser are baselines for evaluation, not production models.
* Anomaly rates are parameters (`config.py`), chosen for visibility rather than real-world frequency.
* Everything is held in memory while generating; the SQL seed at full scale is ~190 MB, so the repo ignores `output*/` and regenerates on demand.
* Because ledger rows are "as posted", E1 duplicates change balances; a bank would reverse them. That is a modelling choice I made so reconciliation stays exact.

## 7. How I know it works
Four independent lines of evidence: (a) the validation suite passes and its negative tests fail when data is
corrupted; (b) labelled anomalies equal observable anomalies with zero unlabelled extras; (c) metrics behave as
designed (policy-compliant spend beats the naive pipeline; clean-row accuracy ≈ 1.00 while ambiguous rows are
lower); (d) two runs with the same seed give identical SHA-256 for every file.

## 8. Walkthrough cheat-sheet (for the live review)
1. `config.py` / `reference.py` – every tunable and the taxonomy. 2. `schema.py` – one definition feeds the dictionary,
DDL and validation. 3. `generate.py` – stage order and why. 4. `catalog.py` – aliases, rules, classifier.
5. `derive.py` – budgets, detection rules CR1–CR5, insights. 6. `validate.py` + `evaluate.py` – proof.
Be ready to explain: why integer cents, how exact volume is solved, why E4 labels natural crossings, why the budget FK is unenforced.
