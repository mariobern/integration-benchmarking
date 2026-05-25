# Summarize Feeds Tool

Generates a single Excel summary workbook from the DQ reports produced by `evaluate_feeds_bulk`. Ranks the top publishers per feed/mode, applies per-mode pass thresholds, and emits a paste-ready `allowedPublisherIds` JSON snippet for config.

- Input: CSV of feeds + `dq_reports/<cluster>/<feed_id>/<mode>/stats.csv` files + `publishers.md`
- Output: one `.xlsx` workbook with two sheets — `rankings` and `allowed`

## When to Use

| Scenario                                                | Use This Tool                   |
| ------------------------------------------------------- | ------------------------------- |
| Roll up bulk DQ outputs into a single workbook          | Yes                             |
| Build the `allowedPublisherIds` array for a feed config | Yes                             |
| Inspect per-feed/mode publisher rankings side-by-side   | Yes                             |
| Run DQ on the feeds (produce `stats.csv`)               | Use `evaluate_feeds_bulk` first |

## Usage

```bash
# Minimal: produces dq_summary_lazer-prod_2026-05-06.xlsx in cwd
python -m lazer_dq.summarize_feeds \
    --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06

# Explicit output + custom reports dir + publishers file
python -m lazer_dq.summarize_feeds \
    --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06 \
    --reports-dir dq_reports --publishers-md publishers.md \
    --output dq_summary_pre.xlsx

# Override per-mode thresholds
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --max-rmse-over-spread-regular 0.8 --min-hit-rate-regular 85.0 \
    --max-rmse-over-spread-pre 1.5 --min-hit-rate-pre 60.0

# Override ranking knobs
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --top-n 15 --redundancy-floor 5 --topup-ceiling-mult 2.0 --min-n-observations 500
```

## Arguments

| Argument                           | Description                                                                | Default                            |
| ---------------------------------- | -------------------------------------------------------------------------- | ---------------------------------- |
| `--csv`                            | CSV file (column 1 = `feed_id`) — **required**                             | —                                  |
| `--cluster`                        | Cluster name — **required**                                                | —                                  |
| `--date`                           | Date `YYYY-MM-DD` — **required**                                           | —                                  |
| `--reports-dir`                    | Base reports directory                                                     | `dq_reports`                       |
| `--publishers-md`                  | Path to `publishers.md`                                                    | `publishers.md`                    |
| `--output`                         | Output `.xlsx` path                                                        | `dq_summary_<cluster>_<date>.xlsx` |
| `--max-rmse-over-spread-regular`   | RMSE/spread ceiling for `us-equities`                                      | `1.0`                              |
| `--min-hit-rate-regular`           | Hit-rate floor (%) for `us-equities`                                       | `80.0`                             |
| `--max-rmse-over-spread-pre`       | RMSE/spread ceiling for `us-equities-pre`                                  | `2.0`                              |
| `--min-hit-rate-pre`               | Hit-rate floor (%) for `us-equities-pre`                                   | `50.0`                             |
| `--max-rmse-over-spread-post`      | RMSE/spread ceiling for `us-equities-post`                                 | `2.0`                              |
| `--min-hit-rate-post`              | Hit-rate floor (%) for `us-equities-post`                                  | `50.0`                             |
| `--max-rmse-over-spread-overnight` | RMSE/spread ceiling for `us-equities-overnight`                            | `3.0`                              |
| `--min-hit-rate-overnight`         | Hit-rate floor (%) for `us-equities-overnight`                             | `25.0`                             |
| `--min-n-observations`             | Minimum sample size to consider a publisher                                | `1000`                             |
| `--top-n`                          | Top-N publishers per feed/mode                                             | `10`                               |
| `--redundancy-floor`               | Minimum publishers to return per feed/session                              | `5`                                |
| `--topup-ceiling-mult`             | A top-up's `rmse_over_spread` must be ≤ this × the per-mode pass threshold | `2.0`                              |

## Inputs

### CSV

Only column 1 (`feed_id`) is used; other columns are ignored. Malformed rows are skipped silently. Order of first-seen feed IDs is preserved.

### Per-feed DQ stats

Read from:

```
<reports-dir>/<cluster>/<feed_id>/<mode>/stats.csv
```

Missing files are treated as "no data" for that feed/mode — the feed is still listed but rendered as `(no data)`.

### publishers.md

Markdown table used to derive **excluded publishers**:

- ID `0` is always excluded.
- Any publisher whose Name ends with `.Test` is excluded.
- All other publishers are eligible.

Malformed rows are skipped silently.

## Modes

Each feed is reported across four modes in stable order:

| Mode                    | Session     |
| ----------------------- | ----------- |
| `us-equities`           | REGULAR     |
| `us-equities-pre`       | PRE_MARKET  |
| `us-equities-post`      | POST_MARKET |
| `us-equities-overnight` | OVER_NIGHT  |

## Ranking & Filtering

For each `(feed_id, mode)`:

1. **Exclude** publishers in the excluded set (ID 0, `.Test`) — applies to both sheets.
2. **Rank** ascending by `rmse_over_spread`, keep top `--top-n`. This drives the `rankings` sheet and is _not_ filtered by the pass thresholds or `--min-n-observations`.
3. **Filter** by per-mode thresholds (`max-rmse-over-spread-*`, `min-hit-rate-*`) and apply the redundancy floor. This drives the `allowed` sheet:
   - **Passers** = publishers meeting all three thresholds — `rmse_over_spread`, `hit_rate`, and `n_observations ≥ --min-n-observations` — sorted ascending by `rmse_over_spread`.
   - If passers ≥ `--redundancy-floor` → return all passers (the floor is a minimum, never a cap).
   - If passers < `--redundancy-floor` → **top up** with the next-best below-threshold publishers, ranked by `rmse_over_spread`, each of which must clear `--min-n-observations` and have `rmse_over_spread ≤ --topup-ceiling-mult × max-rmse-over-spread-<mode>`. Take only as many as needed to reach the floor.
   - A publisher above the ceiling is never promoted, even if the feed stays below the floor.
   - The `Notes` column shows the mix, e.g. `2 passed + 3 top-up (≤2×)` (highlighted yellow), or `0 passed, all > 2× ceiling` when no publisher is within the ceiling.

The cross-mode **aggregate** is the sorted union of per-mode allowed lists (deduplicated).

## Output Workbook

### `rankings` sheet

Per-feed blocks, modes laid out side-by-side. Each mode column shows ranked publishers (top-N) with their `rmse_over_spread`, `hit_rate`, and `n_observations`. Useful for cross-mode comparison and threshold debugging.

### `allowed` sheet

Per-feed rows with paste-ready JSON arrays per mode plus the aggregate. Column C contains the **aggregate** `allowedPublisherIds` snippet formatted to drop into a config file:

```
allowedPublisherIds: [ 1, 7, 23, 31, 62 ],
```

(Matching the spacing and trailing comma style of `after.json`.)

Feeds with no data in any mode are listed in a `Skipped feeds` section at the bottom.

## Exit Codes

- `0` — workbook written.
- `1` — hard error (missing CSV / `publishers.md`, or no data found for **any** feed).
