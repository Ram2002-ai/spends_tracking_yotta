@echo off
rem Creates a readable commit history (one commit per logical step). Real timestamps - nothing is backdated.
rem Run once from the project root:  tools\make_commits.bat
rem Then:
rem   git branch -M main
rem   git remote add origin https://github.com/<you>/household-finance-synth.git
rem   git push -u origin main
if not exist .git git init
git add .gitignore && git commit -m "Add .gitignore (generated output is reproducible, not versioned)"
git add hfsynth/__init__.py hfsynth/config.py hfsynth/reference.py && git commit -m "Add run configuration and reference taxonomy, merchants and spending model"
git add hfsynth/ids.py hfsynth/timeutil.py && git commit -m "Add deterministic ID builders and DST-aware time helpers"
git add hfsynth/schema.py && git commit -m "Add schema registry: single source for data dictionary, DDL and validation"
git add hfsynth/catalog.py hfsynth/recurring.py && git commit -m "Add merchant catalogue, effective-dated rule engine and recurring series model"
git add hfsynth/generate.py && git commit -m "Add staged ledger generator with labelled edge cases and derived balances"
git add hfsynth/derive.py && git commit -m "Add budgets, detection rules CR1-CR5, review cases and insights"
git add hfsynth/validate.py && git commit -m "Add validation suite: integrity, reconciliation, lifecycle, label checks"
git add hfsynth/evaluate.py hfsynth/export.py hfsynth/cli.py hfsynth/__main__.py && git commit -m "Add evaluation metrics, CSV/JSONL/SQL export, manifest and CLI"
git add tests && git commit -m "Add test suite incl. negative validation, SQLite load and reproducibility"
git add README.md run_all.bat docs tools && git commit -m "Add README, decision log, AI usage disclosure and prompt history"
git log --oneline
