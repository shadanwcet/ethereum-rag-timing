# -*- coding: utf-8 -*-
"""
PROMPT ABLATION v2  --  Does a 7B LLM use the kNN retrieval signal, and with which sign?
=========================================================================================
Self-contained: needs only blocks.csv (and Ollama + qwen2.5:7b unless MOCK_LLM=1).
Runs on the CAL split only. Does not touch TEST, so the pre-registered endpoint is unchanged.
Log it in DEVIATIONS.md as a post-registration diagnostic.

WHAT CHANGED VS THE FIRST ABLATION CELL (all findings from the review)
----------------------------------------------------------------------
 1. SIGN CONVENTION. ybest = min(fwd)/b - 1 is always <= 0 (fwd includes b[t] itself),
    and yhat = mean(ybest over neighbours) <= 0 as well. A value near 0 means "waiting
    saves little" -> SUBMIT.  Hence the paper's +0.23 on yhat is the CORRECT direction.
    We regress on  saving = -yhat >= 0  (expected sign of P(SUBMIT) on saving: NEGATIVE).
    A sanity gate asserts ybest <= 0.
 2. The v2 prompt prints the saving as a negative number ("-6.2%") under the label
    "saving". New variant v3 changes ONLY that (prints "6.2%"). Every later variant
    is built on v3, so single-factor changes are interpretable.
 3. No survival bias. The decision depends only on (t, t0, w), not on history, so we
    query ALL grid states of every swap (w = 0,5,...,50) and derive the sequential
    policy (first SUBMIT, forced at the deadline) afterwards.
 4. Regression: near-unpenalised (ridge 1e-2 on standardised features, negligible at n~1000 but stops blow-ups under separation), cluster bootstrap CIs at BOTH swap
    level and window level (the paper's unit of inference). Holm across variants.
    Sign is classified from the window-level CI (conservative).
 5. yhat is the neighbour MEAN (as in the paper) AND the median actually shown in
    the prompt is analysed as a second model.
 6. Controls: v0 (no retrieval shown) and v9 (placebo: retrieval from a different
    random state, same format as v3).
 7. Policy outcome at matched wait (heuristic, kNN, random-wait), same metric as the
    paper: fee reduction % = 100*(1 - mean cost / mean base cost), per window,
    window-cluster bootstrap.
 8. Engineering: thread-pool concurrency, atomic periodic cache save with a cache key
    covering model/digest/system/prompt/options, retries, INVALID outputs recorded
    (not fatal), a determinism re-query check, no pkill of a running Ollama.
 9. Effective-neighbour diagnostic: how many distinct episodes (gap > D blocks) the 10
    neighbours really cover.

RUN
---
Colab:  paste whole file into one cell (or !python prompt_ablation_v2.py).
Dry run without GPU:  MOCK_LLM=1 SELFTEST=1 CAL_TX_PER_WIN=3 python prompt_ablation_v2.py
Never run a cell that deletes files matching "cache" in CACHE_DIR (the old "Step 1").
"""
import os, sys, json, re, time, hashlib, shutil, subprocess, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv
from scipy.spatial import cKDTree
from scipy.special import expit

# =============================================================================
# 0. CONFIG
# =============================================================================
LLM_MODE = os.environ.get("LLM_MODE", "live")        # live | cache | mock
MOCK = os.environ.get("MOCK_LLM") == "1" or LLM_MODE == "mock"   # pipeline test only; results meaningless
CACHE_ONLY = LLM_MODE == "cache"                    # replay shipped answers; no Ollama needed
SELFTEST = os.environ.get("SELFTEST") == "1"      # synthesise blocks.csv if none found
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5:7b")
CONC = int(os.environ.get("CONC", 8))
CAL_TX_PER_WIN = int(os.environ.get("CAL_TX_PER_WIN", 8))   # swaps per CAL window
B_BOOT = int(os.environ.get("B_BOOT", 400))
W, D, TIP, K, STEP = 7_200, 50, 1.5, 10, 5
H1, H2 = 300, 50
ARRIVAL_SEED = 11
LLM_OPTS = {"temperature": 0.0, "seed": 42, "num_predict": 5}

CSV_CANDIDATES = ([os.environ["BLOCKS_CSV"]] if os.environ.get("BLOCKS_CSV") else []) + ["blocks.csv", "data/blocks.csv", "/content/blocks.csv"]
_drive = os.path.exists("/content/drive/MyDrive")
CACHE_DIR = os.environ.get("ABL_CACHE_DIR") or ("/content/drive/MyDrive/Experiments/rag_ethereum_cache" if _drive else "./cache")
OUT_DIR = os.environ.get("ABL_OUT_DIR") or ("/content/drive/MyDrive/Experiments/ablation_v2_out" if _drive else "./ablation_v2_out")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
CACHE_PATH = os.path.join(CACHE_DIR, "ablation_v2_llm_store.json")

OLLAMA = "http://127.0.0.1:11434"


