"""Tables, figures and the reconciliation against the values reported in the manuscript."""
import json, math, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 11})


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return jsonable(o.to_dict(orient="records"))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and math.isnan(o)) or (isinstance(o, np.floating) and np.isnan(o)) else float(o)
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    return o


def f2(x, d=2, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def ci(m, lo, hi, d=2):
    return f"{f2(m, d)} [{f2(lo, d)}, {f2(hi, d)}]"


# ------------------------------------------------------------------ tables
def table2(primary):
    t = primary["table"].copy()
    out = pd.DataFrame(dict(
        Arm=t["arm"], Swaps=t["n_swaps"], MeanWait_s=t["mean_wait_s"].round(0).astype(int),
        FeeReduction_pct_CI=[ci(a, b, c) for a, b, c in zip(t.fee_reduction, t.ci_lo, t.ci_hi)],
        DiffVsHeuristic_pp=[f2(x, 2, True) if x is not None and not pd.isna(x) else "-" for x in t.vs_heuristic_pp],
        HolmP=[f2(x, 3) if x is not None and not pd.isna(x) else "-" for x in t.holm_p]))
    return out


def table3(h_static, h_roll, fr_init, fr_hard, primary):
    rows = []
    k = primary["knn_vs_heur"]
    rows.append(["1-day windows, static library (primary)", primary["params"]["n_windows"],
                 f"{f2(k['diff_pp'],2,True)} [{f2(k['ci_lo'],2,True)}, {f2(k['ci_hi'],2,True)}]; Holm p = {f2(k['holm_p'],3)}",
                 f"{k['wait_knn_s']:.0f} s vs {k['wait_heur_s']:.0f} s"])
    if h_static:
        d = h_static["delta"]
        rows.append(["2-day windows, static library", len(h_static["per_window"]),
                     f"{f2(d['diff_pp'],2,True)} [{f2(d['ci_lo'],2,True)}, {f2(d['ci_hi'],2,True)}]",
                     f"{d['wait_ret_s']:.0f} s vs {d['wait_heur_s']:.0f} s"])
    if h_roll:
        d = h_roll["delta"]
        rows.append(["2-day windows, rolling 5,000-block look-back, unmatched", len(h_roll["per_window"]),
                     f"{f2(d['diff_pp'],2,True)} [{f2(d['ci_lo'],2,True)}, {f2(d['ci_hi'],2,True)}]",
                     f"{d['wait_ret_s']:.0f} s vs {d['wait_heur_s']:.0f} s"])
        m = h_roll.get("matched")
        if m:
            A, B = m["A"], m["B"]
            rows.append(["Same, heuristic matched to retrieval's wait", len(h_roll["per_window"]),
                         f"{f2(A['diff_pp'],2,True)} [{f2(A['ci_lo'],2,True)}, {f2(A['ci_hi'],2,True)}]",
                         f"{A['wait_ret_s']:.0f} s vs {A['wait_heur_matched_s']:.0f} s"])
            ok = abs(B["wait_ret_matched_s"] - B["wait_heur_s"]) <= 0.1 * B["wait_heur_s"]
            rows.append(["Same, retrieval matched to heuristic's wait" + ("" if ok else " (match failed: not interpretable)"),
                         len(h_roll["per_window"]), f"{f2(B['diff_pp'],2,True)} [{f2(B['ci_lo'],2,True)}, {f2(B['ci_hi'],2,True)}]",
                         f"{B['wait_ret_matched_s']:.0f} s vs {B['wait_heur_s']:.0f} s"])
    for fr in (fr_init, fr_hard):
        if fr:
            rows.append([f"Frontier audit, {fr['support_s'][0]:.0f}-{fr['support_s'][1]:.0f} s, margin +/-{fr['margin']:.2f} pp (static library)",
                         "9" if True else "", f"{f2(fr['mean_gap'],2,True)} [{f2(fr['ci_lo'],2,True)}, {f2(fr['ci_hi'],2,True)}]; {fr['verdict']}",
                         "matched along frontier"])
    return pd.DataFrame(rows, columns=["Configuration", "Windows", "kNN minus heuristic, pp [95% CI]", "Mean wait, kNN vs heuristic"])


def table4(diag):
    t = diag["terciles"]
    rows = []
    for lab in ["low", "mid", "high", "ALL"]:
        a = t[(t.retriever == "static") & (t.rank_tercile == lab)].iloc[0]
        r = t[(t.retriever == "rolling") & (t.rank_tercile == lab)].iloc[0]
        rows.append([lab.capitalize() if lab != "ALL" else "All", int(a.n), f"{f2(a.r,3,True)} [{f2(a.ci_lo,3,True)}, {f2(a.ci_hi,3,True)}]",
                     f"{f2(r.r,3,True)} [{f2(r.ci_lo,3,True)}, {f2(r.ci_hi,3,True)}]"])
    return pd.DataFrame(rows, columns=["Trailing-rank tercile", "Arrivals", "Static library r [95% CI]", "Rolling look-back r [95% CI]"])


def table5(abl):
    reg, pol = abl["regression"], abl["policy"]
    rows = []
    for v, r in reg.items():
        A = r.get("modelA") or {}
        B = r.get("modelB") or {}
        sa, sb = (A.get("sav_true") if A else None), (B.get("sav_shown") if B else None)
        deg = r.get("degenerate", False)
        f = lambda s: "n/a" if (deg or not s) else f"{f2(s['coef'],2,True)} [{f2(s['win']['lo'],2,True)}, {f2(s['win']['hi'],2,True)}]"
        p = pol[v]["llm_minus_heur"]
        rows.append([v, f2(r["submit_rate"], 2), f(sa), f(sb), "degenerate (near-constant answers)" if deg else "",
                     f2(pol[v]["wait_llm"], 1), f"{f2(p[0],2,True)} [{f2(p[1],2,True)}, {f2(p[2],2,True)}]"])
    return pd.DataFrame(rows, columns=["Variant", "SUBMIT rate", "Coef on saving (true mean) [95% CI, windows]",
                                       "Coef on saving shown [95% CI]", "Note", "Mean wait (blocks)",
                                       "Minus heuristic at matched wait, pp [95% CI]"])


# ------------------------------------------------------------------ figures
def fig1(primary, path):
    t = primary["table"].set_index("arm")
    order = [("baseline", "Submit now"), ("placebo", "Placebo"), ("heuristic", "Trailing-rank\nheuristic"),
             ("knn_retrieval", "kNN\nretrieval"), ("oracle", "Hindsight\noracle"),
             ("llm_no_context", "LLM, no\ncontext"), ("llm_retrieval", "LLM, with\nretrieval")]
    order = [(a, b) for a, b in order if a in t.index]
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=300)
    cols = {"baseline": "#9e9e9e", "placebo": "#9e9e9e", "heuristic": "#1f77b4", "knn_retrieval": "#ff7f0e",
            "oracle": "#2ca02c", "llm_no_context": "#8c564b", "llm_retrieval": "#8c564b"}
    for i, (a, lab) in enumerate(order):
        r = t.loc[a]
        ax.bar(i, r.fee_reduction, color=cols[a], hatch="//" if a.startswith("llm") else "", edgecolor="black", width=0.65)
        ax.errorbar(i, r.fee_reduction, yerr=[[r.fee_reduction - r.ci_lo], [r.ci_hi - r.fee_reduction]], color="black", capsize=4)
        ax.text(i, max(r.ci_hi, r.fee_reduction) + 0.6, f"{r.fee_reduction:+.2f}%\nwait {r.mean_wait_s:.0f} s, n={int(r.n_swaps)}",
                ha="center", va="bottom", fontsize=8.5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([b for _, b in order], fontsize=9)
    ax.set_ylabel("Fee reduction vs. submit-now (%)")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout(); plt.savefig(path); plt.close()


def fig2(abl, path):
    names = {"v2_paper_baseline": "v2 paper prompt", "v3_positive_saving": "v3 saving printed positive",
             "v6_reorder": "v6 clauses reordered", "v8_all_fixes": "v8 all changes", "v9_placebo": "v9 placebo retrieval"}
    reg = abl["regression"]
    keep = [k for k in names if k in reg and reg[k].get("modelA") and not reg[k].get("degenerate", False)]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.8), dpi=300, sharey=True)
    for ax, mk, fk, ttl in zip(axs, ("modelA", "modelB"), ("sav_true", "sav_shown"),
                               ("A. True neighbour-mean saving", "B. Median saving shown in the prompt")):
        ys = np.arange(len(keep))[::-1]
        for y, k in zip(ys, keep):
            m = reg[k].get(mk)
            if not m:
                continue
            s = m[fk]
            ax.errorbar(s["coef"], y, xerr=[[s["coef"] - s["win"]["lo"]], [s["win"]["hi"] - s["coef"]]], fmt="o", color="black", capsize=4)
        ax.axvline(0, color="grey", ls="--")
        ax.set_yticks(ys); ax.set_yticklabels([names[k] for k in keep], fontsize=9)
        ax.set_title(ttl, fontsize=11); ax.grid(axis="x", alpha=0.25)
        ax.set_xlabel("Standardised logistic coefficient on saving\n(negative = correct direction)")
    plt.tight_layout(); plt.savefig(path); plt.close()


