# Replication Package: Matched-Wait Evaluation of RAG Transaction Timing under Ethereum EIP-1559

Replication package for:
> **Matched-wait evaluation of retrieval-augmented transaction timing under Ethereum EIP-1559: kNN analogs, a trailing-rank heuristic and a 7B language-model planner.**

---

## 1. Directory Structure

```text
├── README.md                           # Replication guide, table-to-cell map, environment specs
├── LICENSE                             # MIT License
├── checksums.sha256                    # SHA-256 hashes of all included files
├── environment.txt                     # Output of `pip freeze`, GPU specs, and Ollama metadata
├── data/
│   └── blocks.csv                      # Contiguous Ethereum base-fee dataset (316,800 blocks)
├── cache/
│   ├── ollama_qwen2.5_7b_test_cache.json   # Primary exact answer cache (16 TEST windows, 96 swaps)
│   └── states_v*.csv                       # Full state-by-state traces for CAL prompt ablations (v0–v9)
├── code/
│   ├── mve_rag.py                                    # Standalone CLI evaluation script
│   └── Supplementary_S1_executed_notebook_rebuilt.ipynb  # Primary executed Colab notebook
└── docs/
    └── Supplementary_S1_executed_notebook_rebuilt.html   # Static archival rendering of notebook
    