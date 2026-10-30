# Replication Package: Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23799506.svg)](https://doi.org/10.5281/zenodo.23799506)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Provenance: Verified](https://img.shields.io/badge/Provenance-VERIFIED__PASS-brightgreen.svg)](reproducibility_package/passport.yaml)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](reproducibility_package/requirements.txt)

This repository provides the complete replication package, Colab execution notebook, answer caches, and provenance verification ledger for:

> **Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559: Benchmarking kNN Analogs, Trailing-Rank Heuristics, and 7B Language-Model Planners**  
> *Mohammad Pasha and Mohammed Ali Shaik* (SR University)  
> Target Venue: *PeerJ Computer Science*

---

## Directory Structure

```text
├── .gitignore                  # Git tracking exclusion rules
├── LICENSE                     # MIT License
├── README.md                   # Main repository guide
├── code/                       # Primary executed Colab notebook (Supplementary S1)
│   └── Supplementary_S1_executed_notebook_rebuilt.ipynb
└── reproducibility_package/    # Self-contained standalone replication package
    ├── README.md               # Replication package guide
    ├── requirements.txt        # Python dependency specification
    ├── problem.toml            # Benchmark specification & configuration
    ├── run_all.py              # CLI evaluation and verification runner
    ├── reproduce.ipynb         # Interactive replication notebook
    ├── reviewer_defense_sweeps.py  # Reviewer defense parametric sweep scripts
    ├── trace.py                # Number-level provenance verifier
    ├── ledger.json             # 105-claim machine-readable verification ledger
    ├── passport.yaml           # Reproducibility passport (VERIFIED_PASS)
    ├── expected_results.json   # Expected numerical results & tolerances
    ├── cache/                  # Shipped answer caches (ablation & test)
    ├── data/                   # Contiguous Ethereum block headers (blocks.csv)
    ├── results/                # Output figures, tables, and ablation logs
    ├── swaprepro/              # Core replication analysis library
    └── tests/                  # Selftests and fidelity verification
```

---

## Quick Start (Replication)

All replication commands are run inside `reproducibility_package/`:

```bash
cd reproducibility_package

# 1. Install dependencies
pip install -r requirements.txt

# 2. Replay all analyses deterministically using shipped caches (CPU only, a few minutes)
python run_all.py --csv data/blocks.csv --mode cache

# 3. Rule-based baselines only (CPU only, ~30 seconds)
python run_all.py --csv data/blocks.csv --no-llm

# 4. Verify number-level provenance ledger (zero external dependencies)
python trace.py verify --ledger ledger.json --notebook ../code/Supplementary_S1_executed_notebook_rebuilt.ipynb
```

---

## Provenance and Verification

The repository includes a machine-verifiable claim audit ledger ([`ledger.json`](reproducibility_package/ledger.json)) and reproducibility passport ([`passport.yaml`](reproducibility_package/passport.yaml)):

- **105 Audited Claims**: 72 recomputed deterministically from raw block headers, 33 extracted declaratively from executed Colab notebook outputs.
- **0 Discrepancies**: 100% of reported values in the primary tables fall within their declared scientific tolerances.
- **Invariants Enforced**: Causal zero-lookahead, in-sample scaler isolation, scale invariance, and boundary seam guards.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
