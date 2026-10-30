"""Data loading, state features, labels, splits and the static kNN library."""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv
from scipy.spatial import cKDTree

BQ_QUERY = """
SELECT number, UNIX_SECONDS(timestamp) AS timestamp, base_fee_per_gas
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp BETWEEN '2024-01-01' AND '2024-02-15'
ORDER BY number
"""


def load_blocks(csv_path):
    """Load blocks.csv; return base fee in gwei (float64) and a validation report."""
    df = pd.read_csv(csv_path).sort_values("number")
    gaps = df["number"].diff().dropna()
    contiguity = float((gaps == 1).mean())
    assert contiguity > 0.999, f"Contiguity failure: {contiguity:.4%}"
    assert df["number"].is_monotonic_increasing, "Block numbers not monotonic"
    b = np.ascontiguousarray(df["base_fee_per_gas"].to_numpy(np.float64) / 1e9)
    info = dict(rows=int(len(df)), contiguity=contiguity, first_block=int(df["number"].iloc[0]),
                last_block=int(df["number"].iloc[-1]))
    if "timestamp" in df.columns:
        info.update(first_ts=int(df["timestamp"].iloc[0]), last_ts=int(df["timestamp"].iloc[-1]))
    return b, info


def synthetic_base_fee(n_blocks=316_800, seed=0):
    """Synthetic mean-reverting base fee for software self-tests ONLY (not real data)."""
    from scipy.signal import lfilter
    r = np.random.default_rng(seed)
    eps = r.normal(0, 0.06, n_blocks)
    x = lfilter([1.0], [1.0, -0.98], eps) + np.log(20.0)
    return np.exp(x)


def causal_lag(arr, shift):
    out = np.empty_like(arr)
    out[:shift] = arr[0]
    out[shift:] = arr[:-shift]
    return out


class Market:
    """All arrays for one window length. feature_mode 'roll' = np.roll (primary/sensitivity runs),
    'causal' = padded lag (retrieval-signal diagnostic). Both only differ in the first 5 blocks."""

    def __init__(self, base_fee_gwei, W, feature_mode="roll", D=50, TIP=1.5, K=10, H1=300, H2=50,
                 STEP=5, lib_frac=0.35, cal_frac=0.30):
        self.W, self.D, self.TIP, self.K, self.H1, self.H2, self.STEP = W, D, TIP, K, H1, H2, STEP
        nw = len(base_fee_gwei) // W
        b = np.ascontiguousarray(np.asarray(base_fee_gwei, np.float64)[: nw * W])
        self.b, self.nw, self.N = b, nw, len(b)
        self.lb = np.log(b)
        cs = np.concatenate([[0.0], np.cumsum(b)])
        t = np.arange(self.N)

        def trail_mean(L):
            lo = np.maximum(t - L, 0)
            return (cs[t] - cs[lo]) / np.maximum(t - lo, 1)

        self.m1, self.m2 = trail_mean(H1), trail_mean(H2)
        rank = np.zeros(self.N)
        bw = swv(b, H1)
        for s in range(H1, self.N, 20_000):
            e = min(s + 20_000, self.N)
            rank[s:e] = (bw[s - H1: e - H1] < b[s:e, None]).mean(axis=1)
        self.rank = rank
        lag = (lambda a, k: np.roll(a, k)) if feature_mode == "roll" else causal_lag
        lb = self.lb
        self.F = np.column_stack([np.log(b / np.maximum(self.m1, 1e-9)), np.log(b / np.maximum(self.m2, 1e-9)),
                                  lb - lag(lb, 5), lb - lag(lb, 1), rank])
        fwd = swv(b, D + 1)
        self.fwd = fwd
        self.ybest = np.full(self.N, np.nan)
        self.abest = np.zeros(self.N, dtype=np.int32)
        self.ybest[: len(fwd)] = fwd.min(axis=1) / b[: len(fwd)] - 1.0
        self.abest[: len(fwd)] = fwd.argmin(axis=1)
        assert np.nanmax(self.ybest) <= 1e-12, "ybest must be <= 0 by construction"
        wl = np.arange(nw)
        nl, nc = int(nw * lib_frac), int(nw * cal_frac)
        self.LIB, self.CAL, self.TEST = wl[:nl], wl[nl: nl + nc], wl[nl + nc:]
        self.li = self.valid(self.LIB, D + 1)
        self.mu = self.F[self.li].mean(axis=0)
        self.sd = self.F[self.li].std(axis=0) + 1e-9
        self.Z = np.ascontiguousarray((self.F - self.mu) / self.sd)
        self.tree = cKDTree(self.Z[self.li])
        self.glob_best = float(np.nanmean(self.ybest[self.li]))
        assert self.li.max() + D + 1 <= self.CAL[0] * W, "library must precede calibration windows"

    def valid(self, ws, tail=None):
        tail = self.D + 1 if tail is None else tail
        return np.concatenate([np.arange(w * self.W + self.H1, (w + 1) * self.W - tail) for w in ws])

    def arrivals(self, ws, per, seed):
        r = np.random.default_rng(seed)
        return np.concatenate([r.integers(w * self.W + self.H1, (w + 1) * self.W - self.D - 2, per) for w in ws])

    def knn(self, idx):
        """Library neighbours (positions in the full array) of states idx."""
        d, ix = self.tree.query(self.Z[idx], self.K, workers=-1)
        return d, self.li[ix]

    def yhat_mean(self, window_sets):
        """Mean best saving of the K library neighbours (<= 0), for all valid states of the given windows."""
        out = np.full(self.N, np.nan)
        for ws in window_sets:
            q = self.valid(ws, 1)
            _, nb = self.knn(q)
            out[q] = self.ybest[nb].mean(axis=1)
        return out

    def summary(self):
        return dict(blocks=self.N, W=self.W, windows=self.nw, LIB=len(self.LIB), CAL=len(self.CAL), TEST=len(self.TEST))
