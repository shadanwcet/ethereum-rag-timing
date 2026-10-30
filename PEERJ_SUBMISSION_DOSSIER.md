# PeerJ Computer Science — Submission Portal Dossier

This document contains all pre-formatted, verified fields required by the [PeerJ Computer Science](https://peerj.com/computer-science/) submission portal. Copy and paste each section directly into the corresponding online form fields.

---

## 1. Article Title & Metadata

### Full Title
> **Matched-Wait Evaluation of Retrieval-Augmented Transaction Timing under Ethereum EIP-1559: Benchmarking kNN Analogs, Trailing-Rank Heuristics, and 7B Language-Model Planners**

### Short Title (Running Head)
> *Ethereum Base-Fee Timing Evaluation*

### Section / Subject Classifications
* **Primary Subject**: Distributed Computing and High Performance Computing
* **Secondary Subject**: Autonomous Systems & Agent-Based Modeling
* **Tertiary Subject**: Computational Economics & Financial Computing

---

## 2. Author Details & Institutional Affiliations

### Author 1 (Corresponding Author)
* **First Name**: Mohammad
* **Last Name**: Pasha
* **Email**: `mohd.pasha@outlook.com`
* **ORCID ID**: [0000-0002-0596-1682](https://orcid.org/0000-0002-0596-1682)
* **Institution**: SR University
* **Department**: Department of Computer Science & Engineering
* **City / State / Postal Code / Country**: Ananthasagar, Warangal 506371, Telangana, India
* **Role**: Postdoctoral Research Fellow
* **Corresponding Author?**: Yes

### Author 2 (Co-Author)
* **First Name**: Mohammed Ali
* **Last Name**: Shaik
* **Email**: `niharali@gmail.com`
* **ORCID ID**: [0000-0002-5520-0830](https://orcid.org/0000-0002-5520-0830)
* **Institution**: SR University
* **Department**: School of Computer Science and Artificial Intelligence
* **City / State / Postal Code / Country**: Ananthasagar, Warangal 506371, Telangana, India
* **Role**: Associate Professor
* **Corresponding Author?**: No

---

## 3. Structured Abstract

*(PeerJ word limit: under 450 words; Current: 382 words)*

```text
Background. Execution-timing decisions, such as deferring an Ethereum transaction within a short deadline, present an operational testbed for retrieval-augmented sequential decision making. An autonomous agent can query similar historical market states and act upon subsequent fee dynamics. However, whether analogue retrieval provides alpha beyond simple trailing-price heuristics once policies are evaluated at identical average waiting budgets remains largely untested.

Methods. We evaluated 316,800 contiguous Ethereum mainnet blocks (2024-01-01 to 2024-02-14 UTC; BigQuery public datasets) partitioned chronologically into library (LIB), calibration (CAL), and holdout test (TEST) windows. A swap transaction arriving at block t0 could defer execution up to a deadline of D = 50 blocks (10.0 minutes) and paid the base fee of its submission block plus a fixed 1.5 gwei tip (150,000 gas). We benchmarked submit-immediately, random-wait, a trailing percentile-rank heuristic, non-parametric kNN retrieval over causal state features, an ex-post oracle, and an open-weight 7B language model (qwen2.5:7b) with and without retrieved context. Heuristic and retrieval thresholds were matched to equal mean wait, and uncertainty was quantified using window-clustered bootstrap percentile intervals (3,000 resamples).

Results. On the calibration split, retrieved historical neighbors carried genuine predictive signal regarding achievable savings beyond trailing rank (incremental correlation r = +0.227, 95% cluster CI [+0.167, +0.267]). On holdout test windows, unconstrained kNN retrieval saved 5.25% [3.19, 7.31] but expanded wait to 261s, while the heuristic saved 4.61% [3.78, 5.40] at 165s. When deconfounded across the common support frontier (60s to 400s), the mean Pareto frontier gap was Delta = -0.14 pp (95% CI [-0.70, +0.46]). Because the confidence interval half-width (+/-0.58 pp) exceeds our pre-specified economic equivalence margin of +/-0.40 pp, the comparison is statistically inconclusive rather than an established tie. The 7B language model failed to outperform matched-wait baselines across all prompt configurations (retrieval vs. grid-matched heuristic: Delta = -1.05 pp [-2.61, +0.40]) and exhibited severe wording fragility on calibration ablations.

Conclusions. Although historical state retrieval captures non-redundant predictive signal, we found no statistical evidence that it improves the fee–wait frontier over a matched-wait trailing-rank heuristic. Apparent performance gains in unconstrained retrieval and LLM agents are confounded by waiting budget differences.
```

---

## 4. Keywords
Copy and paste as comma-separated or individual tags:
```text
Retrieval-augmented generation, k-nearest neighbors, Ethereum base fee, EIP-1559, transaction timing, large language models, causal deconfounding, matched-wait evaluation
```

---

## 5. Suggested Independent Referees

*Note: None of the suggested reviewers have collaborated with the authors, and none share institutional affiliations.*

1. **Prof. Tim Roughgarden**
   * **Affiliation**: Department of Computer Science, Columbia University & Head of Research, a16z crypto, USA
   * **Email**: `tim.roughgarden@gmail.com`
   * **Expertise**: Author of the seminal economic analysis of EIP-1559; algorithmic mechanism design and dynamic transaction fee mechanics.
   * **Reason**: Uniquely qualified to evaluate game-theoretic EIP-1559 mechanics, priority tip floors, and strategic bidder delays.

2. **Dr. Sarah Azouvi**
   * **Affiliation**: Flashbots & University College London, UK
   * **Email**: `sarah@flashbots.net`
   * **Expertise**: Empirical fee market dynamics, base-fee manipulation under EIP-1559, mempool modeling.
   * **Reason**: Domain expert in empirical on-chain gas dynamics and transaction inclusion guarantees.

3. **Dr. Lioba Heimbach**
   * **Affiliation**: Decentralized Systems and Network Security Group, ETH Zürich, Switzerland
   * **Email**: `hlioba@ethz.ch`
   * **Expertise**: DeFi trading behavior, decentralized exchange execution latency, MEV, and transaction timing under delay tolerance.
   * **Reason**: Expert in the operational trade-off between gas fee savings and DEX asset price slippage.

4. **Dr. Daesoo Lee**
   * **Affiliation**: Graduate School of Data Science, KAIST, South Korea
   * **Email**: `daesoo.lee@kaist.ac.kr`
   * **Expertise**: Retrieval-augmented time series forecasting (author of RAFT: Retrieval-Augmented Forecasting of Time-Series, ICML 2024).
   * **Reason**: Leading authority on non-parametric temporal neighbor retrieval and episodic time-series forecasting.

5. **Dr. Jason Milionis**
   * **Affiliation**: Department of Computer Science, Columbia University, USA
   * **Email**: `jason@cs.columbia.edu`
   * **Expertise**: Automated Market Makers, optimal stopping, and transaction fee mechanism design.
   * **Reason**: Evaluates the mathematical formulation of optimal stopping under stochastic queue dynamics.

### Opposed Referees
* `None` (no reviewers requested to be excluded).

---

## 6. Declarations & Formal Statements

### Data and Code Availability
```text
Historical Ethereum block headers are publicly available via Google Cloud BigQuery (bigquery-public-data.crypto_ethereum.blocks). A single unified Zenodo record (DOI: 10.5281/zenodo.10820011) contains the truncated contiguous evaluation dataset (blocks.csv, 9.8 MB, SHA256: d5184d44032dd4aacadc90ce58c3d3e7603a03e510a1bc98f7477b756aab76a2), precomputed feature caches, evaluation outputs, benchmark suites, and complete Python replication source code. In addition, blocks.csv is uploaded as PeerJ Supplemental Information (<30 MB), and the active codebase is mirrored on GitHub (https://github.com/shadanwcet/ethereum-rag-timing).
```

### Funding Statement
```text
This research was supported by internal computing facilities at SR University, utilizing Google Colab NVIDIA T4 compute resources. No external grant funding was received.
```

### Competing Interests
```text
The authors declare that they have no competing financial or non-financial interests.
```

### Ethics Approval & Informed Consent
```text
Not applicable. This study did not recruit human participants, use human biological material, involve animals, or conduct an intervention. The analyses used publicly available on-chain blockchain records, public or research-use datasets, and simulation outputs.
```

### Author Contributions (CRediT Taxonomy)
* **Mohammad Pasha**: Conceptualization, Methodology, Software, Formal analysis, Investigation, Data curation, Visualization, Writing - original draft, Writing - review & editing, Project administration.
* **Mohammed Ali Shaik**: Validation, Supervision, Writing - review & editing.
* *Both authors reviewed and approved the final manuscript and agree to be accountable for the work.*

---

## 7. Portal File Upload Package

Ensure the following files are uploaded in the PeerJ document manager:

| Portal File Role | Target File | Notes |
| :--- | :--- | :--- |
| **Main Manuscript File** | [`Manuscript.docx`](file:///G:/chatgpt-library/claud-2/Manuscript.docx) | Full editable source (10,782 words) with embedded high-res tables |
| **Figure 1** | `Figure1.png` | Incremental correlation of retrieved neighbors by rank tercile |
| **Figure 2** | `Figure2.png` | Fee reduction vs. mean waiting duration showing budget confounding |
| **Figure 3** | `Figure3_frontier_hardened.png` | Two-panel Pareto frontier audit & TOST equivalence margin |
| **Figure 4** | `Figure4.png` | Prompt ablation behavioral fragility curve |
| **Supplemental Information** | [`zenodo_deposit_final.zip`](file:///G:/chatgpt-library/claud-2/zenodo_deposit_final.zip) | Complete 14.2 MB replication package with `blocks.csv` and scripts |
| **Replication Manifest** | [`passport.yaml`](file:///G:/chatgpt-library/claud-2/passport.yaml) | Cryptographic claim-to-code verification map |

