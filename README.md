# Replication Package: Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Provenance: Verified](https://img.shields.io/badge/Provenance-VERIFIED__PASS-brightgreen.svg)](passport.yaml)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](reproducibility_package/requirements.txt)

This repository provides the complete, deterministic replication package, analysis code, answer caches, and number-level provenance ledger for:

> **Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559: Benchmarking kNN Analogs, Trailing-Rank Heuristics, and 7B Language-Model Planners**  
> *Mohammad Pasha and Mohammed Ali Shaik* (SR University)  
> Target Venue: *PeerJ Computer Science*

---

## Quick Start (Deterministic Replay)

### 1. Verify Claim Provenance (Zero External Dependencies)
Every number, p-value, and confidence interval in the manuscript results can be verified directly using Python's standard library:

```bash
# Verify 101 audited manuscript numbers against executed outputs
python trace.py verify --ledger ledger.json --notebook code/Supplementary_S1_executed_notebook_rebuilt.ipynb

# Regenerate dynamic Reproducibility Passport
python trace.py passport --ledger ledger.json --out passport.yaml
```

### 2. Full Replication from Raw Blockchain Data
To recompute the complete suite (empirical test holdouts, matched-wait deconfounding, and continuous Pareto frontier audits):

```bash
# Install dependencies
pip install -r reproducibility_package/requirements.txt

# Run full replication (replays cached LLM answers deterministically)
python reproducibility_package/run_all.py --csv data/blocks.csv --mode cache

# Rule-based baselines only (CPU only, ~30 seconds)
python reproducibility_package/run_all.py --csv data/blocks.csv --no-llm
```

---

## Directory Structure

```text
├── README.md               # Main replication guide
├── LICENSE                 # MIT License
├── passport.yaml           # Cryptographic claim passport (VERIFIED_PASS, 101 claims)
├── trace.py                # Dependency-free number-level provenance verifier
├── ledger.json             # 101-claim machine-readable verification ledger
├── reconciliation.csv      # Tabular claim reconciliation ledger
├── code/                   # Primary executed Colab notebook (Supplementary S1)
├── data/                   # Contiguous Ethereum base-fee dataset (316,800 blocks)
├── cache/                  # Exact prompt answer caches for deterministic verification
├── results/                # High-resolution figures and CSV benchmark tables
└── reproducibility_package/# Standalone Python package and CLI runner
```

---

## Provenance and Verification

The repository includes a machine-verifiable claim audit ledger ([`ledger.json`](ledger.json)) and reproducibility passport ([`passport.yaml`](passport.yaml)). 

- **101 Audited Claims**: 40 recomputed deterministically from raw block headers, 61 extracted declaratively from executed Colab notebook outputs.
- **0 Discrepancies**: 100% of reported values in the primary tables fall within their declared scientific tolerances.
- **Invariants Enforced**: Causal zero-lookahead, in-sample scaler isolation, scale invariance, and boundary seam guards.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
