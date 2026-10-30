#!/usr/bin/env python3
"""OPTIONAL QA: run the ORIGINAL notebook's analysis cells and this package on the same synthetic data and
check that they agree to 1e-9 (rule-based arms, rolling/static harness, matched step, both frontier audits,
diagnostic terciles, strata, prompts, cache keys). Usage:
    python tests/fidelity_against_original.py --notebook Copy_of_RAG83__2_.ipynb
"""
import argparse, contextlib, hashlib, io, json, os, sys, tempfile, time
import numpy as np, pandas as pd
from typing import Tuple, List, Dict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swaprepro import data, analyses as A
from swaprepro.llm import prompt_retrieval, prompt_no_context, SYS, LLM

ap = argparse.ArgumentParser(); ap.add_argument("--notebook", required=True); a = ap.parse_args()
tmp = tempfile.mkdtemp()
CSV = os.path.join(tmp, "blocks.csv")
b0 = data.synthetic_base_fee()
pd.DataFrame({"number": np.arange(len(b0)), "base_fee_per_gas": b0 * 1e9}).to_csv(CSV, index=False)
nb = json.load(open(a.notebook))
src = lambda i: "".join(nb["cells"][i]["source"])
patch = lambda s: (s.replace("/content/drive/MyDrive/NBA2026/3.5/blocks.csv", CSV).replace("plt.show()", "pass")
                    .replace("import matplotlib.pyplot as plt", 'import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt'))
res = []
def ok(name, x, y, tol=1e-9):
    good = bool(np.allclose(x, y, atol=tol, equal_nan=True)); res.append(good); print(("PASS  " if good else "FAIL  ") + name)
b, _ = data.load_blocks(CSV)
M1, M2, M2c = data.Market(b, 7200, "roll"), data.Market(b, 14400, "roll"), data.Market(b, 14400, "causal")

# 1. primary (cell 23, no Ollama part) -----------------------------------------------------
s = src(23)
pre = s[s.index("# 2. Data Ingestion"):s.index("# 3. Validated v2 Prompt")]
pre = pre.replace("csv_candidates = ['blocks.csv', '/content/drive/MyDrive/NBA2026/3.5/blocks.csv', '/content/blocks.csv']", f"csv_candidates=['{CSV}']")
sec = s[s.index("# 3. Validated v2 Prompt"):s.index("async def call_llm_async")].replace(
    '"/content/drive/MyDrive/Experiments/rag_ethereum_cache" if os.path.exists("/content/drive/MyDrive") else "./rag_cache"', repr(tmp))
ns = {"CONC": 8, "MODEL_NAME": "qwen2.5:7b", "MODEL_DIGEST": "845dbda0ea48"}
exec("import numpy as np, pandas as pd, os, zlib, json, asyncio, urllib.request, time, hashlib, re\nfrom numpy.lib.stride_tricks import sliding_window_view as swv\n"
     "from scipy.spatial import cKDTree\nfrom scipy import stats\n" + pre + sec, ns)
tt, win, TEST, off, P = ns["tt"], ns["win"], ns["TEST"], ns["off"], ns["P"]
rts, yts = ns["rank"][tt[:, None] + off], ns["yhat"][tt[:, None] + off]
arms = {"baseline": np.zeros(len(tt), dtype=np.int32), "placebo": ns["w_plac"](tt, P["m"]),
        "heuristic": ns["w_heur_arr"](rts.copy(), P["q"]), "knn_retrieval": ns["w_knn_arr"](yts.copy(), P["tau"]),
        "oracle": ns["fwd"][tt].argmin(axis=1)}
cost = ns["cost"]; bc = cost(tt, np.zeros(len(tt), dtype=np.int32)); bm = {w: bc[win == w].mean() for w in TEST}
red = lambda w_arr: np.array([100 * (1 - cost(tt, w_arr)[win == w].mean() / bm[w]) for w in TEST])
r1 = A.run_primary(M1, None, log=lambda *x: None)
for k in arms: ok(f"primary {k}: per-window fee reduction", red(arms[k]), r1["cluster_reductions"][k])
ok("primary calibrated q and tau", [P["q"], P["tau"]], [r1["params"]["q"], r1["params"]["tau"]])
bad = 0
for i in ns["sub"][:60]:
    t0 = int(tt[i])
    for w in range(0, 51, 5):
        t = t0 + w
        bad += ns["prompt_for"](t, t0, w, True) != prompt_retrieval(M1, t, w, ns["nbr_lookup"][t])
        bad += ns["prompt_for"](t, t0, w, False) != prompt_no_context(M1, t0, t, w)
