# NLR Pre-Market Pyth Lazer vs Pyth Core Comparison — Design

**Date:** 2026-04-09
**Type:** One-off ad-hoc analysis (not a reusable tool)
**Status:** Approved for implementation

## Goal

Document, with charts and stats, that the Pyth Lazer NLR.PRE feed
(`price_feed_id = 2928`) was stuck near $130 for the entire
**2026-04-08 08:00–09:00 UTC** pre-market hour, while Pyth Core
(`Equity.US.NLR/USD.PRE`, exported via Hermes) tracked the real
~$137–$138 price.

The deliverables (per-second CSV, three charts, markdown report) are
sufficient evidence to file/share the incident without requiring the reader
to re-derive anything from raw data.

## Inputs (CSVs already exported, no DB queries)

| Source                    | File                      | Key fields used                                                                         |
| ------------------------- | ------------------------- | --------------------------------------------------------------------------------------- |
| Pyth Core (Hermes export) | `hermes_price_export.csv` | `intervalTime`, `price`, `confidence`, `expo`                                           |
| Pyth Lazer (Pro export)   | `lazer_price_export.csv`  | `interval_price`, `price`, `confidence`, `best_bid_price`, `best_ask_price`, `exponent` |

Both files live at the repo root and are pre-trimmed to
`2026-04-08 08:00:00` → `2026-04-08 09:00:00` UTC inclusive (3601 rows
each, one per second).

### Schema notes

- **Hermes** filters to a single symbol, `Equity.US.NLR/USD.PRE`. The
  symbol value MUST equal that string for every row; the loader asserts
  this and aborts otherwise.
- **Lazer** filters to a single feed id, `2928`. The loader asserts every
  row has `price_feed_id == 2928` and aborts otherwise.
- Both sides use `expo == -5` (Hermes column name `expo`, Lazer column
  name `exponent`). The loader asserts this on both sides and aborts
  otherwise — better to fail loudly than silently mis-scale prices.
- Both sides convert `price * 10**expo` to USD floats. Same conversion
  applied to `confidence`, `best_bid_price`, `best_ask_price`.

## Constants (hardcoded in the script)

| Field                          | Value                                                                   |
| ------------------------------ | ----------------------------------------------------------------------- |
| Lazer feed id                  | `2928`                                                                  |
| Hermes symbol                  | `Equity.US.NLR/USD.PRE`                                                 |
| Window start (UTC, inclusive)  | `2026-04-08 08:00:00`                                                   |
| Window end (UTC, inclusive)    | `2026-04-08 09:00:00`                                                   |
| Expected row count per side    | `3601`                                                                  |
| Expected exponent (both sides) | `-5`                                                                    |
| Stuckness threshold            | `$0.01` (a Lazer second is "stuck" if `abs(lazer_price.diff()) < 0.01`) |
| Hermes CSV path                | `hermes_price_export.csv` (repo root)                                   |
| Lazer CSV path                 | `lazer_price_export.csv` (repo root)                                    |
| Output directory               | `output_csv/`                                                           |
| Output filename prefix         | `2928_nlr_pre_20260408_0800-0900`                                       |

No ClickHouse, no CLI flags, no environment variables — all of the above
are module-level constants.

## Processing

1. **Load** both CSVs into pandas DataFrames. Parse timestamp columns as
   UTC-aware `datetime64[ns, UTC]`. Set timestamp as the index.
2. **Validate** each frame in isolation (single symbol / single feed id,
   `expo == -5`, exactly 3601 rows). Raise `RuntimeError` with a useful
   message on any failure.
3. **Build** a complete 3601-second UTC index over
   `[08:00:00, 09:00:00]` inclusive via `pd.date_range`.
   Assert both inputs already align with this index (no reindex
   necessary). If they don't, raise — that's a data export bug, not
   something to silently paper over.
