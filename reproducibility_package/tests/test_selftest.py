"""Smoke test: the whole pipeline runs on synthetic data with a mock LLM (about 15 s)."""
import subprocess, sys, os, json
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
out = os.path.join(root, "results_selftest")
r = subprocess.run([sys.executable, os.path.join(root, "run_all.py"), "--selftest", "--cal-tx", "2", "--out", out,
                    "--cache", os.path.join(out, "cache")], capture_output=True, text=True)
assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
for f in ["Table2_primary.csv", "Table3_sensitivity.csv", "Table4_diagnostic.csv", "Table5_ablation.csv", "Figure1.png",
          "Figure2.png", "Figure3_frontier_hardened.png", "reconciliation.csv", "results.json"]:
    assert os.path.exists(os.path.join(out, f)), f
print("selftest OK")