def fig3(fr, path):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5), dpi=200)
    g = np.array(fr["grid"])
    a1.plot(g, fr["heur_curve"], label="Trailing-rank heuristic", color="#1f77b4", lw=2)
    a1.plot(g, fr["knn_curve"], label="kNN retrieval", color="#ff7f0e", lw=2)
    a1.set_xlabel("Mean wait (s)"); a1.set_ylabel("Fee reduction vs submit-now (%)"); a1.legend(); a1.grid(alpha=0.4, ls="--")
    a2.plot(g, fr["gap_curve"], color="black", lw=2, label="Mean gap (kNN - heuristic)")
    a2.fill_between(g, fr["gap_lo"], fr["gap_hi"], color="gray", alpha=0.3, label="95% window-cluster CI")
    a2.axhline(0, color="red", ls="--", lw=1)
    a2.axhline(fr["margin"], color="green", ls=":", label=f"Equivalence margin (+/-{fr['margin']:.2f} pp)")
    a2.axhline(-fr["margin"], color="green", ls=":")
    a2.set_xlabel("Mean wait (s)"); a2.set_ylabel("Gap (pp)"); a2.legend(); a2.grid(alpha=0.4, ls="--")
    plt.tight_layout(); plt.savefig(path); plt.close()


# ------------------------------------------------------------------ reconciliation
def flatten(primary=None, h_static=None, h_roll=None, fr_init=None, fr_hard=None, diag=None, abl=None):
    f = {}
    if primary:
        for _, r in primary["table"].iterrows():
            a = r["arm"]
            f[f"primary.{a}.fee_reduction"], f[f"primary.{a}.wait_s"] = r.fee_reduction, r.mean_wait_s
            if r.holm_p is not None and not pd.isna(r.holm_p):
                f[f"primary.{a}.holm_p"] = r.holm_p
        for m in primary["matched"]:
            f[f"primary.matched.{m['comparator']}.diff"] = m["diff_pp"]
    for key, h in (("static", h_static), ("rolling", h_roll)):
        if not h:
            continue
        for _, r in h["table"].iterrows():
            f[f"harness.{key}.{r.arm}.fee_reduction"], f[f"harness.{key}.{r.arm}.wait_s"] = r.fee_reduction, r.mean_wait_s
        d = h["delta"]
        f[f"harness.{key}.delta"], f[f"harness.{key}.delta_lo"], f[f"harness.{key}.delta_hi"] = d["diff_pp"], d["ci_lo"], d["ci_hi"]
        f[f"harness.{key}.freshness_lag"] = h["freshness_lag"]
        if h.get("matched"):
            for k in ("A", "B"):
                f[f"harness.{key}.matched{k}.diff"] = h["matched"][k]["diff_pp"]
                f[f"harness.{key}.matched{k}.lo"], f[f"harness.{key}.matched{k}.hi"] = h["matched"][k]["ci_lo"], h["matched"][k]["ci_hi"]
    for fr in (fr_init, fr_hard):
        if fr:
            v = fr["variant"]
            f[f"frontier.{v}.mean_gap"], f[f"frontier.{v}.lo"], f[f"frontier.{v}.hi"] = fr["mean_gap"], fr["ci_lo"], fr["ci_hi"]
    if diag:
        for _, r in diag["terciles"].iterrows():
            f[f"diag.{r.retriever}.{r.rank_tercile}.r"] = r.r
        s = diag["strata"]
        for _, r in s.iterrows():
            f[f"diag.stratum.{r.stratum}.r"], f[f"diag.stratum.{r.stratum}.q"], f[f"diag.stratum.{r.stratum}.n"] = r.r, r.q_fdr, r.n
    if abl:
        for v, r in abl["regression"].items():
            f[f"ablation.{v}.submit_rate"] = r["submit_rate"]
            if r.get("modelA"):
                s = r["modelA"]["sav_true"]
                f[f"ablation.{v}.coef"], f[f"ablation.{v}.coef_lo"], f[f"ablation.{v}.coef_hi"] = s["coef"], s["win"]["lo"], s["win"]["hi"]
            if r.get("modelB"):
                f[f"ablation.{v}.shown_coef"] = r["modelB"]["sav_shown"]["coef"]
            p = abl["policy"][v]
            f[f"ablation.{v}.wait_blocks"], f[f"ablation.{v}.vs_heur"] = p["wait_llm"], p["llm_minus_heur"][0]
    return f


def reconcile(flat, expected_path):
    exp = json.load(open(expected_path))["items"]
    rows = []
    for e in exp:
        got = flat.get(e["id"])
        if got is None or (isinstance(got, float) and math.isnan(got)):
            status, diff = "not run", None
        else:
            diff = got - e["expected"]
            status = "OK" if abs(diff) <= e["tol"] else "DIFFERS"
        rows.append(dict(id=e["id"], manuscript=e["table"], description=e["desc"], reported=e["expected"], regenerated=got,
                         difference=diff, tolerance=e["tol"], status=status))
    return pd.DataFrame(rows)
