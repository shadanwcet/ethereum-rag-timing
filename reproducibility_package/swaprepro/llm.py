"""Language-model arms: prompts, Ollama client, and a decision cache.

Modes
-----
cache : replay decisions from a shipped cache file (no GPU, no Ollama). A missing prompt raises CacheMiss.
live  : query a local Ollama server (qwen2.5:7b) and extend the cache.
mock  : deterministic fake answers for software self-tests ONLY (results are meaningless).

The cache key is sha256(model + digest + prompt), identical to the original notebook, so the original
cache file (ollama_qwen2.5_7b_test_cache.json) can be used unchanged.
"""
import hashlib, json, os, re, shutil, subprocess, threading, time, urllib.request
import numpy as np

SYS = ("You time an Ethereum swap. You pay the base fee of the block you submit in. "
       "Waiting is free except latency; there is a hard deadline after which the swap is submitted anyway. "
       "Reply with exactly one word: SUBMIT or WAIT.")
OPTIONS = {"temperature": 0.0, "seed": 42, "num_predict": 5}
OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL, DEFAULT_DIGEST = "qwen2.5:7b", "845dbda0ea48"


class CacheMiss(RuntimeError):
    pass


def prompt_retrieval(M, t, w, nb):
    """Prompt v2 (retrieval arm). The saving is printed as a (negative) relative change, as in the paper."""
    n0 = int((M.abest[nb] == 0).sum())
    med = float(np.median(M.ybest[nb])) if len(nb) > 0 else 0.0
    mb = int(np.median(M.abest[nb])) if len(nb) > 0 else 0
    return (
        f"Now (waited {w} of {M.D} blocks, 12s each): base fee {M.b[t]:.2f} gwei.\n"
        f"Context: now vs 1h mean {M.b[t]/M.m1[t]-1:+.1%}; vs 10min mean {M.b[t]/M.m2[t]-1:+.1%}; "
        f"fraction of the last hour cheaper than now {M.rank[t]:.0%}.\n"
        f"Among 10 similar past situations, submitting immediately was already cheapest in {n0}/10; "
        f"median best saving from waiting was {med:+.1%} (after ~{mb} blocks); typical across all situations {M.glob_best:+.1%}.\n"
        f"Only the fee in the block you submit in counts. Submitting now is correct when the current fee is low "
        f"relative to recent history. Decision (reply ONLY with SUBMIT or WAIT):")


def prompt_no_context(M, t0, t, w):
    return (f"Arrival base fee {M.b[t0]:.2f} gwei. Now (waited {w} of {M.D} blocks, 12s each): base fee {M.b[t]:.2f} gwei.\n"
            f"Decision (reply ONLY with SUBMIT or WAIT):")


def setup_ollama(model=DEFAULT_MODEL, conc=8):
    """Start (if needed) a local Ollama server, pull the model, warm it up. Never kills a running server."""
    import requests
    if shutil.which("ollama") is None:
        os.system("apt-get update -qq && apt-get install -y -qq zstd pciutils lshw > /dev/null")
        os.system("curl -fsSL https://ollama.com/install.sh | sh")
    os.environ.update(OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NUM_PARALLEL=str(conc), OLLAMA_FLASH_ATTENTION="1",
                      OLLAMA_KEEP_ALIVE="-1", OLLAMA_MAX_LOADED_MODELS="1")

    def alive():
        try:
            return requests.get(OLLAMA + "/api/tags", timeout=1).ok
        except Exception:
            return False

    if not alive():
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if alive():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Ollama did not start")
    tags = requests.get(OLLAMA + "/api/tags", timeout=5).json().get("models", [])
    if not any(m["name"].startswith(model) for m in tags):
        os.system(f"ollama pull {model}")
        tags = requests.get(OLLAMA + "/api/tags", timeout=5).json().get("models", [])
    digest = next((m["digest"][:12] for m in tags if m["name"].startswith(model)), "local")
    body = json.dumps({"model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 5}}).encode()
    for _ in range(2):
        urllib.request.urlopen(urllib.request.Request(OLLAMA + "/api/generate", data=body,
                               headers={"Content-Type": "application/json"}), timeout=300).read()
    return digest


class LLM:
    def __init__(self, mode="cache", model=DEFAULT_MODEL, digest=DEFAULT_DIGEST, cache_path="cache/llm_cache.json", conc=8):
        assert mode in ("cache", "live", "mock")
        self.mode, self.model, self.digest, self.conc = mode, model, digest, conc
        self.cache_path = cache_path
        self.cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        self.lock = threading.Lock()
        self.n_hits = self.n_new = 0
        if mode == "live":
            self.digest = setup_ollama(model, conc)

    def key(self, prompt):
        return hashlib.sha256((self.model + self.digest + prompt).encode()).hexdigest()

    def _call(self, prompt):
        payload = json.dumps({"model": self.model, "system": SYS, "prompt": prompt, "stream": False,
                              "options": OPTIONS}).encode()
        req = urllib.request.Request(OLLAMA + "/api/generate", data=payload, headers={"Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    out = json.loads(r.read().decode()).get("response", "").strip().upper()
                m = re.search(r"SUBMIT|WAIT", out)
                if not m:
                    raise RuntimeError(f"Unparseable model output: {out!r}")
                return m.group(0)
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))

    @staticmethod
    def _mock(prompt):
        m = re.search(r"cheaper than now (\d+)%", prompt)
        r = int(m.group(1)) / 100 if m else 0.5
        h = int(hashlib.md5(prompt.encode()).hexdigest()[:4], 16) / 65535
        return "SUBMIT" if (r <= 0.3 or h < 0.15) else "WAIT"

    def decide(self, prompt):
        k = self.key(prompt)
        if k in self.cache:
            self.n_hits += 1
            return self.cache[k]
        if self.mode == "cache":
            raise CacheMiss("Prompt not in cache. Put the original cache file in cache/ or rerun with mode='live'.\n" + prompt[:300])
        ans = self._mock(prompt) if self.mode == "mock" else self._call(prompt)
        with self.lock:
            self.cache[k] = ans
            self.n_new += 1
        return ans

    def save(self):
        if self.n_new == 0:
            return
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        tmp = self.cache_path + ".tmp"
        with self.lock, open(tmp, "w") as f:
            json.dump(self.cache, f)
        os.replace(tmp, self.cache_path)
