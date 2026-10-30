"""All analyses reported in the manuscript. Each function maps to a table/figure (see README)."""
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from scipy import stats as sps

from .stats import boot_mean_ci, crc_seed, holm, bh_qvalues
from .llm import prompt_retrieval, prompt_no_context


# ---------------------------------------------------------------- shared helpers
def wait_from(cond):
    """Index of the first True decision point; the last point (deadline) is forced True."""
    c = cond.copy()
    c[:, -1] = True
    return c.argmax(axis=1)


def calibrate(target, matrix, lo, hi, is_rank):
    """Bisection for the threshold whose mean wait (in decision-grid steps) equals target."""
    for _ in range(25):
        mid = (lo + hi) / 2.0
        cond = (matrix <= mid) if is_rank else (matrix > -mid)
        if wait_from(cond).mean() > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ================================================================= A. PRIMARY REPLAY (Table 2, Fig 1)
def run_primary(M, llm=None, target_wait=12.0, per_window=100, llm_tx=6, seed_cal=11, seed_test=22, log=print):
    """16 one-day TEST windows (when M was built with W=7200). llm=None skips the language-model arms."""
    b, D, STEP, TIP, K = M.b, M.D, M.STEP, M.TIP, M.K
    CAL, TEST = M.CAL, M.TEST
    yhat = M.yhat_mean([CAL, TEST])
    off = np.arange(D + 1)
    c_arr = M.arrivals(CAL, 300, seed_cal)
    ci = c_arr[:, None] + off
    P = dict(q=calibrate(target_wait, M.rank[ci], 0.0, 1.0, True),
             tau=calibrate(target_wait, yhat[ci], 0.0, 0.3, False), m=min(D, 2 * target_wait))
    tt = M.arrivals(TEST, per_window, seed_test)
    win = np.repeat(TEST, per_window)
    sub = np.concatenate([np.where(win == w)[0][:llm_tx] for w in TEST])
    ti = tt[:, None] + off
    cost = lambda t0, w: b[t0 + w] + TIP

    arms = {
        "baseline": np.zeros(len(tt), dtype=np.int32),
        "placebo": np.minimum(np.random.default_rng(1).integers(0, int(P["m"]) + 1, len(tt)), D),
        "heuristic": wait_from(M.rank[ti] <= P["q"]),
        "knn_retrieval": wait_from(yhat[ti] > -P["tau"]),
        "oracle": M.fwd[tt].argmin(axis=1),
    }
    if llm is not None:
        cand = np.unique([int(t0 + w) for t0 in tt[sub] for w in range(0, D + 1, STEP)])
        _, nbr_ix = M.tree.query(M.Z[cand], K, workers=-1)
        nbr = {int(t): M.li[nbr_ix[i]] for i, t in enumerate(cand)}

        def wait_llm(t0, ctx):
            for w in range(0, D + 1, STEP):
                t = t0 + w
                p = prompt_retrieval(M, t, w, nbr[t]) if ctx else prompt_no_context(M, t0, t, w)
                ans = llm.decide(p)
                if ans.startswith("SUBMIT") or w + STEP > D:
                    return w if ans.startswith("SUBMIT") else D
            return D

        for name, ctx in (("llm_no_context", False), ("llm_retrieval", True)):
            log(f"  running {name} on {len(sub)} swaps ...")
            with ThreadPoolExecutor(max_workers=llm.conc) as ex:
                res = list(ex.map(lambda i: wait_llm(int(tt[sub[i]]), ctx), range(len(sub))))
            ws = np.zeros(len(tt), dtype=np.int32)
            ws[sub] = res
            arms[name] = ws
        llm.save()

    base_full = cost(tt, np.zeros(len(tt), dtype=np.int32))
    base_mean_full = {w: base_full[win == w].mean() for w in TEST}
    win_sub = win[sub]
    base_sub = cost(tt[sub], np.zeros(len(sub), dtype=np.int32))
    base_mean_sub = {w: base_sub[win_sub == w].mean() for w in TEST}

    def red_by_cluster(w_arr, is_sub=False):
        t_eval, w_eval = (tt[sub], w_arr[sub]) if is_sub else (tt, w_arr)
        win_eval, bm = (win_sub, base_mean_sub) if is_sub else (win, base_mean_full)
        c = cost(t_eval, w_eval)
        return np.array([100.0 * (1.0 - c[win_eval == w].mean() / bm[w]) for w in TEST])

    clusters = {n: red_by_cluster(w, n.startswith("llm")) for n, w in arms.items()}
    h_full, h_sub = clusters["heuristic"], red_by_cluster(arms["heuristic"], True)
    raw_p, deltas = {}, {}
    for n in [k for k in ("placebo", "knn_retrieval", "llm_no_context", "llm_retrieval") if k in arms]:
        diff = clusters[n] - (h_sub if n.startswith("llm") else h_full)
        deltas[n] = float(diff.mean())
        raw_p[n] = float(sps.ttest_1samp(diff, 0.0)[1])
    adj_p = holm(raw_p)

    rows = []
    for n, w in arms.items():
        idx = sub if n.startswith("llm") else np.arange(len(tt))
        m, lo, hi = boot_mean_ci(clusters[n], crc_seed(n))
        rows.append(dict(arm=n, n_swaps=len(idx), mean_wait_s=float(w[idx].mean() * 12), fee_reduction=m, ci_lo=lo,
                         ci_hi=hi, vs_heuristic_pp=deltas.get(n), holm_p=adj_p.get(n)))

    # NEW (not printed in the original notebook): paired kNN - heuristic difference with CI
    d = clusters["knn_retrieval"] - h_full
    dm, dlo, dhi = boot_mean_ci(d, crc_seed("paired_knn_vs_heur"))
    knn_vs_heur = dict(diff_pp=dm, ci_lo=dlo, ci_hi=dhi, wait_knn_s=float(arms["knn_retrieval"].mean() * 12),
                       wait_heur_s=float(arms["heuristic"].mean() * 12), holm_p=adj_p["knn_retrieval"])

    matched = []
    if "llm_retrieval" in arms:
        sub_tt, w_llm = tt[sub], arms["llm_retrieval"][sub]
        G5 = sub_tt[:, None] + np.arange(0, D + 1, STEP)
        rk, yh = M.rank[G5], yhat[G5]
        tg = w_llm.mean() / STEP
        wh = STEP * wait_from(rk <= calibrate(tg, rk, 0.0, 1.0, True))
        wk = STEP * wait_from(yh > -calibrate(tg, yh, 0.0, 0.3, False))

        def red_c(w_sub):
            c = cost(sub_tt, w_sub)
            return np.array([100.0 * (1.0 - c[win_sub == k].mean() / base_mean_sub[k]) for k in TEST])

        for nm, wb in (("heuristic", wh), ("kNN", wk)):
            dd = red_c(w_llm) - red_c(wb)
            bs = np.random.default_rng(crc_seed(f"paired_{nm}")).choice(dd, size=(3000, len(dd)), replace=True).mean(axis=1)
            matched.append(dict(comparator=nm, diff_pp=float(dd.mean()), ci_lo=float(np.percentile(bs, 2.5)),
                                ci_hi=float(np.percentile(bs, 97.5)), wait_llm_s=float(w_llm.mean() * 12),
                                wait_comp_s=float(wb.mean() * 12)))
    collapse = {nm: dict(zip(*[x.tolist() for x in np.unique(arms[nm][sub], return_counts=True)]))
                for nm in ("llm_no_context", "llm_retrieval") if nm in arms}
    return dict(table=pd.DataFrame(rows), matched=matched, knn_vs_heur=knn_vs_heur, collapse=collapse,
                params=dict(q=P["q"], tau=P["tau"], m=P["m"], n_windows=len(TEST), per_window=per_window, llm_tx=llm_tx),
                cluster_reductions={k: v.tolist() for k, v in clusters.items()})


