# AI usage disclosure

## Approach
I built this project with a prompt-driven workflow: I scoped the work from the recruiter's brief, directed an
AI assistant (Claude, via claude.ai with filesystem and sandbox access) through prompts, and reviewed what it produced.
The prompts are in `PROMPT_HISTORY.md`.

## Division of work (stated plainly)
| Area | Who |
|---|---|
| Scope, requirements, choice of tool and target folder, decision to continue each stage | Me (prompts 1-4) |
| Schema, generator, rule engine, validation, evaluation, tests, documentation drafts | Claude generated these from the brief |
| Running and debugging in a sandbox (five bugs fixed, see `DECISIONS.md` §5) | Claude |
| Review, local verification, parameter changes, final acceptance | Me - see checklist below |

The implementation and design drafts are AI-generated. I am not claiming to have written them by hand.

## My review and validation
> Tick only what you actually did; add specifics. Reviewers may ask you to walk through any item.

- [ ] I read each module and can explain it: _(list modules)_
- [ ] I ran `python -m unittest discover -s tests` locally: _(date, result)_
- [ ] I generated the full dataset and inspected the output: _(what I looked at)_
- [ ] I ran `python -m hfsynth repro` locally: _(result)_
- [ ] Design choices I questioned, changed or rejected: _(list, or "none")_
- [ ] Parameters or rules I changed myself: _(list, or "none")_

## Provenance of pre-existing files
`hfsynth/config.py` and `hfsynth/reference.py` were in the folder before this session.
_(State who wrote them and whether AI was involved.)_

## Verification note
Reported results (86 validation checks, 25 tests, ~13 s for 500,000 rows, SQL seed loading in SQLite) were produced
in the assistant's sandbox. Items I have not re-run above remain AI-reported.