res.append(bad == 0); print(("PASS  " if bad == 0 else "FAIL  ") + f"LLM prompts byte-identical (1,320 compared, {bad} mismatches)")
p_ = ns["prompt_for"](t, t0, w, True)
k_ok = LLM("mock", cache_path=os.path.join(tmp, "x.json")).key(p_) == hashlib.sha256(("qwen2.5:7b" + "845dbda0ea48" + p_).encode()).hexdigest()
res.append(k_ok); print(("PASS  " if k_ok else "FAIL  ") + "cache key identical to original; system prompt " + ("identical" if ns["SYS"] == SYS else "DIFFERENT"))

# 2. rolling harness + matched (cells 30, 31) -----------------------------------------------
g = {}; exec(patch(src(30)), g); g2 = dict(g); exec(patch(src(31)), g2)
h = A.run_harness(M2, "rolling", matched=True, log=lambda *x: None)
for col in ["retrieval_red_%", "heuristic_red_%", "oracle_red_%", "placebo_red_%", "no_retrieval_red_%", "fixed_10_red_%"]:
    ok(f"rolling harness {col}", g["res_df"][col].to_numpy(), h["per_window"][col.replace("_red_%", "_red")].to_numpy())
ok("rolling freshness lag", g["res_df"]["mean_freshness_lag"].to_numpy(), h["per_window"]["mean_freshness_lag"].to_numpy())
ok("matched-wait pairs A and B", [g2["match_df"]["diff_pair_A"].mean(), g2["match_df"]["diff_pair_B"].mean()],
   [h["matched"]["A"]["diff_pp"], h["matched"]["B"]["diff_pp"]])

# 3. static harness (cells 28, 29) ----------------------------------------------------------
gs = {"Tuple": Tuple, "time": time, "np": np, "pd": pd, "List": List, "Dict": Dict}
cls = src(28); cls = cls[cls.index("class SpatialIndexRetriever"):cls.index("retriever = SpatialIndexRetriever")]
exec("import numpy as np, time\nfrom typing import Tuple\n" + cls, gs)
with contextlib.redirect_stdout(io.StringIO()): exec(patch(src(29)).replace("class StreamingSpatialIndexRetriever", "class _Unused"), gs)
hs = A.run_harness(M2, "static", matched=False, log=lambda *x: None)
for col in ["retrieval_red_%", "heuristic_red_%", "oracle_red_%", "placebo_red_%"]:
    ok(f"static harness {col}", gs["res_df"][col].to_numpy(), hs["per_window"][col.replace("_red_%", "_red")].to_numpy())
ok("static freshness lag", gs["res_df"]["mean_freshness_lag"].to_numpy(), hs["per_window"]["mean_freshness_lag"].to_numpy())

# 4. frontier audits (cells 33, 34) ---------------------------------------------------------
for cell, var in ((34, "hardened"), (33, "initial")):
    gg = {}
    with contextlib.redirect_stdout(io.StringIO()): exec(patch(src(cell)), gg)
    fr = A.frontier_audit(M2, var)
    ok(f"frontier {var}: mean gap and CI", [gg["mean_gap_stat"] if cell == 34 else gg["mean_gap"], gg["ci_lo"], gg["ci_hi"]],
       [fr["mean_gap"], fr["ci_lo"], fr["ci_hi"]])

# 5. diagnostic (cells 41, 42) --------------------------------------------------------------
gd = {}
with contextlib.redirect_stdout(io.StringIO()): exec(patch(src(42)), gd)
d = A.diagnostic(M2c)
for name, col in (("static", "resid_static"), ("rolling", "resid_rolling")):
    for lab in ["low", "mid", "high"]:
        s_ = gd["df_diag"][gd["df_diag"].rank_terc == lab]
        ok(f"diagnostic {name} / {lab}: incremental r", np.corrcoef(s_[col], s_["resid_y"])[0, 1],
           d["terciles"].query("retriever==@name and rank_tercile==@lab").r.iloc[0])
g41 = {}
with contextlib.redirect_stdout(io.StringIO()):
    exec(patch(src(34)), g41); exec(src(41), g41)
gp, mine = g41["df_grid"].set_index("stratum"), d["strata"].set_index("stratum")
ok("12 exploratory strata: r, CI, p, FDR q", gp[["incremental_r", "ci_lo", "ci_hi", "p_cluster", "q_fdr"]].to_numpy(),
   mine.loc[gp.index, ["r", "ci_lo", "ci_hi", "p_cluster", "q_fdr"]].to_numpy())
print(f"\n{sum(res)}/{len(res)} checks passed")
sys.exit(0 if all(res) else 1)
