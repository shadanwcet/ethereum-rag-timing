#!/usr/bin/env python3
"""Regenerate every table and figure of the manuscript.

  python run_all.py --csv data/blocks.csv --mode cache            # replay shipped LLM answers (CPU, minutes)
  python run_all.py --csv data/blocks.csv --mode live             # query Ollama on a GPU (hours)
  python run_all.py --selftest                                    # synthetic data + mock LLM, software test only
"""
import argparse, json, os, platform, sys, time, hashlib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swaprepro import data, analyses as A, report as R
from swaprepro.llm import LLM, DEFAULT_DIGEST


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/blocks.csv")
    ap.add_argument("--mode", default="cache", choices=["cache", "live", "mock"])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default="results")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--skip", default="", help="comma list of: primary,harness,frontier,diagnostic,ablation")
    ap.add_argument("--no-llm", action="store_true", help="skip language-model arms (rule-based results only)")
    ap.add_argument("--cal-tx", type=int, default=8, help="swaps per CAL window in the prompt ablation")
    a = ap.parse_args()
    skip = set(x for x in a.skip.split(",") if x)
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)
    t0 = time.time()
    log = lambda *x: print(*x, flush=True)

    if a.selftest:
        a.mode = "mock"
        b = data.synthetic_base_fee()
        info = dict(rows=len(b), synthetic=True)
        log("!! SELFTEST: synthetic data and mock LLM. Numbers are meaningless; this only tests the software. !!")
        csv = os.path.join(a.out, "synthetic_blocks.csv")
        pd.DataFrame({"number": np.arange(len(b)), "base_fee_per_gas": b * 1e9}).to_csv(csv, index=False)
    else:
        csv = a.csv
        b, info = data.load_blocks(csv)
        info["sha256"] = hashlib.sha256(open(csv, "rb").read()).hexdigest()
    log(f"[data] {info}")

    results = dict(meta=dict(info=info, mode=a.mode, python=sys.version.split()[0], platform=platform.platform(),
                             numpy=np.__version__, pandas=pd.__version__, selftest=a.selftest))
    primary = h_static = h_roll = fr_init = fr_hard = diag = abl = None

    if "primary" not in skip:
        log("\n[A] Primary replay (1-day windows) -> Table 2, Figure 1")
        M1 = data.Market(b, W=7200, feature_mode="roll")
        log("   ", M1.summary())
        llm = None if a.no_llm else LLM(a.mode, cache_path=os.path.join(a.cache, "ollama_qwen2.5_7b_test_cache.json"))
        primary = A.run_primary(M1, llm, log=log)
        results["primary"] = primary
        t2 = R.table2(primary)
        t2.to_csv(os.path.join(a.out, "Table2_primary.csv"), index=False)
        R.fig1(primary, os.path.join(a.out, "Figure1.png"))
        log(t2.to_string(index=False))
        log("   kNN - heuristic:", primary["knn_vs_heur"])

    M2 = None
    if {"harness", "frontier"} - skip:
        M2 = data.Market(b, W=14400, feature_mode="roll")
        log("\n[B/C] 2-day windows:", M2.summary())
    if "harness" not in skip:
        log("\n[B] 2-day sensitivity harness (static and rolling retriever) -> Table 3")
        h_static = A.run_harness(M2, "static", matched=True, log=log)
        h_roll = A.run_harness(M2, "rolling", matched=True, log=log)
        results["harness_static"], results["harness_rolling"] = h_static, h_roll
    if "frontier" not in skip:
        log("\n[C] Wait-frontier audits -> Table 3, Figure 3")
        fr_init, fr_hard = A.frontier_audit(M2, "initial"), A.frontier_audit(M2, "hardened")
        results["frontier_initial"], results["frontier_hardened"] = fr_init, fr_hard
        R.fig3(fr_hard, os.path.join(a.out, "Figure3_frontier_hardened.png"))
        R.fig3(fr_init, os.path.join(a.out, "Figure3_frontier_initial.png"))
        log("   initial :", fr_init["verdict"], round(fr_init["mean_gap"], 2), "crossings", fr_init["crossings_s"])
        log("   hardened:", fr_hard["verdict"], round(fr_hard["mean_gap"], 2), "crossings", fr_hard["crossings_s"])
    if primary is not None or h_static is not None or fr_init is not None:
        t3 = R.table3(h_static, h_roll, fr_init, fr_hard, primary) if primary else None
        if t3 is not None:
            t3.to_csv(os.path.join(a.out, "Table3_sensitivity.csv"), index=False)
            log(t3.to_string(index=False))
    if "diagnostic" not in skip:
        log("\n[D] Retrieval-signal diagnostic (causal features) -> Table 4")
        M2c = data.Market(b, W=14400, feature_mode="causal")
        diag = A.diagnostic(M2c)
        results["diagnostic"] = diag
        t4 = R.table4(diag)
        t4.to_csv(os.path.join(a.out, "Table4_diagnostic.csv"), index=False)
        diag["strata"].to_csv(os.path.join(a.out, "Table4_strata.csv"), index=False)
        log(t4.to_string(index=False))
        log(diag["strata"].head(3).to_string(index=False))
    if "ablation" not in skip and not a.no_llm:
        log("\n[E] Prompt ablation on CAL (separate process) -> Table 5, Figure 2")
        abl = A.run_ablation(csv, a.cache, os.path.join(a.out, "ablation"), mode=a.mode, cal_tx_per_win=a.cal_tx, log=log)
        results["ablation"] = abl
        t5 = R.table5(abl)
        t5.to_csv(os.path.join(a.out, "Table5_ablation.csv"), index=False)
        R.fig2(abl, os.path.join(a.out, "Figure2.png"))
        log(t5.to_string(index=False))

    flat = R.flatten(primary, h_static, h_roll, fr_init, fr_hard, diag, abl)
    rec = R.reconcile(flat, os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected_results.json"))
    rec.to_csv(os.path.join(a.out, "reconciliation.csv"), index=False)
    n_ok, n_diff, n_na = (rec.status == "OK").sum(), (rec.status == "DIFFERS").sum(), (rec.status == "not run").sum()
    log(f"\n[reconciliation] {n_ok} match the manuscript, {n_diff} differ, {n_na} not run "
        f"(see {a.out}/reconciliation.csv). Selftest results are meaningless by construction." if a.selftest else
        f"\n[reconciliation] {n_ok} match the manuscript, {n_diff} differ, {n_na} not run (see {a.out}/reconciliation.csv)")
    results["reconciliation_summary"] = dict(ok=int(n_ok), differs=int(n_diff), not_run=int(n_na))
    results["meta"]["seconds"] = round(time.time() - t0, 1)
    json.dump(R.jsonable(results), open(os.path.join(a.out, "results.json"), "w"), indent=1)
    log(f"[done] {time.time()-t0:.0f}s -> {a.out}/")


if __name__ == "__main__":
    main()