# =============================================================================
# 1. OLLAMA (idempotent; never kills a running server)
# =============================================================================
def _http_json(url, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _ollama_alive():
    try:
        _http_json(OLLAMA + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def setup_ollama():
    if MOCK:
        return "mock"
    if CACHE_ONLY:
        return os.environ.get("MODEL_DIGEST", "845dbda0ea48")
    if shutil.which("ollama") is None:
        os.system("apt-get update -qq && apt-get install -y -qq zstd pciutils lshw > /dev/null")
        os.system("curl -fsSL https://ollama.com/install.sh | sh")
    os.environ.update(OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NUM_PARALLEL=str(CONC),
                      OLLAMA_FLASH_ATTENTION="1", OLLAMA_KEEP_ALIVE="-1", OLLAMA_MAX_LOADED_MODELS="1")
    if not _ollama_alive():
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if _ollama_alive():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Ollama did not start")
    tags = _http_json(OLLAMA + "/api/tags").get("models", [])
    if not any(m["name"].startswith(MODEL_NAME) for m in tags):
        os.system(f"ollama pull {MODEL_NAME}")
        tags = _http_json(OLLAMA + "/api/tags").get("models", [])
    digest = next((m["digest"][:12] for m in tags if m["name"].startswith(MODEL_NAME)), "local")
    for _ in range(2):  # warm-up
        try:
            _http_json(OLLAMA + "/api/generate",
                       {"model": MODEL_NAME, "prompt": "hi", "stream": False, "options": {"num_predict": 1}}, 300)
        except Exception:
            pass
    return digest


MODEL_DIGEST = setup_ollama()
print(f"[ollama] model={MODEL_NAME} digest={MODEL_DIGEST} mock={MOCK}")
if MOCK:
    print("!! MOCK MODE: LLM answers are synthetic. Pipeline test only. Do NOT interpret results. !!")


# =============================================================================
# 2. DATA, FEATURES, RETRIEVER (same definitions as the main pipeline)
# =============================================================================
def make_synthetic_csv(path, nw=24, seed=0):
    r = np.random.default_rng(seed)
    n = nw * W
    x = np.empty(n)
    x[0] = np.log(20.0)
    eps = r.normal(0, 0.06, n)
    for i in range(1, n):
        x[i] = x[i - 1] + 0.02 * (np.log(20.0) - x[i - 1]) + eps[i]
    pd.DataFrame({"number": np.arange(n), "base_fee_per_gas": np.exp(x) * 1e9}).to_csv(path, index=False)


CSV = next((p for p in CSV_CANDIDATES if os.path.exists(p)), None)
if CSV is None and SELFTEST:
    CSV = "./synthetic_blocks.csv"
    make_synthetic_csv(CSV)
    print("[selftest] synthetic blocks.csv generated")
if CSV is None:
    raise FileNotFoundError("blocks.csv not found")

df = pd.read_csv(CSV).sort_values("number")
assert (df["number"].diff().dropna() == 1).mean() > 0.999, "Contiguity failure"
b = np.ascontiguousarray(df["base_fee_per_gas"].to_numpy(np.float64) / 1e9)
nw = len(b) // W
b = b[: nw * W]
N = len(b)
lb = np.log(b)
cs = np.concatenate([[0.0], np.cumsum(b)])


def trail_mean(L):
    t = np.arange(N)
    lo = np.maximum(t - L, 0)
    return (cs[t] - cs[lo]) / np.maximum(t - lo, 1)       # mean of b[lo..t-1]: excludes b[t]


m1, m2 = trail_mean(H1), trail_mean(H2)
rank = np.zeros(N)
b_swv = swv(b, H1)                                         # window i = b[i:i+H1]
for s in range(H1, N, 20_000):
    e = min(s + 20_000, N)
    rank[s:e] = (b_swv[s - H1: e - H1] < b[s:e, None]).mean(axis=1)   # past H1 blocks only

# np.roll wraps only for t < 5; every state used here has t >= H1 inside its window.
F = np.column_stack([np.log(b / np.maximum(m1, 1e-9)), np.log(b / np.maximum(m2, 1e-9)),
                     lb - np.roll(lb, 5), lb - np.roll(lb, 1), rank])

fwd = swv(b, D + 1)                                        # fwd[i] = b[i:i+D+1], INCLUDES b[i]
ybest = np.full(N, np.nan)
abest = np.zeros(N, dtype=np.int32)
ybest[: len(fwd)] = fwd.min(axis=1) / b[: len(fwd)] - 1.0
abest[: len(fwd)] = fwd.argmin(axis=1)
assert np.nanmax(ybest) <= 1e-12, "ybest must be <= 0 by construction"
print(f"[sign gate] max ybest = {np.nanmax(ybest):.3g} (<= 0 as required). "
      f"Expected coefficient sign on SAVING = -yhat is NEGATIVE; on yhat it is POSITIVE.")

wl = np.arange(nw)
nl, nc = int(nw * 0.35), int(nw * 0.30)
LIB, CAL, TEST = wl[:nl], wl[nl: nl + nc], wl[nl + nc:]
assert len(LIB) and len(CAL) and len(TEST), "not enough windows"


def valid(ws, tail=D + 1):
    return np.concatenate([np.arange(w * W + H1, (w + 1) * W - tail) for w in ws])


li = valid(LIB, D + 1)
assert li.min() >= 5 and li.max() + D + 1 <= CAL[0] * W, "LIB must lie strictly before CAL (no leakage)"
mu, sd = F[li].mean(axis=0), F[li].std(axis=0) + 1e-9
Z = np.ascontiguousarray((F - mu) / sd)
tree = cKDTree(Z[li])
glob_best = float(np.nanmean(ybest[li]))                   # <= 0

q_cal = valid(CAL, 1)
_, ix = tree.query(Z[q_cal], K, workers=-1)
NB = np.full((N, K), -1, dtype=np.int64)
NB[q_cal] = li[ix]
YHAT = np.full(N, np.nan)
YHAT[q_cal] = ybest[NB[q_cal]].mean(axis=1)                # paper's yhat (mean), <= 0

# -----------------------------------------------------------------------------
# CAL arrivals (distinct per window) and the full state grid
# -----------------------------------------------------------------------------
rng = np.random.default_rng(ARRIVAL_SEED)
t0s = np.concatenate([rng.choice(np.arange(w * W + H1, (w + 1) * W - D - 2), CAL_TX_PER_WIN, replace=False)
                      for w in CAL])
S = len(t0s)
G = np.arange(0, D + 1, STEP)
nG = len(G)
T0 = np.repeat(t0s, nG)
WV = np.tile(G, S)
T = T0 + WV
SW = np.repeat(np.arange(S), nG)                           # swap id
WIN = T0 // W                                              # window id
assert np.isin(WIN, CAL).all() and (NB[T] >= 0).all()
NBe = NB[T]                                                # (M, K)
M = len(T)
sav_true = -ybest[NBe].mean(axis=1)                        # = -yhat[t] >= 0
assert np.allclose(sav_true, -YHAT[T])
eps_n = 1 + (np.diff(np.sort(NBe, axis=1), axis=1) > D).sum(axis=1)
print(f"[cal] swaps={S} windows={len(CAL)} states/swap={nG} total states={M} "
      f"| distinct episodes among the {K} neighbours: mean={eps_n.mean():.2f} "
      f"(<{K} means the '10 similar situations' are not independent)")
perm = np.roll(np.arange(M), M // 3)                       # placebo: retrieval from another state


# =============================================================================
# 3. PROMPT VARIANTS
# =============================================================================
SYS_DL = ("You time an Ethereum swap. You pay the base fee of the block you submit in. "
          "Waiting is free except latency; there is a hard deadline after which the swap is submitted anyway. "
          "Reply with exactly one word: SUBMIT or WAIT.")
SYS_NODL = ("You time an Ethereum swap. You pay the base fee of the block you submit in. "
            "Waiting is free except latency. Reply with exactly one word: SUBMIT or WAIT.")


def head(t, w):
    return (f"Now (waited {w} of {D} blocks, 12s each): base fee {b[t]:.2f} gwei.\n"
            f"Context: now vs 1h mean {b[t]/m1[t]-1:+.1%}; vs 10min mean {b[t]/m2[t]-1:+.1%}; "
            f"fraction of the last hour cheaper than now {rank[t]:.0%}.\n")


TAIL = ("Only the fee in the block you submit in counts. Submitting now is correct when the current fee "
        "is low relative to recent history. Decision (reply ONLY with SUBMIT or WAIT):")
RULES = ("SUBMIT rule: submit when the current fee is low relative to recent history (fraction cheaper below ~30%).\n"
         "WAIT rule: wait when the median saving from waiting is large (above ~2%) AND the current fee "
         "is not already low relative to recent history.\n")


def stats_of(nb):
    n0 = int((abest[nb] == 0).sum())
    med = float(np.median(ybest[nb]))
    mb = int(np.median(abest[nb]))
    return n0, med, mb, max(0.0, -med), max(0.0, -glob_best)


def p_v0(t, w, nb):
    return head(t, w) + TAIL


def p_v2(t, w, nb):          # EXACT paper prompt (saving printed as a negative number)
    n0, med, mb, _, _ = stats_of(nb)
    return head(t, w) + (f"Among 10 similar past situations, submitting immediately was already cheapest in {n0}/10; "
                         f"median best saving from waiting was {med:+.1%} (after ~{mb} blocks); "
                         f"typical across all situations {glob_best:+.1%}.\n") + TAIL


def p_v3(t, w, nb):          # ONLY change vs v2: saving printed as a positive number
    n0, med, mb, sv, gs = stats_of(nb)
    return head(t, w) + (f"Among 10 similar past situations, submitting immediately was already cheapest in {n0}/10; "
                         f"median best saving from waiting was {sv:.1%} (after ~{mb} blocks); "
                         f"typical across all situations {gs:.1%}.\n") + TAIL


def p_v4(t, w, nb):          # v3 + explicit decision rules (tests instruction-following, not signal use)
    n0, med, mb, sv, gs = stats_of(nb)
    return head(t, w) + (f"Among 10 similar past situations, submitting immediately was already cheapest in {n0}/10; "
                         f"median best saving from waiting was {sv:.1%} (after ~{mb} blocks); "
                         f"typical across all situations {gs:.1%}.\n") + RULES + TAIL


def p_v5(t, w, nb):          # v3 + choice-conditional (counterfactual) framing, keeps TAIL
    n0, med, mb, sv, gs = stats_of(nb)
    return head(t, w) + (f"If you SUBMIT now you pay {b[t]:.2f} gwei; in 10 similar past situations submitting "
                         f"immediately was already cheapest in {n0}/10. If you WAIT, the median best saving versus "
                         f"submitting now was {sv:.1%} (reached after ~{mb} blocks); typical across all situations "
                         f"{gs:.1%}.\n") + TAIL


def p_v6(t, w, nb):          # v3 + clause order swapped
    n0, med, mb, sv, gs = stats_of(nb)
    return head(t, w) + (f"Median best saving from waiting was {sv:.1%} (after ~{mb} blocks); typical across all "
                         f"situations {gs:.1%}. Among 10 similar past situations, submitting immediately was already "
                         f"cheapest in {n0}/10.\n") + TAIL


def p_v8(t, w, nb):          # everything at once: positive + counterfactual + rules + no deadline
    n0, med, mb, sv, gs = stats_of(nb)
    return head(t, w) + (f"If you SUBMIT now you pay {b[t]:.2f} gwei; in 10 similar past situations submitting "
                         f"immediately was already cheapest in {n0}/10. If you WAIT, the median best saving versus "
                         f"submitting now was {sv:.1%} (reached after ~{mb} blocks); typical across all situations "
                         f"{gs:.1%}.\n") + RULES + TAIL


VARIANTS = {
    # name:                (prompt fn, system, placebo, shows_stats)
    "v0_no_retrieval":     (p_v0, SYS_DL,   False, False),
    "v2_paper_baseline":   (p_v2, SYS_DL,   False, True),
    "v3_positive_saving":  (p_v3, SYS_DL,   False, True),
    "v4_rules":            (p_v4, SYS_DL,   False, True),
    "v5_counterfactual":   (p_v5, SYS_DL,   False, True),
    "v6_reorder":          (p_v6, SYS_DL,   False, True),
    "v7_no_deadline":      (p_v3, SYS_NODL, False, True),
    "v8_all_fixes":        (p_v8, SYS_NODL, False, True),
    "v9_placebo":          (p_v3, SYS_DL,   True,  True),
}


# ---- staged runs (cache makes every stage resumable and additive)
#   STAGE=1 : core diagnosis      v0, v2, v3, v9      (~4 x M calls)
#   STAGE=2 : mechanism ablations v4, v5, v6, v7, v8  (~5 x M calls)
#   STAGE=all (default) or ONLY="v2_paper_baseline,v3_positive_saving"
_STAGES = {"1": ["v0_no_retrieval", "v2_paper_baseline", "v3_positive_saving", "v9_placebo"],
           "2": ["v4_rules", "v5_counterfactual", "v6_reorder", "v7_no_deadline", "v8_all_fixes"]}
_only = os.environ.get("ONLY")
_stage = os.environ.get("STAGE", "all")
_keep = [x.strip() for x in _only.split(",")] if _only else _STAGES.get(_stage, list(VARIANTS))
VARIANTS = {k: v for k, v in VARIANTS.items() if k in _keep}
assert VARIANTS, "no variants selected"
REF = next(iter(VARIANTS))                      # reference variant for determinism / VIF
print(f"[plan] variants={list(VARIANTS)} | states/variant={M} | total calls={M*len(VARIANTS)} "
      f"| est. sequential time @0.5-1.0 s/call = {M*len(VARIANTS)*0.5/3600:.1f}-{M*len(VARIANTS)*1.0/3600:.1f} h "
      f"(cache hits and parallel slots reduce this; progress/ETA printed below)")


# =============================================================================
# 4. LLM CALLS (thread pool, cache, retries)
# =============================================================================
_lock = threading.Lock()
STORE = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}
_new_since_save = 0


def _key(sys_i, prompt):
    return hashlib.sha256(json.dumps([MODEL_NAME, MODEL_DIGEST, sys_i, prompt, LLM_OPTS],
                                     sort_keys=True).encode()).hexdigest()


def save_store():
    with _lock:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(STORE, f)
        os.replace(tmp, CACHE_PATH)


def _parse(raw):
    m = re.search(r"SUBMIT|WAIT", raw.upper())
    return m.group(0) if m else "INVALID"


def _mock(prompt):
    m = re.search(r"cheaper than now (\d+)%", prompt)
    r = int(m.group(1)) / 100 if m else 0.5
    h = int(hashlib.md5(prompt.encode()).hexdigest()[:4], 16) / 65535
    return "SUBMIT" if (r <= 0.3 or h < 0.1) else "WAIT"


def _raw_call(sys_i, prompt):
    if MOCK:
        return _mock(prompt)
    if CACHE_ONLY:
        raise RuntimeError("Prompt not in the shipped cache (LLM_MODE=cache). Copy ablation_v2_llm_store.json into cache/ "
                           "or rerun with LLM_MODE=live.")
    last = None
    for attempt in range(4):
        try:
            out = _http_json(OLLAMA + "/api/generate",
                             {"model": MODEL_NAME, "system": sys_i, "prompt": prompt, "stream": False,
                              "options": LLM_OPTS}, 120)
            return _parse(out.get("response", ""))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after retries: {last}")


def call_llm(sys_i, prompt, use_cache=True):
    global _new_since_save
    k = _key(sys_i, prompt)
    if use_cache and k in STORE:
        return STORE[k]
    ans = _raw_call(sys_i, prompt)
    if use_cache:
        with _lock:
            STORE[k] = ans
            _new_since_save += 1
            need = _new_since_save >= 300
            if need:
                _new_since_save = 0
        if need:
            save_store()
    return ans


def run_variant(name):
    fn, sys_i, placebo, shows = VARIANTS[name]
    prompts = [fn(int(T[i]), int(WV[i]), NBe[perm[i]] if placebo else NBe[i]) for i in range(M)]
    todo = sum(1 for p in prompts if _key(sys_i, p) not in STORE)
    print(f"  [{name}] {M} states, {todo} uncached calls")
    t_start = time.perf_counter()
    done = [0]
    step = max(1, todo // 10)

    def work(p):
        cached = _key(sys_i, p) in STORE
        a = call_llm(sys_i, p)
        if not cached:
            with _lock:
                done[0] += 1
                d = done[0]
            if d % step == 0 and d < todo:
                el = time.perf_counter() - t_start
                print(f"    {d}/{todo} calls | {el/60:.1f} min elapsed | {d/el:.2f} calls/s "
                      f"| ETA {(todo-d)/(d/el)/60:.1f} min", flush=True)
        return a

    with ThreadPoolExecutor(max_workers=CONC) as ex:
        ans = list(ex.map(work, prompts))
    save_store()
    print(f"  [{name}] done in {(time.perf_counter()-t_start)/60:.1f} min | "
          f"invalid={np.mean([a=='INVALID' for a in ans]):.1%}")
    return np.array(ans), prompts


# =============================================================================
# 5. STATISTICS
# =============================================================================
def logit_fit(X, y, lam=1e-2, iters=60):
    n, p = X.shape
    A = np.column_stack([np.ones(n), X])
    beta = np.zeros(p + 1)
    pen = np.r_[0.0, np.ones(p)] * lam
    for _ in range(iters):
        mu_ = expit(A @ beta)
        g = A.T @ (y - mu_) - pen * beta
        H = (A * (mu_ * (1 - mu_))[:, None]).T @ A + np.diag(pen) + 1e-9 * np.eye(p + 1)
        step = np.linalg.solve(H, g)
        nrm = np.max(np.abs(step))
        if nrm > 5:
            step *= 5 / nrm
        beta += step
        if nrm < 1e-8:
            break
    return beta


def cluster_boot(X, y, cl, B, seed):
    rg = np.random.default_rng(seed)
    ucl, inv = np.unique(cl, return_inverse=True)
    idx = [np.where(inv == k)[0] for k in range(len(ucl))]
    out = np.full((B, X.shape[1] + 1), np.nan)
    for i in range(B):
        pick = rg.integers(0, len(ucl), len(ucl))
        rows = np.concatenate([idx[k] for k in pick])
        yb = y[rows]
        if yb.min() == yb.max():
            continue
        out[i] = logit_fit(X[rows], yb)
    return out


def summarise(draws, j):
    d = draws[:, j + 1]
    d = d[~np.isnan(d)]
    if len(d) < 50:
        return dict(lo=np.nan, hi=np.nan, p=np.nan, n=len(d))
    lo, hi = np.percentile(d, [2.5, 97.5])
    p = max(2 * min((d <= 0).mean(), (d >= 0).mean()), 1.0 / (len(d) + 1))
    return dict(lo=float(lo), hi=float(hi), p=float(p), n=len(d))


def vif(X):
    out = []
    for j in range(X.shape[1]):
        others = np.column_stack([np.ones(len(X)), np.delete(X, j, axis=1)])
        coef, *_ = np.linalg.lstsq(others, X[:, j], rcond=None)
        r2 = 1 - ((X[:, j] - others @ coef) ** 2).sum() / max(((X[:, j] - X[:, j].mean()) ** 2).sum(), 1e-12)
        out.append(1 / max(1 - r2, 1e-9))
    return out


def fit_block(rows, feats, y, tag):
    """Return dict feat -> {coef, swap CI/p, window CI/p}. Standardised features, fixed scaling."""
    X = np.column_stack([rows[f] for f in feats]).astype(float)
    X = (X - X.mean(0)) / np.where(X.std(0) < 1e-12, 1.0, X.std(0))
    if y.min() == y.max():
        return None
    beta = logit_fit(X, y)
    d_sw = cluster_boot(X, y, rows["swap"], B_BOOT, 1)
    d_wn = cluster_boot(X, y, rows["win"], B_BOOT, 2)
    res = {}
    for j, f in enumerate(feats):
        res[f] = dict(coef=float(beta[j + 1]), swap=summarise(d_sw, j), win=summarise(d_wn, j))
    res["_sep"] = bool(np.max(np.abs(beta)) > 15)
    res["_vif"] = dict(zip(feats, [float(v) for v in vif(X)]))
    return res


def holm(pvals):
    p = np.array(pvals, float)
    order = np.argsort(np.where(np.isnan(p), 2, p))
    adj = np.full(len(p), np.nan)
    run, m = 0.0, int(np.sum(~np.isnan(p)))
    for rank_i, i in enumerate(order[:m]):
        run = max(run, (m - rank_i) * p[i])
        adj[i] = min(run, 1.0)
    return adj


def classify(r):
    lo, hi = r["win"]["lo"], r["win"]["hi"]
    if np.isnan(lo):
        return "n/a"
    if hi < 0:
        return "CORRECT (neg, CI excl 0)"
    if lo > 0:
        return "INVERTED (pos, CI excl 0)"
    return "undetected (CI incl 0)"


# =============================================================================
# 6. RUN ALL VARIANTS
# =============================================================================
print("\n" + "=" * 100)
print(f"PROMPT ABLATION v2 on CAL | {S} swaps x {nG} states | {len(VARIANTS)} variants | model {MODEL_NAME}")
print("=" * 100)

ANS, PROMPTS = {}, {}
for name in VARIANTS:
    ANS[name], PROMPTS[name] = run_variant(name)

# ---- determinism re-query (bypass cache) on the paper baseline
rg_d = np.random.default_rng(3)
chk = rg_d.choice(M, size=min(100, M), replace=False)
fn_, sys_, _, _ = VARIANTS[REF]
if CACHE_ONLY:
    determinism = float("nan")                      # cannot re-query without a live model
else:
    re_ans = [call_llm(sys_, PROMPTS[REF][i], use_cache=False) for i in chk]
    determinism = float(np.mean([re_ans[k] == ANS[REF][i] for k, i in enumerate(chk)]))
print(f"[determinism] re-query agreement on {len(chk)} {REF} prompts: {determinism:.1%}")

# ---- per-variant state tables + regressions
base_rows = dict(rank=rank[T], vs_arrival=b[T] / b[T0] - 1.0, w=WV.astype(float),
                 sav_true=sav_true, swap=SW, win=WIN)
results = {}
for name, (fn, sys_i, placebo, shows) in VARIANTS.items():
    ans = ANS[name]
    ok = (ans != "INVALID") & (WV < D)               # at w=D the swap is submitted anyway
    y = (ans[ok] == "SUBMIT").astype(float)
    rows = {k: v[ok] for k, v in base_rows.items()}
    if shows:
        shown_nb = NBe[perm] if placebo else NBe
        rows["sav_shown"] = -np.median(ybest[shown_nb], axis=1)[ok]
    r = dict(n_rows=int(ok.sum()), n_swaps=int(len(np.unique(rows["swap"]))),
             invalid=float(np.mean(ans == "INVALID")), submit_rate=float(y.mean()),
             submit_w0=float((ans[WV == 0] == "SUBMIT").mean()),
             marginal=None, modelA=None, modelB=None)
    r["marginal"] = fit_block(rows, ["sav_true"], y, name)
    r["modelA"] = fit_block(rows, ["rank", "sav_true", "vs_arrival", "w"], y, name)       # paper-comparable
    if shows:
        r["modelB"] = fit_block(rows, ["rank", "sav_shown", "vs_arrival", "w"], y, name)  # what the model saw
    q4 = pd.qcut(rows["sav_true"], 4, duplicates="drop", labels=False)
    r["p_submit_by_sav_quartile"] = [float(y[q4 == k].mean()) for k in np.unique(q4)]
    results[name] = r

# ---- Holm across variants on window-level p of sav_true (Model A)
names = list(VARIANTS)
# Degenerate = near-constant answers or separation: coefficients are artefacts, not signal use
for n in names:
    r_ = results[n]
    r_["degenerate"] = bool(r_["modelA"] is None or r_["modelA"]["_sep"]
                            or r_["submit_rate"] < 0.02 or r_["submit_rate"] > 0.98)
# Holm family = variants that show retrieval, are not the placebo, and are not degenerate
fam = [n for n in names if VARIANTS[n][3] and not VARIANTS[n][2] and not results[n]["degenerate"]]
def _p(n, lvl):
    a = results[n]["modelA"]
    return a["sav_true"][lvl]["p"] if a else np.nan
hw, hs = holm([_p(n, "win") for n in fam]), holm([_p(n, "swap") for n in fam])
for n in names:
    results[n]["holm_win"] = results[n]["holm_swap"] = float("nan")
for i, n in enumerate(fam):
    results[n]["holm_win"], results[n]["holm_swap"] = float(hw[i]), float(hs[i])

# =============================================================================
# 7. POLICY OUTCOME AT MATCHED WAIT (paper metric: fee reduction %, per-window, window bootstrap)
# =============================================================================
cost = lambda t: b[t] + TIP
t0_arr = t0s
win_of_swap = t0_arr // W
rank_mat = rank[T].reshape(S, nG)
yhat_mat = YHAT[T].reshape(S, nG)
cost_mat = cost(T).reshape(S, nG)


def wait_idx_from(cond):
    c = cond.copy()
    c[:, -1] = True
    return c.argmax(axis=1)


def calibrate(target_idx, mat, hi, is_rank):
    lo = 0.0
    for _ in range(50):
        mid = (lo + hi) / 2
        cond = (mat <= mid) if is_rank else (mat > -mid)
        if wait_idx_from(cond).mean() > target_idx:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def reduction_by_window(idx_arr):
    """100*(1 - mean cost / mean base cost) per window, as in the paper."""
    pol = cost_mat[np.arange(S), idx_arr]
    base = cost_mat[:, 0]
    return np.array([100.0 * (1 - pol[win_of_swap == w].mean() / base[win_of_swap == w].mean()) for w in CAL])


def boot_mean(x, B=4000, seed=5):
    rg = np.random.default_rng(seed)
    bm = x[rg.integers(0, len(x), (B, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))


policy = {}
for name in VARIANTS:
    ans = ANS[name].reshape(S, nG)
    cond = (ans == "SUBMIT")
    idx_llm = wait_idx_from(cond)                    # INVALID treated as WAIT; forced submit at deadline
    tgt = idx_llm.mean()
    q = calibrate(tgt, rank_mat, 1.0, True)
    tau = calibrate(tgt, yhat_mat, max(0.3, float(-np.nanmin(yhat_mat)) + 1e-6), False)
    idx_h = wait_idx_from(rank_mat <= q)
    idx_k = wait_idx_from(yhat_mat > -tau)
    m_rand = int(np.clip(round(2 * tgt), 0, nG - 1))  # uniform wait on {0..m}: use its expected cost
    pol_rand = cost_mat[:, : m_rand + 1].mean(axis=1)
    red_rand = np.array([100.0 * (1 - pol_rand[win_of_swap == w].mean() / cost_mat[win_of_swap == w, 0].mean())
                         for w in CAL])
    r_llm, r_h, r_k = reduction_by_window(idx_llm), reduction_by_window(idx_h), reduction_by_window(idx_k)
    policy[name] = dict(
        wait_llm=float(idx_llm.mean() * STEP), wait_heur=float(idx_h.mean() * STEP), wait_knn=float(idx_k.mean() * STEP),
        llm=boot_mean(r_llm), heur=boot_mean(r_h), knn=boot_mean(r_k), rand=boot_mean(red_rand),
        llm_minus_heur=boot_mean(r_llm - r_h), llm_minus_knn=boot_mean(r_llm - r_k),
        llm_minus_rand=boot_mean(r_llm - red_rand))

# =============================================================================
# 8. REPORT
# =============================================================================
L = []
add = L.append
add("# Prompt ablation v2 (CAL only)\n")
add(f"Model `{MODEL_NAME}` digest `{MODEL_DIGEST}` | mock={MOCK} | swaps={S} | windows={len(CAL)} | "
    f"states/swap={nG} | decision options {LLM_OPTS}")
add(f"Determinism re-query agreement: {determinism:.1%} | distinct neighbour episodes (of {K}): {eps_n.mean():.2f}")
add("Sign convention: saving = -yhat >= 0. Correct behaviour => NEGATIVE coefficient on saving "
    "(paper's +0.23 on yhat == -0.23 on saving == correct direction).\n")

hdr = (f"{'variant':<20}|{'rows':>6}|{'SUBMIT':>7}|{'@w=0':>6}|{'inval':>6}| "
       f"{'coef(sav)':>9} {'swap 95% CI':>17} {'win 95% CI':>17} {'Holm(win)':>9} | verdict")
add("## A. Paper-comparable model: P(SUBMIT) ~ rank + saving(true mean) + vs_arrival + w   [standardised]\n")
add("```\n" + hdr)
for n in names:
    r = results[n]
    a = r["modelA"]
    if a is None:
        add(f"{n:<20}|{r['n_rows']:>6}|{r['submit_rate']:>7.2f}|{r['submit_w0']:>6.2f}|{r['invalid']:>6.2f}| DEGENERATE (constant outcome)")
        continue
    s = a["sav_true"]
    add(f"{n:<20}|{r['n_rows']:>6}|{r['submit_rate']:>7.2f}|{r['submit_w0']:>6.2f}|{r['invalid']:>6.2f}| "
        f"{s['coef']:>+9.2f} [{s['swap']['lo']:+6.2f},{s['swap']['hi']:+6.2f}] [{s['win']['lo']:+6.2f},{s['win']['hi']:+6.2f}] "
        f"{r['holm_win']:>9.3f} | "
        + ("DEGENERATE (near-constant answers; coef not interpretable)" if r["degenerate"] else classify(s)))
add("```\n")

add("## B. Marginal association (saving alone) and shown-statistic model\n")
add("```\n" + f"{'variant':<20}| {'marg coef':>9} {'win 95% CI':>17} | {'coef(shown med)':>15} {'win 95% CI':>17} | "
    f"P(SUBMIT) by saving quartile (low->high)")
for n in names:
    r = results[n]
    mg = r["marginal"]["sav_true"] if r["marginal"] else None
    mb_ = r["modelB"]["sav_shown"] if r["modelB"] else None
    ms = (f"{mg['coef']:>+9.2f} [{mg['win']['lo']:+6.2f},{mg['win']['hi']:+6.2f}]" if mg else f"{'n/a':>28}")
    mbs = (f"{mb_['coef']:>+15.2f} [{mb_['win']['lo']:+6.2f},{mb_['win']['hi']:+6.2f}]" if mb_ else f"{'n/a':>33}")
    add(f"{n:<20}| {ms} | {mbs} | " + " ".join(f"{v:.2f}" for v in r["p_submit_by_sav_quartile"]))
add("```\n")
vv = next((results[n]["modelA"] for n in names if results[n]["modelA"]), None)
if vv:
    add("Collinearity (VIF, first variant Model A): " + ", ".join(f"{k}={v:.2f}" for k, v in vv["_vif"].items()))
add(f"corr(rank, saving) over all states = {np.corrcoef(rank[T], sav_true)[0,1]:+.2f}\n")

add("## C. Policy outcome at matched wait (fee reduction %, mean over windows, window-bootstrap 95% CI)\n")
add("```\n" + f"{'variant':<20}|{'wait LLM/H/kNN':>16}| {'LLM':>20} | {'LLM-heur (pp)':>22} | {'LLM-kNN (pp)':>22} | {'LLM-rand (pp)':>22}")
for n in names:
    p = policy[n]
    f_ = lambda t: f"{t[0]:+.2f} [{t[1]:+.2f},{t[2]:+.2f}]"
    add(f"{n:<20}|{p['wait_llm']:>5.1f}/{p['wait_heur']:>4.1f}/{p['wait_knn']:>4.1f}| {f_(p['llm']):>20} | "
        f"{f_(p['llm_minus_heur']):>22} | {f_(p['llm_minus_knn']):>22} | {f_(p['llm_minus_rand']):>22}")
add("```\nWait columns are in blocks; heuristic/kNN thresholds are fitted to match the LLM's mean wait on the same "
    "arrivals (one parameter, wait only, no price outcome used). Check the matched waits agree within ~1 block.\n")

add("## D. How to read this\n")
add("- v2 vs v3 isolates the sign/format of the printed saving; v4-v7 are single changes on top of v3; v8 stacks them.")
add("- v0 (no retrieval) should show ~0 coefficient on saving; v9 (placebo) must show ~0 on TRUE saving "
    "(see Model B for the shown placebo value). If v3-v8 are also ~0, the model ignores the signal.")
add("- v4/v8 give the decision rule in words: a correct sign there shows instruction-following, not signal discovery.")
add("- A coefficient is called CORRECT/INVERTED only if the WINDOW-level CI excludes 0. With few windows this is "
    "conservative; swap-level CIs are shown for power.")
add("- Not tested here: other model sizes, quantisations other than the Ollama default, other horizons, TEST data.")

report = "\n".join(L)
print("\n" + report)
with open(os.path.join(OUT_DIR, "ablation_v2_report.md"), "w") as f:
    f.write(report)
with open(os.path.join(OUT_DIR, "ablation_v2_results.json"), "w") as f:
    json.dump(dict(config=dict(model=MODEL_NAME, digest=MODEL_DIGEST, mock=MOCK, swaps=int(S), windows=len(CAL),
                               B_BOOT=B_BOOT, opts=LLM_OPTS, determinism=determinism, episodes=float(eps_n.mean())),
                   regression=results, policy=policy), f, indent=2, default=float)
for name in VARIANTS:
    pd.DataFrame(dict(t0=T0, w=WV, t=T, swap=SW, window=WIN, rank=rank[T], saving_true=sav_true,
                      vs_arrival=b[T] / b[T0] - 1, decision=ANS[name])).to_csv(
        os.path.join(OUT_DIR, f"states_{name}.csv"), index=False)
save_store()
print(f"\nSaved report, JSON and per-variant state tables to {OUT_DIR}")
