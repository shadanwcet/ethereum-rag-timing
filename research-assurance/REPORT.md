# Number-Level Provenance & Verification Report (PeerJ Computer Science)
**Project**: *Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559*  
**Date**: October 30, 2026  
**Implementation**: Dependency-free Standard Library (`trace.py` & `research-assurance` integration)

---

## 1. Verified Target Artifacts

All verification runs operate deterministically against the exact confirmed files:

| Artifact | Source File | SHA-256 Digest | Status |
| :--- | :--- | :--- | :--- |
| **Manuscript** | `D:\PeerJ\Manuscript.docx` (from `PeerJCSE.zip`) | `1d7e62a1b12fd145bb52b73063778cc2b76a183905455563f89d9ee4d480761f` | Verified |
| **Notebook** | `D:\Downloads\Supplementary_S1_executed_notebook_rebuilt (1).ipynb` | `74063ac223dbb8ddb4488000a582d56e28784b18f01d5e59ca9773a9339058d3` | Verified |
| **Reconciliation** | `D:\PeerJ\reconciliation.csv` | `1614e71ca8453f29ca1bf1be6065922de7e59014f2b5475e9f86edfd33916439` | Verified |
| **Blockchain Data** | `D:\PeerJ\data\blocks.csv` (316,800 blocks) | `d5184d44032dd4aacadc90ce58c3d3e7603a03e510a1bc98f7477b756aab76a2` | Verified |
| **Passport** | `D:\PeerJ\passport.yaml` (Dynamically Generated) | Programmatically derived from ledger | Verified |

---

## 2. Ledger Status (101 Audited Claims)

```
Ledger summary:
  regenerated (OK):     40 claims (recomputed deterministically by replication engine)
  recorded_output (OK): 61 claims (extracted directly from notebook cells 18, 44, 51, 53, 55, 60, 62, 71, 77, 82)
  unsourced:             0 claims
  discrepancies:         0 claims
```

All 101 audited numbers in the ledger match within their declared scientific tolerances:
- **`regenerated` tier (40 claims)**: Fully verified by re-execution against raw blockchain blocks.
- **`recorded_output` tier (61 claims)**: Declaratively extracted from executed cell outputs in Colab notebook S1.

---

## 3. Explicit Slot & Estimand Audit

Run via: `python trace.py slots --ledger ledger.json --manuscript Manuscript.docx`

### 3.1 All 15 Primary Literals in Tables 2 & 3 Confirmed
- `Table2.PanelA.fixed_10.fee_reduction`: `-0.58%` (Found in docx; ledger: `-0.58`)
- `Table2.PanelA.placebo.fee_reduction`: `-0.13%` (Found in docx; ledger: `-0.13`)
- `Table2.PanelA.no_retrieval.fee_reduction`: `+2.14%` (Found in docx; ledger: `2.14`)
- `Table2.PanelA.heuristic.fee_reduction`: `+4.61%` (Found in docx; ledger: `4.6114`)
- `Table2.PanelA.knn_static.fee_reduction`: `+3.11%` (Found in docx; ledger: `3.1121`)
- `Table2.PanelA.knn_rolling.fee_reduction`: `+5.25%` (Found in docx; ledger: `5.2457`)
- `Table2.PanelA.oracle.fee_reduction`: `+13.41%` (Found in docx; ledger: `13.41`)
- `Table2.PanelA.knn_rolling.vs_heuristic`: `+0.64` (Found in docx; ledger: `0.6343`)
- `Table2.PanelB.llm_no_context.fee_reduction`: `-0.98%` (Found in docx; ledger: `-0.98`)
- `Table2.PanelB.llm_retrieval.fee_reduction`: `+0.48%` (Found in docx; ledger: `0.48`)
- `Table3.matched_wait.high.diff`: `+0.09 pp` (Found in docx; ledger: `0.09`)
- `Table3.matched_wait.low.diff`: `+0.77 pp` (Found in docx; ledger: `0.77`)
- `Table3.frontier.hardened.gap`: `-0.14 pp` (Found in docx; ledger: `-0.14`)
- `Table3.frontier.hardened.margin`: `0.58` (Found in docx; ledger: `0.58`)
- `Table3.frontier.hardened.bound`: `0.40` (Found in docx; ledger: `0.40`)

### 3.2 Estimand Mismatch Resolution
1. **Holm $p = 0.0416$ in Table 2 Panel B**:
   - The manuscript Table 2 Panel B presents Holm $p = 0.0416$ beside the vs-grid-matched heuristic difference ($-1.05$ pp).
   - Provenance extraction confirms this $p$-value was actually derived from the comparison against the **unmatched 157s heuristic baseline** (where LLM difference is $-3.95$ pp, $p = 0.0416$).
   - *Status*: Explicitly flagged by `trace.py slots`. The Table 2 note documents this comparison structure.
2. **$+0.64$ vs $+0.63$ pp**:
   - Point subtraction: $5.25\% - 4.61\% = +0.64$ pp.
   - Paired per-window mean difference in Cell 53: $+0.6343$ pp $\approx +0.63$ pp `[95% Cluster CI: -1.24, +2.38]`.
   - *Status*: Documented in Table 2 footnote and Table A2.

---

## 4. Manuscript Number Inventory Coverage

Run via: `python trace.py inventory --ledger ledger.json --manuscript Manuscript.docx --out inventory.csv`

- **Total numerals in manuscript body**: 1,178 (citations, DOIs, URLs, and references excluded).
- **Decimal and percentage numerals**: 516.
- **Numerals matching verified ledger values**: 228 (44.2% direct coverage).
- **1-ulp rounding drift near-misses**: 39.

---

## 5. Verification Commands for Reviewers

Any reviewer can independently audit the results without specialized GPU setups or external dependencies:

```bash
# 1. Direct standalone verification
python trace.py verify --ledger ledger.json --notebook code/Supplementary_S1_executed_notebook_rebuilt.ipynb

# 2. Audit slot bindings & estimands against Manuscript.docx
python trace.py slots --ledger ledger.json --manuscript Manuscript.docx

# 3. Regenerate dynamic Reproducibility Passport
python trace.py passport --ledger ledger.json --out passport.yaml

# 4. Invoke via integrated research-assurance engine
python research-assurance/engine.py trace verify --ledger ledger.json --notebook code/Supplementary_S1_executed_notebook_rebuilt.ipynb

# 5. Run full test suite (22 unit tests)
python -m unittest discover -s research-assurance/tests
```
