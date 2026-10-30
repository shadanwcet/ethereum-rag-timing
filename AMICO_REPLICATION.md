# Replication and Verification Guide
## Study: Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559
**Authors**: Mohammad Pasha & Mohammed Ali Shaik (SR University)  
**Target Venue**: *PeerJ Computer Science*  
**Dataset DOI**: [10.5281/zenodo.10820011](https://doi.org/10.5281/zenodo.10820011)  
**Dataset SHA256**: `d5184d44032dd4aacadc90ce58c3d3e7603a03e510a1bc98f7477b756aab76a2`

---

### 1. One-Command Verification via Amico
If you have `amico` installed:
```bash
amico run ethereum-swap-timing --verify
```
This automatically executes:
1. Data Integrity and Contiguity Pre-flight (`320,730` contiguous blocks, 0 gaps).
2. Spatial KD-Tree Indexing and In-Sample Scaler Isolation.
3. Test Holdout Evaluation across all 8 execution policies.
4. TOST Equivalence Margin check ($\delta = \pm 0.40$ pp).
5. Cross-checks all generated numbers against `results/reconciliation.csv`.

---

### 2. Standalone Python Replication
If you are running in a standard Python virtual environment:
```bash
# 1. Install dependencies
pip install numpy pandas scipy matplotlib

# 2. Run the full reproducibility suite (rule-based + frontier)
python reproducibility_package/run_all.py --csv data/blocks.csv --no-llm

# 3. Check reconciliation results
cat reproducibility_package/results/reconciliation.csv
```

---

### 3. Reviewer Defense Dossier & Sensitivity Sweeps
To re-run the parameter sensitivity checks:
```bash
python reproducibility_package/reviewer_defense_sweeps.py
```
This computes:
* **Window Length Parity**: 1-day ($G=16$) vs 2-day ($G=9$) discretization invariance.
* **Priority Tip Sensitivity**: Impact of $\tau_{\text{tip}} \in [0.5, 1.5, 3.0, 5.0]$ gwei on fee reduction compression.
* **Lookback Memory Depth**: Trade-off between memory sparsity and regime drift ($L_{\text{look}} \in [2500, 5000, 10000]$).

---

### 4. Integrity and Machine-Verifiable Passport
The accompanying `passport.yaml` provides a cryptographic and tabular mapping of every reported figure, p-value, and confidence interval in `Manuscript.docx`.

