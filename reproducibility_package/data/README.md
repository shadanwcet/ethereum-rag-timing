# Data

`blocks.csv` is **not** included (it is a public-chain extract). Create it once with the query below
(Google BigQuery public dataset, a few MB), then place it at `data/blocks.csv`.

```sql
SELECT number, UNIX_SECONDS(timestamp) AS timestamp, base_fee_per_gas
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp BETWEEN '2024-01-01' AND '2024-02-15'
ORDER BY number
```

Expected: 320,730 rows, columns `number, timestamp, base_fee_per_gas` (wei). The analyses use the first
316,800 consecutive blocks (44 days). `run_all.py` and the notebook print the file's SHA-256 so the exact
extract can be cited in the manuscript.

Colab: the notebook contains an optional cell that runs this query for you (needs your own Google Cloud
project id; the project id is deliberately NOT stored in this bundle).