4. **Inner-join** Hermes and Lazer on the second-resolution timestamp,
   producing one merged frame with columns:
   `hermes_price`, `hermes_conf`,
   `lazer_price`, `lazer_conf`, `lazer_bid`, `lazer_ask`.
5. **Derive** these columns on the merged frame:
   - `deviation_abs = lazer_price - hermes_price` (USD)
   - `deviation_pct = (lazer_price - hermes_price) / hermes_price * 100`
     (Hermes is the reference because the user states Core was correct)
   - `lazer_spread = lazer_ask - lazer_bid` (USD)
   - `lazer_price_step = lazer_price.diff().abs()` (USD; first row is `NaN`)
   - `lazer_stuck = lazer_price_step < 0.01` (boolean; first row is `False`)
6. **Compute summary stats** (a single dict-of-scalars):
   - `max_abs_dev_pct`, `min_abs_dev_pct`, `mean_abs_dev_pct`
   - `max_abs_dev_usd`, `min_abs_dev_usd`, `mean_abs_dev_usd`
   - `max_dev_pct_ts` — UTC timestamp where `abs(deviation_pct)` is maximal
   - `mean_lazer_spread_usd`
   - `mean_lazer_conf_usd`, `mean_hermes_conf_usd`
   - `stuck_seconds_pct` — `lazer_stuck.sum() / (len - 1) * 100`
   - `hermes_price_first`, `hermes_price_last`
   - `lazer_price_first`, `lazer_price_last`

## Outputs

All written under `output_csv/` with the shared filename prefix
`2928_nlr_pre_20260408_0800-0900`:

| File                                                   | Purpose                                                                                                                                                                            |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `2928_nlr_pre_20260408_0800-0900.csv`                  | Per-second merged frame: `ts, hermes_price, hermes_conf, lazer_price, lazer_conf, lazer_bid, lazer_ask, deviation_abs, deviation_pct, lazer_spread, lazer_price_step, lazer_stuck` |
| `2928_nlr_pre_20260408_0800-0900_price_overlay.png`    | Chart 1 — price overlay                                                                                                                                                            |
| `2928_nlr_pre_20260408_0800-0900_deviation.png`        | Chart 2 — deviation curve                                                                                                                                                          |
| `2928_nlr_pre_20260408_0800-0900_lazer_diagnostic.png` | Chart 3 — Lazer self-diagnostic with Hermes overlay                                                                                                                                |
| `2928_nlr_pre_20260408_0800-0900_report.md`            | Markdown verdict + commentary, embedding Charts 1–3                                                                                                                                |

### Chart 1 — Price overlay (`_price_overlay.png`)

- Both lines on a shared y-axis across the full 08:00–09:00 UTC window.
- Hermes (Core) line and Lazer (Pro) line in distinct colors.
- No tolerance band — the gap between the two lines is the visual.
- Title: `NLR.PRE (Lazer feed 2928): Pyth Core vs Pyth Lazer — 2026-04-08 08:00–09:00 UTC`
- Y-axis: `Price (USD)`. X-axis time formatter: `HH:MM:SS`.
- Legend: top-right. Gridlines, seaborn-default styling — match the
  visual idiom of `scripts/wtik6_deviation_check.py`.

### Chart 2 — Deviation curve (`_deviation.png`)

- Line plot of signed `deviation_pct` (Lazer − Hermes) across the window.
- Solid horizontal line at `0%`.
- A horizontal dashed line at the **mean** `deviation_pct`, with a text
  annotation reading e.g. `mean = -5.51%`.
- No `±X%` threshold lines — this report is descriptive, not pass/fail.
- Title: `NLR.PRE (Lazer feed 2928) Lazer − Core deviation — 2026-04-08 08:00–09:00 UTC`
- Y-axis: `Deviation (%)`. X-axis time formatter: `HH:MM:SS`.

### Chart 3 — Lazer self-diagnostic (`_lazer_diagnostic.png`)

The most evidentiary chart. One panel:

