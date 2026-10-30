# Prompt ablation v2 (CAL only)

Model `qwen2.5:7b` digest `mock` | mock=True | swaps=104 | windows=13 | states/swap=11 | decision options {'temperature': 0.0, 'seed': 42, 'num_predict': 5}
Determinism re-query agreement: 100.0% | distinct neighbour episodes (of 10): 9.60
Sign convention: saving = -yhat >= 0. Correct behaviour => NEGATIVE coefficient on saving (paper's +0.23 on yhat == -0.23 on saving == correct direction).

## A. Paper-comparable model: P(SUBMIT) ~ rank + saving(true mean) + vs_arrival + w   [standardised]

```
variant             |  rows| SUBMIT|  @w=0| inval| coef(sav)       swap 95% CI        win 95% CI Holm(win) | verdict
v0_no_retrieval     |  1040|   0.41|  0.33|  0.00|     +0.11 [ -0.16, +0.37] [ -0.17, +0.41]       nan | undetected (CI incl 0)
v2_paper_baseline   |  1040|   0.41|  0.31|  0.00|     -0.09 [ -0.33, +0.14] [ -0.36, +0.18]     1.000 | undetected (CI incl 0)
v3_positive_saving  |  1040|   0.41|  0.31|  0.00|     -0.15 [ -0.36, +0.09] [ -0.33, +0.07]     1.000 | undetected (CI incl 0)
v4_rules            |  1040|   0.42|  0.37|  0.00|     -0.13 [ -0.40, +0.11] [ -0.44, +0.17]     1.000 | undetected (CI incl 0)
v5_counterfactual   |  1040|   0.39|  0.30|  0.00|     +0.17 [ -0.09, +0.43] [ -0.08, +0.43]     1.000 | undetected (CI incl 0)
v6_reorder          |  1040|   0.39|  0.30|  0.00|     +0.05 [ -0.27, +0.31] [ -0.20, +0.31]     1.000 | undetected (CI incl 0)
v7_no_deadline      |  1040|   0.41|  0.31|  0.00|     -0.15 [ -0.36, +0.09] [ -0.33, +0.07]     1.000 | undetected (CI incl 0)
v8_all_fixes        |  1040|   0.39|  0.29|  0.00|     +0.01 [ -0.26, +0.29] [ -0.23, +0.29]     1.000 | undetected (CI incl 0)
v9_placebo          |  1040|   0.41|  0.32|  0.00|     -0.00 [ -0.25, +0.30] [ -0.25, +0.34]       nan | undetected (CI incl 0)
```

## B. Marginal association (saving alone) and shown-statistic model

```
variant             | marg coef        win 95% CI | coef(shown med)        win 95% CI | P(SUBMIT) by saving quartile (low->high)
v0_no_retrieval     |     -1.26 [ -1.55, -1.02] |                               n/a | 0.76 0.49 0.24 0.15
v2_paper_baseline   |     -1.39 [ -1.68, -1.12] |           -0.12 [ -0.37, +0.14] | 0.76 0.48 0.26 0.12
v3_positive_saving  |     -1.44 [ -1.62, -1.22] |           -0.21 [ -0.42, -0.02] | 0.77 0.47 0.27 0.12
v4_rules            |     -1.34 [ -1.63, -1.09] |           -0.25 [ -0.58, +0.05] | 0.78 0.50 0.26 0.15
v5_counterfactual   |     -1.35 [ -1.61, -1.11] |           +0.07 [ -0.14, +0.29] | 0.75 0.47 0.24 0.12
v6_reorder          |     -1.45 [ -1.67, -1.20] |           +0.01 [ -0.23, +0.25] | 0.77 0.45 0.22 0.12
v7_no_deadline      |     -1.44 [ -1.62, -1.22] |           -0.21 [ -0.42, -0.02] | 0.77 0.47 0.27 0.12
v8_all_fixes        |     -1.44 [ -1.69, -1.17] |           -0.03 [ -0.30, +0.24] | 0.75 0.47 0.25 0.10
v9_placebo          |     -1.32 [ -1.59, -1.09] |           +0.12 [ -0.14, +0.40] | 0.76 0.48 0.26 0.14
```

Collinearity (VIF, first variant Model A): rank=2.43, sav_true=2.00, vs_arrival=1.43, w=1.01
corr(rank, saving) over all states = +0.71

## C. Policy outcome at matched wait (fee reduction %, mean over windows, window-bootstrap 95% CI)

```
variant             |  wait LLM/H/kNN|                  LLM |          LLM-heur (pp) |           LLM-kNN (pp) |          LLM-rand (pp)
v0_no_retrieval     | 14.6/14.5/14.7|  +3.04 [-0.58,+6.72] |    -3.20 [-6.16,-0.39] |    -4.36 [-6.83,-1.93] |    +2.63 [-0.12,+5.45]
v2_paper_baseline   | 14.3/14.0/14.2|  +3.07 [-0.92,+7.15] |    -3.02 [-6.44,+0.54] |    -4.39 [-7.50,-1.23] |    +2.66 [-0.53,+5.92]
v3_positive_saving  | 14.7/15.1/14.7|  +5.88 [+2.31,+9.16] |    -0.53 [-3.84,+2.82] |    -1.53 [-4.69,+1.43] |    +5.47 [+2.06,+8.55]
v4_rules            | 12.7/12.3/12.9|  +4.09 [+0.58,+7.33] |    -1.50 [-4.28,+1.04] |    -2.46 [-5.71,+0.41] |    +3.81 [+1.02,+6.15]
v5_counterfactual   | 16.7/16.9/16.7|  +2.67 [-1.52,+6.45] |    -3.69 [-6.85,-0.47] |    -5.57 [-9.13,-2.06] |    +2.18 [-0.32,+4.74]
v6_reorder          | 16.3/16.3/16.3|  +4.41 [+0.71,+8.24] |    -1.81 [-4.44,+0.78] |    -3.39 [-6.97,-0.13] |    +3.92 [+0.49,+7.13]
v7_no_deadline      | 14.7/15.1/14.7|  +5.88 [+2.31,+9.16] |    -0.53 [-3.84,+2.82] |    -1.53 [-4.69,+1.43] |    +5.47 [+2.06,+8.55]
v8_all_fixes        | 17.1/16.9/17.1|  +3.53 [-0.87,+7.39] |    -2.83 [-5.95,+0.08] |    -4.80 [-8.15,-1.73] |    +3.04 [+0.11,+5.88]
v9_placebo          | 15.9/15.8/16.0|  +2.37 [-1.19,+5.80] |    -4.15 [-6.58,-1.32] |    -5.47 [-8.24,-2.67] |    +1.95 [-1.16,+5.03]
```
Wait columns are in blocks; heuristic/kNN thresholds are fitted to match the LLM's mean wait on the same arrivals (one parameter, wait only, no price outcome used). Check the matched waits agree within ~1 block.

## D. How to read this

- v2 vs v3 isolates the sign/format of the printed saving; v4-v7 are single changes on top of v3; v8 stacks them.
- v0 (no retrieval) should show ~0 coefficient on saving; v9 (placebo) must show ~0 on TRUE saving (see Model B for the shown placebo value). If v3-v8 are also ~0, the model ignores the signal.
- v4/v8 give the decision rule in words: a correct sign there shows instruction-following, not signal discovery.
- A coefficient is called CORRECT/INVERTED only if the WINDOW-level CI excludes 0. With few windows this is conservative; swap-level CIs are shown for power.
- Not tested here: other model sizes, quantisations other than the Ollama default, other horizons, TEST data.