# ================================================================= B. 2-DAY SENSITIVITY HARNESS (Table 3)
class StaticRetriever:
    """Static library (LIB windows only); neighbour summary = MEDIAN best saving (as in the 2-day harness)."""

    def __init__(self, M):
        self.M = M

    def yhat_median(self, idx):
        flat = idx.ravel()
        _, nb = self.M.knn(flat)
        return np.median(self.M.ybest[nb], axis=1).reshape(idx.shape)

    def lag(self, idx):
        _, nb = self.M.knn(idx)
        return idx - nb.max(axis=1)


class RollingRetriever:
    """Recency-constrained retriever: neighbours only from [t - lookback, t - D)."""

    def __init__(self, M, lookback=5000):
        self.M, self.L = M, lookback

    def _one(self, t):
        M = self.M
        s, e = max(0, t - self.L), max(0, t - M.D)
        if e - s <= M.K:
            return 0.0, 999999
        d2 = np.sum((M.Z[s:e] - M.Z[t]) ** 2, axis=1)
        nn = np.argpartition(d2, M.K)[: M.K]
        return float(np.median(M.ybest[s:e][nn])), int(t - (s + nn.max()))

    def yhat_median(self, idx):
        return np.array([self._one(int(t))[0] for t in idx.ravel()]).reshape(idx.shape)

    def lag(self, idx):
        return np.array([self._one(int(t))[1] for t in idx])