- A shaded band between `lazer_bid` and `lazer_ask` (low alpha) — this
  is "Lazer's own quoted range".
- `lazer_price` line drawn inside the band.
- `hermes_price` line drawn over both, in a contrasting color.
- The viewer should see Hermes sitting _above_ Lazer's `best_ask` line
  for the entire window, which is the smoking gun: Lazer's own outputs
  did not contain the real price.
- Title: `NLR.PRE (Lazer feed 2928) Lazer bid/ask vs Core price — 2026-04-08 08:00–09:00 UTC`
- Y-axis: `Price (USD)`. X-axis time formatter: `HH:MM:SS`.
- Legend identifies: `Lazer bid/ask range`, `Lazer price`, `Core price (Hermes)`.

### Markdown report (`_report.md`)

Fixed four-section structure (mirrors the wtik6 report):

1. **Verdict** — one sentence stating Lazer was stuck near $130 the entire
   hour while Core tracked $137 → $138, with the mean absolute deviation
   in `%` and `$`. Example shape:
`"Pyth Lazer NLR.PRE (feed 2928) was stuck at $130.00 ±$0.0024 for the entire 2026-04-08 08:00–09:00 UTC pre-market hour while Pyth Core tracked $137.25 → $138.22 — a sustained mean deviation of −5.51% ($-7.57)."`
2. **Summary stats** — a markdown table with every value from the
   `summary stats` dict above. Include the timestamp of `max_abs_dev_pct`.
3. **Narrative** — 2–4 sentences that call out:
   - Lazer's published price sits ~$8 below Core throughout the window,
     even though Lazer's own bid/ask band (~$20 wide) is loose enough
     that Core still falls inside it ~95% of the hour — the band's
     width is the story, not whether Core breached it.
   - Lazer's confidence was pinned at the maximum (~$10.00), i.e. Lazer
     itself was already advertising "I do not know this price".
   - The `stuck_seconds_pct` measure (expected ~100%) showing Lazer
     essentially never moved.
4. **Caveats** — single price feed id `2928`, single 1-hour pre-market
   window, CSV-driven one-off analysis (not a reusable tool), Hermes
   used as the reference solely because the user reports Core was
   correct (this script does not independently validate that claim).

Charts 1–3 are embedded via relative markdown image references at the
top of the report.

## Script location

`scripts/nlr_lazer_vs_core_check.py` — a one-off, mirroring
`scripts/wtik6_deviation_check.py` in shape. Module-level constants for
feed id, symbol, window, paths, output prefix. No CLI flags.

Runnable as:

```bash
source venv/bin/activate
python3 scripts/nlr_lazer_vs_core_check.py
```

The script must succeed end-to-end on a clean checkout with the two CSVs
in place at the repo root. On any data-shape violation it should raise a
`RuntimeError` with a clear message and exit non-zero.

## Reused helpers / dependencies

- `pandas` — already in `requirements.txt`
- `matplotlib` (with `matplotlib.dates`) — already used by
  `scripts/wtik6_deviation_check.py`
- No `lib/` imports needed — this script is self-contained because it
  reads exported CSVs, not the ClickHouse clusters.

## Non-goals

- Not a reusable CLI — no `--feed-id`, `--symbol`, `--start`, `--end`,
  `--csv` flags.
- No tick-level analysis beyond the 1-second buckets that the exports
  already provide.
- No integration into `quick_benchmark.py`, `feed_readiness.py`, or any
  other existing tool.
- No unit tests — this is a one-off analysis script, not a library
  addition. (Matches the wtik6 precedent.)
- No threshold-based breach verdict — descriptive only.
- No EMA-price comparison — Hermes has `emaPrice` but Lazer has no
  equivalent column, so there is nothing to compare against.
- No ClickHouse queries — purely CSV-driven.
- No `.PRE` vs regular-session reconciliation — the export already
  contains only the pre-market symbol.
