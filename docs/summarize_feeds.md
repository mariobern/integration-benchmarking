# Summarize Feeds Tool

Generates a single Excel summary workbook from the DQ reports produced by `evaluate_feeds_bulk`. Ranks the top publishers per feed/mode, applies per-mode pass thresholds, and emits a paste-ready `allowedPublisherIds` JSON snippet for config.

- Input: CSV of feeds + `dq_reports/<cluster>/<mode>/<feed_id>/<date>/stats.csv` files + `publishers.md`
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

# HK/JP/KR/IN equities (1 mode each); see Asset Classes & Modes below
python -m lazer_dq.summarize_feeds \
    --csv equity_hk_feed_ids.csv --asset-class hk-equities \
    --cluster lazer-prod --date 2026-05-19

# Override per-mode thresholds
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --max-rmse-over-spread-regular 0.8 --min-hit-rate-regular 85.0 \
    --max-rmse-over-spread-pre 1.5 --min-hit-rate-pre 60.0

# Override ranking knobs
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --top-n 15 --redundancy-floor 5 --topup-ceiling-mult 2.0 --min-n-observations 500

# Temporarily hold a jittery publisher out of the allowed lists (kept visible in rankings)
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --exclude-publisher 80
```

## Arguments

| Argument                           | Description                                                                                                             | Default                            |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `--csv`                            | CSV file (column 1 = `feed_id`) — **required**                                                                          | —                                  |
| `--cluster`                        | Cluster name — **required**                                                                                             | —                                  |
| `--date`                           | Date `YYYY-MM-DD` — **required**                                                                                        | —                                  |
| `--reports-dir`                    | Base reports directory                                                                                                  | `dq_reports`                       |
| `--publishers-md`                  | Path to `publishers.md`                                                                                                 | `publishers.md`                    |
| `--output`                         | Output `.xlsx` path                                                                                                     | `dq_summary_<cluster>_<date>.xlsx` |
| `--asset-class`                    | Asset class to summarize; sets which modes are read and the layout (see Asset Classes & Modes)                          | `us-equities`                      |
| `--max-rmse-over-spread-regular`   | RMSE/spread ceiling for `us-equities`                                                                                   | `1.0`                              |
| `--min-hit-rate-regular`           | Hit-rate floor (%) for `us-equities`                                                                                    | `80.0`                             |
| `--max-rmse-over-spread-pre`       | RMSE/spread ceiling for `us-equities-pre`                                                                               | `2.0`                              |
| `--min-hit-rate-pre`               | Hit-rate floor (%) for `us-equities-pre`                                                                                | `50.0`                             |
| `--max-rmse-over-spread-post`      | RMSE/spread ceiling for `us-equities-post`                                                                              | `2.0`                              |
| `--min-hit-rate-post`              | Hit-rate floor (%) for `us-equities-post`                                                                               | `50.0`                             |
| `--max-rmse-over-spread-overnight` | RMSE/spread ceiling for `us-equities-overnight`                                                                         | `3.0`                              |
| `--min-hit-rate-overnight`         | Hit-rate floor (%) for `us-equities-overnight`                                                                          | `25.0`                             |
| `--min-n-observations`             | Minimum sample size to consider a publisher                                                                             | `1000`                             |
| `--top-n`                          | Top-N publishers per feed/mode                                                                                          | `10`                               |
| `--redundancy-floor`               | Minimum publishers to return per feed/session (set `0` to disable top-ups)                                              | `5`                                |
| `--topup-ceiling-mult`             | A top-up's `rmse_over_spread` must be ≤ this × the per-mode pass threshold                                              | `2.0`                              |
| `--exclude-publisher`              | Publisher ID(s) to hold out of the `allowed` sheet only (still shown in `rankings`); floor auto-backfills the next-best | none (off)                         |

## Inputs

### CSV

Only column 1 (`feed_id`) is used; other columns are ignored. Malformed rows are skipped silently. Order of first-seen feed IDs is preserved.

### Per-feed DQ stats

Read from:

```
<reports-dir>/<cluster>/<mode>/<feed_id>/<date>/stats.csv
```

Missing files are treated as "no data" for that feed/mode — the feed is still listed but rendered as `(no data)`.

### publishers.md

Markdown table used to derive **excluded publishers**:

- ID `0` is always excluded.
- Any publisher whose Name ends with `.Test` is excluded.
- All other publishers are eligible.

Malformed rows are skipped silently.

## Asset Classes & Modes

`--asset-class` selects which modes are read and the workbook layout. Each feed is reported across that asset class's modes in stable order. Adding a new asset class is a one-entry edit to `ASSET_CLASS_CONFIG` in `summarize_feeds.py`.

**`us-equities`** (default) — 4 modes, 24-column rankings layout:

| Mode                    | Session     |
| ----------------------- | ----------- |
| `us-equities`           | REGULAR     |
| `us-equities-pre`       | PRE_MARKET  |
| `us-equities-post`      | POST_MARKET |
| `us-equities-overnight` | OVER_NIGHT  |

**Single-mode foreign equity classes** — 1 mode each, 6-column rankings layout, REGULAR session:

| Asset Class   | Mode          | Session |
| ------------- | ------------- | ------- |
| `hk-equities` | `hk-equities` | REGULAR |
| `jp-equities` | `jp-equities` | REGULAR |
| `kr-equities` | `kr-equities` | REGULAR |
| `in-equities` | `in-equities` | REGULAR |

Notes:

- The CSV's column-3 mode must be one of the selected asset class's modes, or the run exits with a clear error.
- The per-mode threshold flags (`--max-rmse-over-spread-*`, `--min-hit-rate-*`) apply only to `us-equities`. Other asset classes use the registry defaults — `hk-equities`, `jp-equities`, `kr-equities`, and `in-equities` REGULAR sessions all use `max rmse_over_spread 1.0` and `min hit_rate 80%`.

## Ranking & Filtering

For each `(feed_id, mode)`:

1. **Exclude** publishers in the excluded set (ID 0, `.Test`) — applies to both sheets.
2. **Rank** ascending by `rmse_over_spread`, keep top `--top-n`. This drives the `rankings` sheet and is _not_ filtered by the pass thresholds or `--min-n-observations`.
3. **Filter** by per-mode thresholds (`max-rmse-over-spread-*`, `min-hit-rate-*`) and apply the redundancy floor. This drives the `allowed` sheet:
   - **Passers** = publishers meeting all three thresholds — `rmse_over_spread`, `hit_rate`, and `n_observations ≥ --min-n-observations` — sorted ascending by `rmse_over_spread`.
   - If passers ≥ `--redundancy-floor` → return all passers (the floor is a minimum, never a cap).
   - If passers < `--redundancy-floor` → **top up** with the next-best below-threshold publishers, ranked by `rmse_over_spread`, each of which must clear `--min-n-observations` and have `rmse_over_spread ≤ --topup-ceiling-mult × max-rmse-over-spread-<mode>`. Take only as many as needed to reach the floor.
   - A publisher above the ceiling is never promoted, even if the feed stays below the floor.
   - **To disable top-ups entirely**, set `--redundancy-floor 0`: with no floor to reach, the `allowed` sheet contains only threshold passers (no below-threshold fillers). To tighten who counts as a passer instead, lower `--max-rmse-over-spread-*` or raise `--min-hit-rate-*`.
   - The `Notes` column shows the mix, e.g. `2 passed + 3 top-up (≤2×)` (highlighted yellow), or `0 passed, all > 2× ceiling` when no publisher is within the ceiling.

The cross-mode **aggregate** is the sorted union of per-mode allowed lists (deduplicated).

### Per-run publisher exclusion (`--exclude-publisher`)

`--exclude-publisher 80 [55 ...]` holds the given publisher IDs out of the
`allowed` sheet for this run only. The excluded publishers **remain visible in
the `rankings` sheet** (so their metrics can still be inspected), but they are
dropped before the threshold/floor filter that builds the `allowed` lists.
Because removal can push a feed/session below `--redundancy-floor`, the
existing top-up logic automatically backfills the next-best eligible publisher
("auto next-best" substitution) — feeds already above the floor simply lose the
excluded publisher with no replacement. When the flag is used, the `allowed`
sheet title row notes which publishers were excluded, and the run summary
prints how many feed/session cells were affected. This is a temporary,
per-run override; it does not touch `publishers.md`.

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