def run_harness(M, retriever="static", lookback=5000, arrivals_per_w=50, target=12.0, matched=True, log=print):
    """2-day windows (M built with W=14400). Replays 7 arms on TEST; optional two-sided matched-wait step."""
    b, D, STEP, TIP, W, H1 = M.b, M.D, M.STEP, M.TIP, M.W, M.H1
    ret = StaticRetriever(M) if retriever == "static" else RollingRetriever(M, lookback)
    grid = np.arange(0, D + 1, STEP)
    cal_arr = np.concatenate([np.random.default_rng(100 + w).integers(w * W + H1, (w + 1) * W - D - 2, 80) for w in M.CAL])
    cal_grid = cal_arr[:, None] + grid
    rank_cal = M.F[cal_grid, 4]
    cal_y = ret.yhat_median(cal_grid)

    def cal_heur(tgt):
        lo, hi = 0.0, 1.0
        for _ in range(25):
            mid = (lo + hi) / 2
            if (STEP * wait_from(rank_cal <= mid)).mean() > tgt:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def cal_ret(tgt):
        lo, hi = 0.0, 0.3
        for _ in range(25):
            mid = (lo + hi) / 2
            if (STEP * wait_from(cal_y > -mid)).mean() > tgt:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    Q, TAU = cal_heur(target), cal_ret(target)
    log(f"  [{retriever}] calibrated Q={Q:.4f} TAU={TAU:.4f}")

    def window_arrivals(w_idx):
        rng = np.random.default_rng(3000 + w_idx)
        return rng, rng.integers(w_idx * W + H1, (w_idx + 1) * W - D - 2, arrivals_per_w)

    recs = []
    for w_idx in M.TEST:
        rng, arr = window_arrivals(w_idx)
        g = arr[:, None] + grid
        w_p = np.array([rng.integers(0, D // STEP + 1) * STEP for _ in arr])      # sequential draws, as original
        yg = ret.yhat_median(g)
        waits = {
            "baseline": np.zeros(len(arr)), "placebo": w_p, "fixed_10": np.full(len(arr), 10.0),
            "no_retrieval": STEP * wait_from(b[g] <= 0.90 * b[arr][:, None]),
            "heuristic": STEP * wait_from(M.F[g, 4] <= Q),
            "retrieval": STEP * wait_from(yg > -TAU),
            "oracle": STEP * np.argmin(b[g], axis=1),
        }
        costs = {k: b[arr + w.astype(int)] + TIP for k, w in waits.items()}
        cb = costs["baseline"].mean()
        rec = {"window": int(w_idx), "mean_freshness_lag": float(np.mean(ret.lag(arr)))}
        for k in waits:
            if k != "baseline":
                rec[f"{k}_red"] = 100.0 * (1.0 - costs[k].mean() / cb)
            rec[f"{k}_wait_s"] = float(waits[k].mean() * 12.0)
        rec["diff_vs_heur_pp"] = rec["retrieval_red"] - rec["heuristic_red"]
        recs.append(rec)
    res = pd.DataFrame(recs)

    rows = []
    for arm in ["placebo", "fixed_10", "no_retrieval", "heuristic", "retrieval", "oracle"]:
        m, lo, hi = boot_mean_ci(res[f"{arm}_red"], 42)
        rows.append(dict(arm=arm, mean_wait_s=float(res[f"{arm}_wait_s"].mean()), fee_reduction=m, ci_lo=lo, ci_hi=hi))
    dm, dlo, dhi = boot_mean_ci(res["diff_vs_heur_pp"], 42)
    out = dict(retriever=retriever, table=pd.DataFrame(rows), per_window=res,
               delta=dict(diff_pp=dm, ci_lo=dlo, ci_hi=dhi, wait_ret_s=float(res["retrieval_wait_s"].mean()),
                          wait_heur_s=float(res["heuristic_wait_s"].mean())),
               freshness_lag=float(res["mean_freshness_lag"].mean()), Q=Q, TAU=TAU)

    if matched:
        wr, wh_ = out["delta"]["wait_ret_s"], out["delta"]["wait_heur_s"]
        Qm, Tm = cal_heur(wr / 12.0), cal_ret(wh_ / 12.0)
        recs2 = []
        for w_idx in M.TEST:
            _, arr = window_arrivals(w_idx)
            g = arr[:, None] + grid
            yg = ret.yhat_median(g)
            c = lambda wv: b[arr + wv.astype(int)] + TIP
            cb = c(np.zeros(len(arr))).mean()
            red = lambda wv: 100.0 * (1.0 - c(wv).mean() / cb)
            w_h, w_hm = STEP * wait_from(M.F[g, 4] <= Q), STEP * wait_from(M.F[g, 4] <= Qm)
            w_r, w_rm = STEP * wait_from(yg > -TAU), STEP * wait_from(yg > -Tm)
            recs2.append(dict(window=int(w_idx), red_heur=red(w_h), red_ret=red(w_r), red_heur_matched=red(w_hm),
                              red_ret_matched=red(w_rm), wait_heur_matched_s=float(w_hm.mean() * 12),
                              wait_ret_matched_s=float(w_rm.mean() * 12),
                              diff_pair_A=red(w_r) - red(w_hm), diff_pair_B=red(w_rm) - red(w_h)))
        m2 = pd.DataFrame(recs2)
        A, B = boot_mean_ci(m2["diff_pair_A"], 101), boot_mean_ci(m2["diff_pair_B"], 102)
        out["matched"] = dict(
            A=dict(diff_pp=A[0], ci_lo=A[1], ci_hi=A[2], wait_ret_s=wr, wait_heur_matched_s=float(m2["wait_heur_matched_s"].mean()),
                   desc="retrieval (as calibrated) minus heuristic matched to retrieval's wait"),
            B=dict(diff_pp=B[0], ci_lo=B[1], ci_hi=B[2], wait_ret_matched_s=float(m2["wait_ret_matched_s"].mean()),
                   wait_heur_s=wh_, desc="retrieval matched to heuristic's wait minus heuristic"),
            drift=dict(heur_cal_s=target * 12, heur_test_s=wh_, ret_test_s=wr))
    return out


# ================================================================= C. FRONTIER AUDIT (Table 3 rows, Fig 3)
FRONTIER_CFG = {
    "initial": dict(seed_base=4000, boot=2000, margin=1.0, clamp=False, pareto=False),
    "hardened": dict(seed_base=5000, boot=3000, margin=0.40, clamp=True, pareto=True),
}


def frontier_audit(M, variant="hardened", lo_s=60.0, hi_s=400.0, per_window=100):
    """kNN minus heuristic along the wait frontier (static library, mean summary, decision every block)."""
    cfg = FRONTIER_CFG[variant]
    b, D, TIP, W, H1, K = M.b, M.D, M.TIP, M.W, M.H1, M.K
    tt_l, win_l = [], []
    for w in M.TEST:
        rng = np.random.default_rng(cfg["seed_base"] + w)
        tt_l.append(rng.integers(w * W + H1, (w + 1) * W - D - 2, per_window))
        win_l.append(np.full(per_window, w))
    tt, win = np.concatenate(tt_l), np.concatenate(win_l)
    off = np.arange(0, D + 1)
    toff = tt[:, None] + off
    uniq, inv = np.unique(toff.ravel(), return_inverse=True)
    _, nb = M.tree.query(M.Z[uniq], K)
    ymat = M.ybest[M.li[nb]].mean(axis=1)[inv].reshape(toff.shape)
    rmat = M.rank[toff]
    base_c = b[tt] + TIP
    Q_GRID, TAU_GRID = np.linspace(0, 1, 51), np.linspace(0, 0.30, 61)

    def eval_pol(mat, t0, bc, thr, heur):
        cond = (mat <= thr) if heur else (mat > -thr)
        cond[:, -1] = True
        wi = off[cond.argmax(axis=1)]
        return (wi * 12).mean(), (100.0 * (1.0 - (b[t0 + wi] + TIP) / bc)).mean()

    nW = len(M.TEST)
    hw, hr = np.zeros((nW, len(Q_GRID))), np.zeros((nW, len(Q_GRID)))
    kw, kr = np.zeros((nW, len(TAU_GRID))), np.zeros((nW, len(TAU_GRID)))
    for i, w in enumerate(M.TEST):
        m = win == w
        for j, q in enumerate(Q_GRID):
            hw[i, j], hr[i, j] = eval_pol(rmat[m], tt[m], base_c[m], q, True)
        for j, tau in enumerate(TAU_GRID):
            kw[i, j], kr[i, j] = eval_pol(ymat[m], tt[m], base_c[m], tau, False)

    if cfg["clamp"]:
        lo = max(hw.mean(0).min(), kw.mean(0).min(), lo_s)
        hi = min(hw.mean(0).max(), kw.mean(0).max(), hi_s)
    else:
        lo, hi = lo_s, hi_s
    grid = np.linspace(lo, hi, 50)

    def interp(w, r):
        o = np.argsort(w)
        ws, rs = w[o], r[o]
        if cfg["pareto"]:
            rs = np.maximum.accumulate(rs)
        return np.interp(grid, ws, rs)

    hc = np.array([interp(hw[i], hr[i]) for i in range(nW)])
    kc = np.array([interp(kw[i], kr[i]) for i in range(nW)])
    gap = kc - hc
    mean_curve = gap.mean(axis=0)
    mean_gap = float(mean_curve.mean())
    rng = np.random.default_rng(2026)
    bi = rng.choice(nW, size=(cfg["boot"], nW), replace=True)
    bmeans = np.array([gap[i].mean() for i in bi])
    bcurves = np.array([gap[i].mean(axis=0) for i in bi])
    ci_lo, ci_hi = np.percentile(bmeans, [2.5, 97.5])
    mg = cfg["margin"]
    if ci_lo > 0:
        verdict = "kNN better"
    elif ci_hi < 0:
        verdict = "heuristic better"
    elif ci_lo >= -mg and ci_hi <= mg:
        verdict = f"equivalent within +/-{mg:.2f} pp"
    else:
        verdict = f"inconclusive (CI spans 0 and exceeds +/-{mg:.2f} pp)"
    cross = grid[np.where(np.diff(np.sign(mean_curve)))[0]]
    return dict(variant=variant, margin=mg, mean_gap=mean_gap, ci_lo=float(ci_lo), ci_hi=float(ci_hi), verdict=verdict,
                crossings_s=[float(x) for x in cross], grid=grid.tolist(), heur_curve=hc.mean(0).tolist(),
                knn_curve=kc.mean(0).tolist(), gap_curve=mean_curve.tolist(),
                gap_lo=np.percentile(bcurves, 2.5, axis=0).tolist(), gap_hi=np.percentile(bcurves, 97.5, axis=0).tolist(),
                support_s=[float(grid[0]), float(grid[-1])])


# ================================================================= D. RETRIEVAL-SIGNAL DIAGNOSTIC (Table 4)
def _inc_r(x, y, win, n_boot=2000, seed=42):
    """Correlation of rank-residualised kNN prediction and realised saving; bootstrap over windows."""
    wins = np.unique(win)
    if len(wins) < 2 or len(x) < 15:
        return np.nan, np.nan, np.nan, np.nan
    idx = {w: np.flatnonzero(win == w) for w in wins}
    r0 = np.corrcoef(x, y)[0, 1]
    rg = np.random.default_rng(seed)
    bs = []
    for _ in range(n_boot):
        sel = np.concatenate([idx[w] for w in rg.choice(wins, size=len(wins), replace=True)])
        if x[sel].std() < 1e-12 or y[sel].std() < 1e-12:
            continue
        bs.append(np.corrcoef(x[sel], y[sel])[0, 1])
    bs = np.array(bs)
    p = min(1.0, max(1.0 / n_boot, 2.0 * min(np.mean(bs <= 0), np.mean(bs >= 0))))
    return float(r0), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), float(p)


def diagnostic(M, per_window=300, seed=11, lookback=5000, n_boot=2000):
    """M must be built with feature_mode='causal' and W=14400. Returns tercile table and 12 exploratory strata."""
    b, D, K, H1 = M.b, M.D, M.K, M.H1
    ev = M.arrivals(M.CAL, per_window, seed)
    win = np.repeat(M.CAL, per_window)
    dists, nb = M.tree.query(M.Z[ev], K)
    kdist = dists.mean(axis=1)
    y_real = M.ybest[ev]
    y_static = M.ybest[M.li[nb]].mean(axis=1)
    rk = M.rank[ev]
    rolling = RollingRetriever(M, lookback)
    y_roll = np.array([np.nan if rolling._one(int(t))[1] == 999999 else rolling._one(int(t))[0] for t in ev])
    tstd = np.array([b[max(0, t - H1):t].std() for t in ev])
    dec = pd.qcut(rk, 10, labels=False, duplicates="drop")

    def resid(v):
        out = np.zeros_like(v, dtype=float)
        for d in np.unique(dec):
            m = dec == d
            out[m] = v[m] - np.nanmean(v[m])
        return out

    df = pd.DataFrame(dict(window=win, rank_terc=pd.qcut(rk, 3, labels=["low", "mid", "high"]),
                           std_terc=pd.qcut(tstd, 3, labels=["low", "mid", "high"]),
                           kdist_terc=pd.qcut(kdist, 3, labels=["close", "mid", "far"]),
                           res_y=resid(y_real), res_static=resid(y_static), res_roll=resid(y_roll)))
    rows = []
    for name, col in (("static", "res_static"), ("rolling", "res_roll")):
        d0 = df.dropna(subset=[col])
        for lab in ["low", "mid", "high", "ALL"]:
            s = d0 if lab == "ALL" else d0[d0.rank_terc == lab]
            r, lo, hi, p = _inc_r(s[col].to_numpy(), s["res_y"].to_numpy(), s["window"].to_numpy(), n_boot)
            rows.append(dict(retriever=name, rank_tercile=lab, n=len(s), r=r, ci_lo=lo, ci_hi=hi, p_cluster=p))
    terc = pd.DataFrame(rows)
    for name in ("static", "rolling"):                       # BH-FDR over the three terciles (primary family)
        m = (terc.retriever == name) & (terc.rank_tercile != "ALL")
        sub = terc[m].sort_values("p_cluster")
        terc.loc[sub.index, "q_fdr"] = bh_qvalues(sub["p_cluster"].to_numpy())
    grid = []
    for rl in ["low", "mid", "high"]:
        for sl in ["low", "high"]:
            for kl in ["close", "far"]:
                s = df[(df.rank_terc == rl) & (df.std_terc == sl) & (df.kdist_terc == kl)]
                if len(s) >= 15:
                    r, lo, hi, p = _inc_r(s["res_static"].to_numpy(), s["res_y"].to_numpy(), s["window"].to_numpy(), n_boot)
                    grid.append(dict(stratum=f"{rl}/{sl}/{kl}", n=len(s), r=r, ci_lo=lo, ci_hi=hi, p_cluster=p))
    strata = pd.DataFrame(grid).sort_values("p_cluster").reset_index(drop=True)
    strata["q_fdr"] = bh_qvalues(strata["p_cluster"].to_numpy())
    return dict(terciles=terc, strata=strata, n_arrivals=len(df), n_windows=len(M.CAL))


# ================================================================= E. PROMPT ABLATION (Table 5, Fig 2)
def run_ablation(blocks_csv, cache_dir, out_dir, mode="cache", model_digest="845dbda0ea48", cal_tx_per_win=8,
                 stage="all", log=print):
    """Runs ablation_v2.py in a subprocess (it is self-contained) and returns its results JSON."""
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ, BLOCKS_CSV=os.path.abspath(blocks_csv), ABL_CACHE_DIR=os.path.abspath(cache_dir),
               ABL_OUT_DIR=os.path.abspath(out_dir), LLM_MODE=mode, MODEL_DIGEST=model_digest,
               CAL_TX_PER_WIN=str(cal_tx_per_win), STAGE=stage)
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(here, "ablation_v2.py")], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ablation_v2.py failed:\n" + r.stdout[-2000:] + "\n" + r.stderr[-3000:])
    for line in r.stdout.splitlines():
        if line.startswith(("[plan]", "[determinism]", "  [v")) and "calls" not in line:
            log("   " + line.strip())
    return json.load(open(os.path.join(out_dir, "ablation_v2_results.json")))
