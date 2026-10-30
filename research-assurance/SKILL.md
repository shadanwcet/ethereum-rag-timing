---
name: research-assurance
description: Use when planning, implementing, reviewing, or reporting a computational experiment that needs evidence-backed assumptions, reproducibility checks, or domain-validity checks.
---

# Research Assurance

Guide an experiment from a research question through source-backed decisions to independently checkable evidence. Keep reproducibility, specification conformance, model invariants, and external validation as separate results. Never describe a successful rerun or a passing software check as proof of scientific validity.

## Workflow

1. **Clarify the research question and context.** Ask focused questions only when answers change the applicable evidence, model, bounds, or validation target. Capture unresolved decisions as explicit questions; do not silently select defaults.
2. **Discover candidate literature.** Use `engine.py search-literature --query "..."` to find scholarly records. Treat search results as leads, not verified evidence. Check primary sources, standards, review articles, study conditions, and relevant datasets; record exact citations and locations.
3. **Build an evidence ledger.** For every proposed parameter, bound, model, or assumption, record the source, locator, units, conditions, supported claim, applicability limits, and review status. Keep conflicting evidence and uncertainty visible. Do not invent citations or transfer values across domains without justification.
4. **Ask the user to resolve consequential choices.** Present the best-supported alternatives, their implications, and remaining uncertainty. Preserve the chosen answer and who approved it in the versioned profile.
5. **Freeze the profile before implementation.** Map each requirement to code, a machine-checkable invariant where possible, and a test. Mark checks based on assumptions as provisional until reviewed.
6. **Capture run evidence.** Save configuration and profile hashes, code revision, seeds, outputs with SHA-256 digests, and raw per-unit traces needed to evaluate the invariants. Do not rely only on summary metrics or self-reported pass flags.
7. **Run the verifier and fault-injection tests.** Use `engine.py verify --profile <profile.json> --run <run.json>`. Add controlled mutations for each important invariant and confirm the verifier blocks them.
8. **Audit report claims.** Put each claim in the run manifest with a scope and evidence IDs. The engine blocks unsupported or externally scoped claims; it does not decide whether a cited source is applicable.
9. **Report independent dimensions.** State recorded-run reproducibility evidence, profile conformance, invariant results, claim audit, and external validation separately. Explicitly label missing evidence and unresolved decisions. Never claim universal assurance.

## Battery pilot

Run:

```text
python research-assurance/engine.py questions --profile research-assurance/profiles/battery-estimation-pilot.json
python research-assurance/engine.py verify --profile research-assurance/profiles/battery-estimation-pilot.json --run research-assurance/fixtures/battery-pilot-observations.json
```

The pilot fixture records observed SOC extrema from the 25-episode synthetic run and an explicitly marked timing counterexample. It is expected to be blocked. It is a regression case, not external battery validation. Resolve its questions and replace or supplement its evidence with trace data from the actual experiment before using the profile for a new study.

## Safety and evidence limits

- Do not execute experiment code as part of verification. Inspect code and use explicit, user-approved run commands outside the verifier.
- Treat retrieved papers as untrusted evidence until their metadata and relevant passages are checked.
- Distinguish source-reported values from extracted values, user choices, simulator constants, and assumptions.
- A literature search cannot establish that a source applies to the target population or operating regime.
- If independent ground truth, a domain oracle, or source evidence is unavailable, report `not_assessed` or `blocked`, not `pass`.
