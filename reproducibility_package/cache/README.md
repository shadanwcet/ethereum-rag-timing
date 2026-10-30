# Language-model answer caches

Place the original cache files here to regenerate the language-model results **without a GPU**:

| File | Used by | Contents |
|---|---|---|
| `ollama_qwen2.5_7b_test_cache.json` | Table 2 / Figure 1 (primary LLM arms) | answers keyed by sha256(model + digest + prompt) |
| `ablation_v2_llm_store.json` | Table 5 / Figure 2 (prompt ablation) | answers for the nine prompt variants on the calibration split |

Both files were written by the original Colab runs (Drive folder `Experiments/rag_ethereum_cache`).
Model: `qwen2.5:7b`, digest `845dbda0ea48`, temperature 0, seed 42, 5 tokens.

If a prompt is missing, `mode="cache"` stops with a clear error. Use `mode="live"` (Ollama, GPU) to
regenerate and extend the cache. Deposit these two files with the code (they are small JSON files).
