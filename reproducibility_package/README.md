# Reproducibility package (Supplemental Code S1)

Regenerates every table and figure of **"Retrieving similar past market states to time Ethereum swaps: a matched-wait replay study with a small language-model arm"** from `blocks.csv` and, for the language-model rows, from shipped answer caches.

## Quick start

**Google Colab (recommended).** Upload this folder to Drive as `MyDrive/reproducibility_package`, add the two inputs below, open `reproduce.ipynb`, *Run all*. Default mode replays the language-model answers from cache: **CPU only, a few minutes**.

**Command line.**
```bash
pip install -r requirements.txt
python run_all.py --csv data/blocks.csv --mode cache      # replay cached LLM answers
python run_all.py --csv data/blocks.csv --mode live       # re-query Ollama qwen2.5:7b (GPU, about 1 h)
python run_all.py --csv data/blocks.csv --no-llm          # rule-based results only (no cache, no GPU)
python run_all.py --selftest                              # synthetic data + mock LLM, about 15 s, software test only
```

**Inputs you must add** (not shipped):
1. `data/blocks.csv` - see `data/README.md` (BigQuery query, 320,730 rows).
2. `cache/ollama_qwen2.5_7b_test_cache.json` and `cache/ablation_v2_llm_store.json` - see `cache/README.md`. Without them use `--mode live` or `--no-llm`.

## What regenerates what

| Manuscript item | Code | Output file(s) in `results/` |
|---|---|---|
| Table 2, Figure 1 (primary replay, 16 one-day windows; matched-wait notes) | `analyses.run_primary` | `Table2_primary.csv`, `Figure1.png` |
| Table 3 rows 1-5 (window length / retriever sensitivity, matched wait) | `analyses.run_harness` (static, rolling) | `Table3_sensitivity.csv` |
| Table 3 last rows, Figure 3 (wait-frontier audits, +/-1.0 and +/-0.40 pp) | `analyses.frontier_audit` | `Table3_sensitivity.csv`, `Figure3_*.png` |
| Table 4 and exploratory strata (retrieval-signal diagnostic) | `analyses.diagnostic` | `Table4_diagnostic.csv`, `Table4_strata.csv` |
| Table 5, Figure 2 (prompt ablation) | `swaprepro/ablation_v2.py` via `analyses.run_ablation` | `Table5_ablation.csv`, `Figure2.png`, `ablation/` |
| Check against the manuscript | `report.reconcile` + `expected_results.json` | `reconciliation.csv`, `results.json` |

## Reading `reconciliation.csv`
One row per number quoted in the manuscript Results (83 rows): `OK` (within tolerance), `DIFFERS` (update the manuscript or investigate), `not run`. With the same `blocks.csv` and cache files every row should be `OK`. Rule-based results are deterministic (all draws seeded). **New outputs** that the original notebook never printed: the CI for kNN minus heuristic in the primary run (`primary.knn_vs_heur`); add it to Table 2/3 of the manuscript.

## How faithful is this to the original notebook?
The original Colab notebook had 46 cells with several superseded versions. This package ports the cells that produced the reported numbers:

| Original cells | Port |
|---|---|
| 23 (primary TEST run) | `run_primary` |
| 28-31 (2-day static / rolling harness, matched step) | `run_harness` |
| 33, 34 (frontier audits) | `frontier_audit` (`initial`, `hardened`) |
| 41, 42 (diagnostic, strata, FDR) | `diagnostic` |
| prompt ablation (new script) | `ablation_v2.py` |

`tests/fidelity_against_original.py` executes the original notebook cells and this package on identical **synthetic** data and checks 30 quantities (per-window fee reductions, calibrated thresholds, matched-wait pairs, frontier gaps and CIs, diagnostic correlations, 12 strata with FDR, 1,320 LLM prompts byte-for-byte, cache keys). All 30 agree to 1e-9. This shows the port is faithful; it does **not** by itself show the real-data numbers (that is what `reconciliation.csv` is for), and the language model is not re-executed by the test.

Deliberate differences: (i) language-model calls run in threads instead of asyncio; (ii) the BigQuery project id was removed; (iii) the original cell 31's verdict "EQUIVALENCE CONFIRMED" when both CIs contain zero was **not** carried over (a CI containing zero does not establish equivalence); (iv) Holm correction for the ablation covers non-degenerate variants only; (v) the 2-day harness summarises neighbours with the median while the primary run, frontier audit and diagnostic use the mean (as in the original code).

## Layout
```
reproduce.ipynb         Colab notebook (sections A-F)
run_all.py              same analyses from the command line
expected_results.json   numbers reported in the manuscript + tolerances
swaprepro/              data.py  stats.py  llm.py  analyses.py  report.py  ablation_v2.py
tests/                  test_selftest.py (15 s smoke test), fidelity_against_original.py (optional QA)
data/  cache/           inputs (see their READMEs)
```

## Before you archive (Zenodo)
- [ ] Add `data/blocks.csv` hash (printed by the run) and both cache files; run once on the real data; confirm `reconciliation.csv` and update any `DIFFERS` rows in the manuscript.
- [ ] Choose a licence (add `LICENSE`), fill in the citation below, and mint the DOI.

Selftest and notebook executed with Python 3.12 on two library sets: NumPy 2.4 / pandas 3.0 / SciPy 1.17 / Matplotlib 3.10, and Colab-like NumPy 2.0.2 / pandas 2.2.2 / SciPy 1.14.1 / Matplotlib 3.9.2. Real-data runs have not been executed by the package author. Model: `qwen2.5:7b` (Ollama digest `845dbda0ea48`), temperature 0, seed 42, 5 output tokens.

**Citation:** <authors>. <year>. Reproducibility package for "Retrieving similar past market states to time Ethereum swaps". Zenodo. DOI: <to be assigned>.
