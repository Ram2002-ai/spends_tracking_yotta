# AI-Assisted Engineering Work Log

## Household Finance Synthetic Data Generator

> **Purpose:** This document records a professional, engineering-led way
> of directing an AI coding assistant during implementation. It focuses
> on requirements, architecture, design constraints, verification, and
> review---not on beginner-style instructions.
>
> **Accuracy note:** The prompts below are a polished, reconstructed set
> of examples. They are **not a verbatim transcript** of the prompts
> originally sent during development. Keep this distinction clear in any
> submission. The actual chat transcript should be exported separately
> and preserved unchanged if the submission guidelines request it.

------------------------------------------------------------------------

## 1. Engineering approach

I treated the coding assistant as an implementation and review aid. The
project direction was organized around explicit engineering concerns:

-   Translate the challenge brief into testable functional and
    non-functional requirements.
-   Inspect the existing repository before changing its structure.
-   Preserve established conventions and avoid unnecessary rewrites.
-   Separate generation, derivation, validation, evaluation, and export
    responsibilities.
-   Make synthetic data deterministic, reproducible, and scalable.
-   Validate correctness at both unit-test and full-run levels.
-   Document design trade-offs, limitations, setup, and AI assistance
    accurately.

The prompts below illustrate that workflow in a concise, senior-engineer
style.

------------------------------------------------------------------------

## 2. Prompt sequence

### Prompt 1 --- Repository assessment and implementation plan

``` text
Act as a senior Python engineer reviewing an existing codebase for a synthetic
household-finance data generation system.

First inspect the repository and the supplied challenge requirements. Do not
modify files yet.

Produce:
1. A concise requirements breakdown, separating functional requirements,
   quality constraints, and submission requirements.
2. An assessment of the existing modules and conventions.
3. A proposed module architecture with clear ownership and dependency
   boundaries.
4. A staged implementation plan, identifying dependencies and major risks.
5. Any assumptions or ambiguities that require confirmation.

Preserve useful existing code. Avoid broad rewrites and do not introduce
dependencies unless they provide a clear benefit.
```

### Prompt 2 --- Core architecture and data contracts

``` text
Implement the agreed foundation of the household-finance synthetic data
generator.

Establish explicit data contracts, stable identifiers, shared time utilities,
and configuration handling. Keep domain rules out of generic utility modules.

Engineering constraints:
- Use clear type hints and focused functions.
- Make configuration explicit rather than relying on hidden global state.
- Keep modules cohesive and avoid circular imports.
- Ensure generated identifiers are stable and reproducible from the configured
  seed and input context.
- Handle invalid configuration with actionable errors.

Before editing, summarize the files you intend to add or change. After editing,
explain the key design decisions and list the checks performed.
```

### Prompt 3 --- Domain model and generation pipeline

``` text
Build the domain and generation layers on top of the established contracts.

Keep catalog/reference data, recurring activity, transaction generation, and
derived attributes as distinct responsibilities. The pipeline should be
composable and should support small development runs as well as large
production-scale synthetic datasets.

Pay particular attention to:
- Consistent relationships between households, accounts, and transactions.
- Realistic date and amount constraints.
- Referential integrity across generated entities.
- Reproducibility when the same configuration and seed are used.
- Clear handling of edge cases and invalid input.

Do not silently weaken validation to make generated data pass. If a domain
rule conflicts with another rule, identify the conflict and resolve it at the
correct layer.
```

### Prompt 4 --- Validation and quality evaluation

``` text
Implement validation and dataset evaluation as separate stages.

Validation should check structural correctness, required fields, allowed
values, identifier uniqueness, referential integrity, and domain invariants.
Evaluation should report useful quality and distribution measures without
mutating the generated dataset.

Requirements:
- Return actionable diagnostics that identify the failed rule and affected
  records or fields where practical.
- Distinguish fatal errors from warnings.
- Avoid expensive repeated scans when a single indexed or grouped pass is
  sufficient.
- Make the output suitable for automated testing and command-line use.

Add focused tests for valid data, invalid data, boundary conditions, and
regression cases. Explain any checks that are intentionally approximate.
```

### Prompt 5 --- Export and command-line interface

