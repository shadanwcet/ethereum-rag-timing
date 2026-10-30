# Research Assurance

This first version pairs an LLM workflow skill with a small Python CLI. It discovers scholarly records through OpenAlex, keeps them explicitly marked as unreviewed candidates, asks for unresolved profile decisions, and checks run evidence against declared invariants. It uses only Python's standard library.

## Desktop app

On Windows, run `research-assurance\start_app.bat`. On any platform with Python 3.9 or newer, run:

```text
python research-assurance/desktop_app.py
```

The app binds only to `127.0.0.1`, chooses an available port by default, and opens the default browser. Stop it with Ctrl+C in the terminal. It has no login or remote hosting mode. Literature searches send only the search query to OpenAlex. Profile, configuration, run, and output files are read in the browser and sent to the loopback verifier; the verifier does not execute uploaded code.

The desktop verifier requires the exact profile file, exact config file, run manifest, and every output listed by that manifest. Output files are selected as a folder so their relative paths can be checked. The verifier computes hashes from uploaded bytes; it does not trust hashes computed by browser JavaScript.

## Commands

From the repository root:

```text
python research-assurance/engine.py search-literature --query "LFP state of charge estimation validation" --limit 10
python research-assurance/engine.py questions --profile research-assurance/profiles/battery-estimation-pilot.json
python research-assurance/engine.py verify --profile path/to/profile.json --run path/to/run.json --config path/to/config.json --output assurance-report.json
python -m unittest discover -s research-assurance/tests -v
```

The literature command uses OpenAlex as a discovery index. It returns metadata and links, not validated parameter values or proof that a paper applies. Review the paper itself and record the cited passage, units, population, conditions, and applicability rationale in the profile before recording a human-review attestation.

## Profile and run evidence

A profile records a stable `profile_id`, research question, unresolved/resolved questions, evidence entries, executable invariants, and external-validation status. Each invariant links to evidence IDs. Evidence marked `reviewed_attestation` must name a reviewer and review date; this records an attestation, not a cryptographic signature or independent verification by the tool.

A run JSON records `profile_id`, the exact profile file's `profile_sha256`, the configuration's `config_sha256`, a `run_id`, output paths and SHA-256 digests, raw trace fields, and optionally a claim ledger:

```json
{
  "run_id": "run-001",
  "profile_id": "my-profile-v1",
  "profile_sha256": "<sha256 of profile file>",
  "config_sha256": "<sha256 of exact config file>",
  "outputs": [{"path": "predictions.json", "sha256": "<sha256>"}],
  "replicates": [],
  "trace": {
    "soc_true_extrema_by_episode": [[0.2, 0.9]],
    "estimator_events": [
      {"event": "predict", "state_from_index": 0, "state_to_index": 1, "input_time_index": 0},
      {"event": "update", "state_time_index": 1, "measurement_time_index": 1}
    ]
  },
  "claims": [
    {"id": "C1", "text": "Claim scoped to this synthetic model", "scope": "synthetic_model", "evidence_ids": ["E1"]}
  ]
}
```

Output paths are resolved relative to the run manifest and may not escape its directory. To provide recorded-run reproducibility evidence, include at least two replicate records with matching profile IDs, configuration hashes, and output digests. This only compares recorded metadata; it does not rerun experiment code.

`verify` exits with code 1 when a configured check fails or evidence is missing, and code 2 for malformed inputs or operational errors. Supplying `--config` checks the actual configuration file against its manifest digest. Its report keeps reproducibility, profile decisions, invariants, artifact integrity, claim audit, external validation, and scientific validity separate. It will not mark scientific validity established. External empirical claims are blocked by this MVP.

## Battery pilot

The pilot profile is intentionally unresolved. Its observation fixture uses SOC extrema freshly measured from the supplied 25-seed simulation after the source changed: the current recorded trajectories remain within [0, 1], but raw clamp-count instrumentation is absent. Its timing counterexample records the predict-first branch advancing state to t=1 before updating with voltage from t=0. The fixture therefore demonstrates a bounds pass, a missing-trace block, and a timing failure; it is not itself a full, instrumented experiment run or external validation.

The engine never executes experiment code. Passing its configured checks is evidence about the supplied records and declared profile only—not a guarantee that the profile is correct or that a model describes physical batteries.
