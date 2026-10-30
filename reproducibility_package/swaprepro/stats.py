"""Statistical helpers (seeds and formulas follow the original notebook)."""
import zlib
import numpy as np


def crc_seed(text: str) -> int:
    """Deterministic seed from a label, as in the original notebook."""
    return zlib.crc32(text.encode()) % (2 ** 31)


def boot_mean_ci(x, seed, B=3000):
    """Percentile bootstrap CI of the mean over clusters (here: windows)."""
    x = np.asarray(x, dtype=np.float64)
    bs = np.random.default_rng(seed).choice(x, size=(B, len(x)), replace=True).mean(axis=1)
    return float(x.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def holm(pvals: dict) -> dict:
    """Holm step-down adjustment. Input/output: {name: p}."""
    adj, cum = {}, 0.0
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    for i, (k, p) in enumerate(items):
        cum = max(cum, min(1.0, p * (len(items) - i)))
        adj[k] = cum
    return adj


def bh_qvalues(p_sorted_ascending):
    """Benjamini-Hochberg q-values for p-values sorted ascending."""
    p = np.asarray(p_sorted_ascending, dtype=float)
    m = len(p)
    return np.minimum.accumulate((p * m / (np.arange(m) + 1))[::-1])[::-1]