``` text
Complete the export and command-line layers.

Provide a predictable interface for configuring a run, generating a dataset,
validating it, evaluating its quality, and exporting the requested outputs.

The CLI should:
- Expose the important configuration options with sensible defaults.
- Validate arguments before starting expensive work.
- Return meaningful exit codes.
- Print concise progress and summary information.
- Keep machine-readable outputs separate from human-readable console output.
- Avoid embedding business logic in command handlers.

Verify the documented commands against the actual implementation. Do not
document options or output files that have not been tested.
```

### Prompt 6 --- Scale, performance, and reproducibility review

``` text
Review the implementation for a large synthetic-data run (target scale:
500,000 transaction records).

Inspect likely memory and runtime bottlenecks before changing code. Prefer
measured improvements and straightforward algorithms over speculative
optimization.

Verify:
- Deterministic output for a fixed seed and configuration.
- No accidental quadratic processing in high-volume paths.
- Bounded or explainable memory use.
- Correct behavior across small and large dataset sizes.
- Stable export and validation behavior at the target scale.

Run an appropriately sized end-to-end test. Report the test configuration,
observed results, limitations, and any remaining performance risks. Do not
claim performance measurements that were not actually collected.
```

### Prompt 7 --- Test suite and regression hardening

``` text
Perform a test-coverage and regression review of the completed system.

Add or refine tests around the highest-risk contracts:
- Identifier generation and uniqueness.
- Date/time boundaries and recurring schedules.
- Transaction and account relationships.
- Schema and domain validation.
- Deterministic generation.
- Export behavior and CLI exit codes.
- Empty, minimal, malformed, and large inputs.

Keep tests independent and deterministic. Avoid tests that merely mirror
implementation details. Run the full suite and report the exact result,
including failures or skipped tests. Fix root causes rather than weakening
assertions.
```

### Prompt 8 --- Documentation and handover quality

``` text
Review the repository as if preparing it for an engineering handover.

Ensure the README explains:
- What the system does and what it does not attempt to model.
- Prerequisites and installation.
- Configuration and reproducible execution.
- CLI examples that have been verified.
- Output structure and validation/evaluation behavior.
- How to run tests.

Add concise engineering documentation for architecture, important design
trade-offs, assumptions, and known limitations. Keep the documentation
consistent with the current code. Do not invent implementation details or
claim unverified guarantees.
```

### Prompt 9 --- Final submission audit

``` text
Conduct a final submission-readiness audit against the challenge brief and
submission guidelines.

Do not make cosmetic changes blindly. First produce a checklist mapping each
requirement to its implementation, evidence, and status. Then inspect for:
- Missing or incomplete requirements.
- Reproducibility and setup problems.
- Tests or commands that fail from a clean checkout.
- Accidental generated files, secrets, or environment-specific paths.
- Inconsistent documentation.
- Missing disclosure of AI-assisted work, where required.

Make only justified corrections. Run the final verification commands and
provide a factual summary of what passed, what remains limited, and what
evidence should be included in the submission.
```

------------------------------------------------------------------------

## 3. Review and decision principles

The engineering decisions should be explainable independently of the
coding assistant:

1.  **Architecture before implementation:** define module boundaries and
    data contracts before building the pipeline.
2.  **Determinism as a system property:** use explicit seeds and test
    repeatability across runs.
3.  **Validation as a first-class stage:** report data-quality failures
    rather than hiding them during generation.
4.  **Scale-aware design:** test the target workload and optimize only
    where evidence supports it.
5.  **Separation of concerns:** keep domain logic, orchestration,
    evaluation, export, and CLI behavior distinct.
6.  **Evidence-based completion:** treat a feature as complete only when
    its behavior is verified.
7.  **Transparent AI assistance:** describe AI contributions accurately
    and retain the original transcript when requested.

## 4. Suggested evidence to retain

For a defensible engineering handover, retain the following artifacts
where they exist:

-   Original challenge brief and submission guidelines.
-   The actual exported AI conversation transcript.
-   Repository history and meaningful commits.
-   Test output from the final test run.
-   Output from the documented end-to-end and large-scale commands.
-   Design decisions and AI-use disclosures.
-   A clean project tree showing only intended deliverables.

## 5. Important submission note

This document is an **illustrative prompt plan**, not proof that these
exact prompts were used or that every decision originated with the
candidate. If the recruiter requests the complete conversation history,
provide the genuine exported transcript as a separate
`chat_transcript.*` file. Do not substitute this reconstructed document
for that transcript.
