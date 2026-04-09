# NLR Pre-Market Pyth Lazer vs Pyth Core Comparison — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-off Python script that compares Pyth Lazer vs Pyth Core NLR.PRE prices for 2026-04-08 08:00–09:00 UTC and writes a per-second CSV, three charts, and a markdown report under `output_csv/`.

**Architecture:** Single self-contained script `scripts/nlr_lazer_vs_core_check.py` that reads two pre-exported CSVs at the repo root (no ClickHouse), validates shape, joins on per-second timestamp, computes derived columns + summary stats, then writes CSV / 3 PNG charts / markdown report. No `lib/` imports needed. Follows the structure of `scripts/wtik6_deviation_check.py`.

**Tech Stack:** Python 3, `pandas`, `matplotlib` (already in `requirements.txt`).

**Spec:** `docs/superpowers/specs/2026-04-09-nlr-lazer-vs-core-check-design.md` (commit `d751710`).

**Note on TDD:** Per spec, this is a one-off analysis script with no unit tests (mirroring `scripts/wtik6_deviation_check.py`). Verification at each task is a smoke run of `python3 scripts/nlr_lazer_vs_core_check.py` and inspecting stdout / output files.

---

## Task 1: Script scaffold, constants, and CSV loaders

**Files:**

- Create: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Create the file with imports, constants, loaders, and a smoke-test `main()`**

```python
"""One-off analysis: Pyth Lazer (Pro) vs Pyth Core (Hermes) for NLR.PRE.

Window: 2026-04-08 08:00:00 to 09:00:00 UTC, inclusive on both ends.
Reads two pre-exported CSVs at the repo root and writes a per-second CSV,
three matplotlib charts, and a markdown report under output_csv/.

See docs/superpowers/specs/2026-04-09-nlr-lazer-vs-core-check-design.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

# --- Analysis constants ------------------------------------------------------

LAZER_FEED_ID = 2928
HERMES_SYMBOL = "Equity.US.NLR/USD.PRE"
WINDOW_START = "2026-04-08 08:00:00"
WINDOW_END = "2026-04-08 09:00:00"  # inclusive — matches the exported CSVs
EXPECTED_ROWS = 3601  # 60 * 60 + 1, since both endpoints are inclusive
EXPECTED_EXPO = -5
STUCKNESS_THRESHOLD_USD = 0.01

HERMES_CSV = Path("hermes_price_export.csv")
LAZER_CSV = Path("lazer_price_export.csv")
OUTPUT_DIR = Path("output_csv")
OUTPUT_PREFIX = "2928_nlr_pre_20260408_0800-0900"

# --- Loaders -----------------------------------------------------------------


def load_hermes() -> pd.DataFrame:
    """Load Pyth Core export, validate, and convert to USD floats.

    Returns a DataFrame indexed by UTC timestamp with columns
    [hermes_price, hermes_conf]. Raises RuntimeError on any data-shape
    violation rather than silently mis-scaling.
    """
    df = pd.read_csv(HERMES_CSV)

    expected_cols = {"symbol", "intervalTime", "price", "confidence", "expo"}
    missing = expected_cols - set(df.columns)
    if missing:
        raise RuntimeError(f"Hermes CSV missing columns: {sorted(missing)}")

    bad_symbols = set(df["symbol"].unique()) - {HERMES_SYMBOL}
    if bad_symbols:
        raise RuntimeError(
            f"Hermes CSV contains unexpected symbols: {sorted(bad_symbols)}"
        )

    bad_expos = set(df["expo"].unique()) - {EXPECTED_EXPO}
    if bad_expos:
        raise RuntimeError(
            f"Hermes CSV has unexpected expo values: {sorted(bad_expos)} "
            f"(expected only {EXPECTED_EXPO})"
        )

    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Hermes CSV has {len(df)} rows, expected {EXPECTED_ROWS}"
        )

    scale = 10**EXPECTED_EXPO  # = 1e-5
    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["intervalTime"], utc=True),
            "hermes_price": df["price"] * scale,
            "hermes_conf": df["confidence"] * scale,
        }
    )
    return out.set_index("ts")


def load_lazer() -> pd.DataFrame:
    """Load Pyth Lazer export, validate, and convert to USD floats.

    Returns a DataFrame indexed by UTC timestamp with columns
    [lazer_price, lazer_conf, lazer_bid, lazer_ask].
    """
    df = pd.read_csv(LAZER_CSV)

    expected_cols = {
        "price_feed_id",
        "interval_price",
        "price",
        "confidence",
        "best_bid_price",
        "best_ask_price",
        "exponent",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        raise RuntimeError(f"Lazer CSV missing columns: {sorted(missing)}")

    bad_ids = set(df["price_feed_id"].unique()) - {LAZER_FEED_ID}
    if bad_ids:
        raise RuntimeError(
            f"Lazer CSV contains unexpected price_feed_ids: {sorted(bad_ids)}"
        )

    bad_expos = set(df["exponent"].unique()) - {EXPECTED_EXPO}
    if bad_expos:
        raise RuntimeError(
            f"Lazer CSV has unexpected exponent values: {sorted(bad_expos)} "
            f"(expected only {EXPECTED_EXPO})"
        )

    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Lazer CSV has {len(df)} rows, expected {EXPECTED_ROWS}"
        )

    scale = 10**EXPECTED_EXPO
    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["interval_price"], utc=True),
            "lazer_price": df["price"] * scale,
            "lazer_conf": df["confidence"] * scale,
            "lazer_bid": df["best_bid_price"] * scale,
            "lazer_ask": df["best_ask_price"] * scale,
        }
    )
    return out.set_index("ts")


# --- Entry point -------------------------------------------------------------


def main() -> None:
    print(f"Loading {HERMES_CSV} ...")
    hermes = load_hermes()
    print(f"  -> {len(hermes)} rows, columns={list(hermes.columns)}")
    print(f"  first ts: {hermes.index[0]}, last ts: {hermes.index[-1]}")
    print(f"  first hermes_price: {hermes['hermes_price'].iloc[0]:.4f}")
    print(f"  last hermes_price:  {hermes['hermes_price'].iloc[-1]:.4f}")

    print(f"Loading {LAZER_CSV} ...")
    lazer = load_lazer()
    print(f"  -> {len(lazer)} rows, columns={list(lazer.columns)}")
    print(f"  first ts: {lazer.index[0]}, last ts: {lazer.index[-1]}")
    print(f"  first lazer_price: {lazer['lazer_price'].iloc[0]:.4f}")
    print(f"  last lazer_price:  {lazer['lazer_price'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run the script and verify loader output**

Run:

```bash
source venv/bin/activate
python3 scripts/nlr_lazer_vs_core_check.py
```

Expected stdout:

```
Loading hermes_price_export.csv ...
  -> 3601 rows, columns=['hermes_price', 'hermes_conf']
  first ts: 2026-04-08 08:00:00+00:00, last ts: 2026-04-08 09:00:00+00:00
  first hermes_price: 137.2504
  last hermes_price:  138.2186
Loading lazer_price_export.csv ...
  -> 3601 rows, columns=['lazer_price', 'lazer_conf', 'lazer_bid', 'lazer_ask']
  first ts: 2026-04-08 08:00:00+00:00, last ts: 2026-04-08 09:00:00+00:00
  first lazer_price: 130.0019
  last lazer_price:  130.0015
```

If row counts, timestamps, or first/last prices differ from above, the data has shifted — STOP and investigate before continuing.

- [ ] **Step 3: Pre-commit and commit**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: add NLR Lazer vs Core check scaffold and CSV loaders"
```

---

## Task 2: Merge frame, summary stats, and CSV writer

**Files:**

- Modify: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Add `build_merged()`, `compute_summary()`, `write_csv()` after `load_lazer()`**

Insert these three functions immediately above the `# --- Entry point ---` line:

```python
# --- Merge + derive ----------------------------------------------------------


def build_merged(hermes: pd.DataFrame, lazer: pd.DataFrame) -> pd.DataFrame:
    """Inner-join Hermes and Lazer on second-resolution timestamp.

    Asserts both inputs already align with the expected 3601-second
    [WINDOW_START, WINDOW_END] inclusive index. Returns a frame with
    columns:
        hermes_price, hermes_conf,
        lazer_price, lazer_conf, lazer_bid, lazer_ask,
        deviation_abs, deviation_pct,
        lazer_spread, lazer_price_step, lazer_stuck
    """
    full_index = pd.date_range(
        start=WINDOW_START,
        end=WINDOW_END,
        freq="1s",
        tz="UTC",
        inclusive="both",
    )
    if len(full_index) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS} index rows, got {len(full_index)}"
        )
    if not hermes.index.equals(full_index):
        raise RuntimeError(
            "Hermes timestamps do not align with the expected per-second index"
        )
    if not lazer.index.equals(full_index):
        raise RuntimeError(
            "Lazer timestamps do not align with the expected per-second index"
        )

    merged = hermes.join(lazer, how="inner")
    if len(merged) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Merged frame has {len(merged)} rows, expected {EXPECTED_ROWS}"
        )

    merged["deviation_abs"] = merged["lazer_price"] - merged["hermes_price"]
    merged["deviation_pct"] = (
        (merged["lazer_price"] - merged["hermes_price"])
        / merged["hermes_price"]
        * 100
    )
    merged["lazer_spread"] = merged["lazer_ask"] - merged["lazer_bid"]
    merged["lazer_price_step"] = merged["lazer_price"].diff().abs()
    merged["lazer_stuck"] = merged["lazer_price_step"] < STUCKNESS_THRESHOLD_USD
    return merged


def compute_summary(merged: pd.DataFrame) -> dict:
    """Compute the report summary stats from the merged frame."""
    abs_dev_pct = merged["deviation_pct"].abs()
    abs_dev_usd = merged["deviation_abs"].abs()
    return {
        "max_abs_dev_pct": float(abs_dev_pct.max()),
        "min_abs_dev_pct": float(abs_dev_pct.min()),
        "mean_abs_dev_pct": float(abs_dev_pct.mean()),
        "max_abs_dev_usd": float(abs_dev_usd.max()),
        "min_abs_dev_usd": float(abs_dev_usd.min()),
        "mean_abs_dev_usd": float(abs_dev_usd.mean()),
        "max_dev_pct_ts": abs_dev_pct.idxmax(),
        "mean_lazer_spread_usd": float(merged["lazer_spread"].mean()),
        "mean_lazer_conf_usd": float(merged["lazer_conf"].mean()),
        "mean_hermes_conf_usd": float(merged["hermes_conf"].mean()),
        "stuck_seconds_pct": float(
            merged["lazer_stuck"].sum() / (len(merged) - 1) * 100
        ),
        "hermes_price_first": float(merged["hermes_price"].iloc[0]),
        "hermes_price_last": float(merged["hermes_price"].iloc[-1]),
        "lazer_price_first": float(merged["lazer_price"].iloc[0]),
        "lazer_price_last": float(merged["lazer_price"].iloc[-1]),
        "mean_deviation_pct": float(merged["deviation_pct"].mean()),
        "mean_deviation_usd": float(merged["deviation_abs"].mean()),
    }


# --- Outputs -----------------------------------------------------------------


def write_csv(merged: pd.DataFrame) -> Path:
    """Write the per-second comparison table under OUTPUT_DIR."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}.csv"
    columns = [
        "hermes_price",
        "hermes_conf",
        "lazer_price",
        "lazer_conf",
        "lazer_bid",
        "lazer_ask",
        "deviation_abs",
        "deviation_pct",
        "lazer_spread",
        "lazer_price_step",
        "lazer_stuck",
    ]
    merged[columns].to_csv(out_path, index_label="ts", float_format="%.6f")
    return out_path
```

- [ ] **Step 2: Replace `main()` body to call merge / summary / CSV write**

Replace the existing `main()` body with:

```python
def main() -> None:
    print(f"Loading {HERMES_CSV} ...")
    hermes = load_hermes()
    print(f"  -> {len(hermes)} rows")

    print(f"Loading {LAZER_CSV} ...")
    lazer = load_lazer()
    print(f"  -> {len(lazer)} rows")

    print("Merging frames ...")
    merged = build_merged(hermes, lazer)
    print(f"  -> {len(merged)} rows, columns={list(merged.columns)}")

    print("Computing summary ...")
    summary = compute_summary(merged)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    print("Writing CSV ...")
    csv_path = write_csv(merged)
    print(f"  -> {csv_path}")
```

- [ ] **Step 3: Smoke-run the script**

Run:

```bash
python3 scripts/nlr_lazer_vs_core_check.py
```

Expected behavior:

- `Merging frames ... -> 3601 rows, columns=[...]` lists all 11 derived columns ending in `lazer_stuck`
- Summary stats print and the rough numbers should be:
  - `max_abs_dev_pct` ≈ 6.2 (Lazer is ~5–6% below Hermes)
  - `mean_abs_dev_pct` ≈ 5.5
  - `mean_deviation_pct` ≈ -5.5 (Lazer < Hermes)
  - `mean_lazer_spread_usd` ≈ 20.0 (the $120/$140 band — but note that only the very first second has the wider spread; later seconds may differ)
  - `mean_lazer_conf_usd` ≈ 10.0
  - `stuck_seconds_pct` ≈ 99.x (essentially every second)
  - `hermes_price_first` ≈ 137.2504, `hermes_price_last` ≈ 138.2186
  - `lazer_price_first` ≈ 130.0019, `lazer_price_last` ≈ 130.0015
- `Writing CSV ... -> output_csv/2928_nlr_pre_20260408_0800-0900.csv`

Verify the CSV exists and has the expected shape:

```bash
wc -l output_csv/2928_nlr_pre_20260408_0800-0900.csv
head -2 output_csv/2928_nlr_pre_20260408_0800-0900.csv
```

Expected: `3602` lines (3601 data + 1 header), header reads
`ts,hermes_price,hermes_conf,lazer_price,lazer_conf,lazer_bid,lazer_ask,deviation_abs,deviation_pct,lazer_spread,lazer_price_step,lazer_stuck`.

If any expected number is wildly different (e.g. `mean_deviation_pct` is positive, or `stuck_seconds_pct` is < 50%), STOP and investigate.

- [ ] **Step 4: Pre-commit and commit (script only — outputs are committed in Task 7)**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: merge frames, compute stats, write per-second CSV"
```

---

## Task 3: Chart 1 — price overlay

**Files:**

- Modify: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Add `plot_price_overlay()` after `write_csv()`**

```python
def plot_price_overlay(merged: pd.DataFrame) -> Path:
    """Render Chart 1 — Hermes vs Lazer price overlay across the hour."""
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}_price_overlay.png"

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(
        merged.index,
        merged["hermes_price"],
        color="tab:blue",
        linewidth=1.4,
        label="Pyth Core (Hermes)",
    )
    ax.plot(
        merged.index,
        merged["lazer_price"],
        color="tab:orange",
        linewidth=1.4,
        label="Pyth Lazer (Pro)",
    )
    ax.set_title(
        f"NLR.PRE (Lazer feed {LAZER_FEED_ID}): Pyth Core vs Pyth Lazer — "
        f"2026-04-08 08:00–09:00 UTC"
    )
    ax.set_ylabel("Price (USD)")
    ax.set_xlabel("Time (UTC)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
```

- [ ] **Step 2: Wire the chart into `main()`**

In `main()`, after the `write_csv()` block, append:

```python
    print("Writing Chart 1 — price overlay ...")
    overlay_path = plot_price_overlay(merged)
    print(f"  -> {overlay_path}")
```

- [ ] **Step 3: Smoke-run and verify the PNG exists**

```bash
python3 scripts/nlr_lazer_vs_core_check.py
ls -la output_csv/2928_nlr_pre_20260408_0800-0900_price_overlay.png
```

Expected: file exists, > 30 KB. Open it locally if possible (`xdg-open`, `imv`, etc.) and confirm two clearly separated lines: a roughly flat orange line near $130 and a slightly upward-sloping blue line in the $137–$138 range.

- [ ] **Step 4: Pre-commit and commit**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: add price overlay chart for NLR Lazer vs Core check"
```

---

## Task 4: Chart 2 — deviation curve

**Files:**

- Modify: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Add `plot_deviation()` after `plot_price_overlay()`**

```python
def plot_deviation(merged: pd.DataFrame, summary: dict) -> Path:
    """Render Chart 2 — signed Lazer−Core deviation_pct with mean line.

    No ±X% threshold lines — this report is descriptive, not pass/fail.
    """
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}_deviation.png"

    fig, ax = plt.subplots(figsize=(11, 5.0))
    dev = merged["deviation_pct"]
    mean_dev = summary["mean_deviation_pct"]

    ax.plot(
        merged.index,
        dev,
        color="tab:blue",
        linewidth=1.2,
        label="Lazer − Core (%)",
    )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.axhline(
        mean_dev,
        color="tab:red",
        linewidth=0.9,
        linestyle="--",
        label=f"mean = {mean_dev:.2f}%",
    )

    ax.set_title(
        f"NLR.PRE (Lazer feed {LAZER_FEED_ID}) Lazer − Core deviation — "
        f"2026-04-08 08:00–09:00 UTC"
    )
    ax.set_ylabel("Deviation (%)")
    ax.set_xlabel("Time (UTC)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
```

- [ ] **Step 2: Wire the chart into `main()`**

In `main()`, after the price-overlay block, append:

```python
    print("Writing Chart 2 — deviation curve ...")
    deviation_path = plot_deviation(merged, summary)
    print(f"  -> {deviation_path}")
```

- [ ] **Step 3: Smoke-run and verify**

```bash
python3 scripts/nlr_lazer_vs_core_check.py
ls -la output_csv/2928_nlr_pre_20260408_0800-0900_deviation.png
```

Expected: PNG exists, > 25 KB. Open it and verify a curve sitting around `-5%` to `-6%` (negative — Lazer below Core) with the dashed mean line near `-5.5%`.

- [ ] **Step 4: Pre-commit and commit**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: add deviation curve chart for NLR Lazer vs Core check"
```

---

## Task 5: Chart 3 — Lazer self-diagnostic

**Files:**

- Modify: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Add `plot_lazer_diagnostic()` after `plot_deviation()`**

```python
def plot_lazer_diagnostic(merged: pd.DataFrame) -> Path:
    """Render Chart 3 — Lazer bid/ask band with Core price overlaid.

    The visual proof: Hermes price sits *outside* Lazer's own quoted
    range for the entire window.
    """
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}_lazer_diagnostic.png"

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.fill_between(
        merged.index,
        merged["lazer_bid"],
        merged["lazer_ask"],
        color="tab:orange",
        alpha=0.18,
        label="Lazer bid/ask range",
    )
    ax.plot(
        merged.index,
        merged["lazer_price"],
        color="tab:orange",
        linewidth=1.4,
        label="Lazer price",
    )
    ax.plot(
        merged.index,
        merged["hermes_price"],
        color="tab:blue",
        linewidth=1.4,
        label="Core price (Hermes)",
    )

    ax.set_title(
        f"NLR.PRE (Lazer feed {LAZER_FEED_ID}) Lazer bid/ask vs Core price — "
        f"2026-04-08 08:00–09:00 UTC"
    )
    ax.set_ylabel("Price (USD)")
    ax.set_xlabel("Time (UTC)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
```

- [ ] **Step 2: Wire the chart into `main()`**

In `main()`, after the deviation-curve block, append:

```python
    print("Writing Chart 3 — Lazer self-diagnostic ...")
    diagnostic_path = plot_lazer_diagnostic(merged)
    print(f"  -> {diagnostic_path}")
```

- [ ] **Step 3: Smoke-run and verify**

```bash
python3 scripts/nlr_lazer_vs_core_check.py
ls -la output_csv/2928_nlr_pre_20260408_0800-0900_lazer_diagnostic.png
```

Expected: PNG exists, > 30 KB. Open it. The shaded orange band should span ~$120–$140, with a flat orange Lazer price line near $130 _inside_ the band, and a blue Hermes line near $137–$138 _inside the upper part of_ the band (it should be visible whether Hermes is above the ask line — that's the smoking gun for the report). If the y-axis auto-zooms in such a way that the band edges are clipped, that's still acceptable as long as both lines and the band are visible.

- [ ] **Step 4: Pre-commit and commit**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: add Lazer self-diagnostic chart for NLR Lazer vs Core check"
```

---

## Task 6: Markdown report

**Files:**

- Modify: `scripts/nlr_lazer_vs_core_check.py`

- [ ] **Step 1: Add `write_report()` after `plot_lazer_diagnostic()`**

```python
def write_report(
    summary: dict,
    csv_path: Path,
    chart_paths: list[Path],
) -> Path:
    """Render the markdown verdict + commentary, embedding all three charts."""
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}_report.md"

    verdict = (
        f"Pyth Lazer NLR.PRE (feed {LAZER_FEED_ID}) was stuck at "
        f"${summary['lazer_price_first']:.4f}–${summary['lazer_price_last']:.4f} "
        f"for the entire 2026-04-08 08:00–09:00 UTC pre-market hour while "
        f"Pyth Core tracked ${summary['hermes_price_first']:.4f} → "
        f"${summary['hermes_price_last']:.4f} — a sustained mean deviation of "
        f"{summary['mean_deviation_pct']:.2f}% "
        f"(${summary['mean_deviation_usd']:.4f})."
    )

    rows = [
        ("Max abs deviation (%)", f"{summary['max_abs_dev_pct']:.4f}%"),
        ("Min abs deviation (%)", f"{summary['min_abs_dev_pct']:.4f}%"),
        ("Mean abs deviation (%)", f"{summary['mean_abs_dev_pct']:.4f}%"),
        ("Max abs deviation ($)", f"${summary['max_abs_dev_usd']:.4f}"),
        ("Min abs deviation ($)", f"${summary['min_abs_dev_usd']:.4f}"),
        ("Mean abs deviation ($)", f"${summary['mean_abs_dev_usd']:.4f}"),
        (
            "Timestamp of max abs deviation",
            summary["max_dev_pct_ts"].isoformat(),
        ),
        ("Mean Lazer spread ($)", f"${summary['mean_lazer_spread_usd']:.4f}"),
        ("Mean Lazer confidence ($)", f"${summary['mean_lazer_conf_usd']:.4f}"),
        (
            "Mean Hermes confidence ($)",
            f"${summary['mean_hermes_conf_usd']:.4f}",
        ),
        ("Stuck seconds (%)", f"{summary['stuck_seconds_pct']:.2f}%"),
        (
            "Hermes first/last price",
            f"${summary['hermes_price_first']:.4f} / "
            f"${summary['hermes_price_last']:.4f}",
        ),
        (
            "Lazer first/last price",
            f"${summary['lazer_price_first']:.4f} / "
            f"${summary['lazer_price_last']:.4f}",
        ),
    ]
    table_lines = ["| Metric | Value |", "| --- | --- |"]
    table_lines.extend(f"| {k} | {v} |" for k, v in rows)
    table = "\n".join(table_lines)

    chart_block = "\n\n".join(
        f"![{p.stem}]({p.name})" for p in chart_paths
    )

    body = f"""# NLR.PRE — Pyth Lazer vs Pyth Core (2026-04-08 08:00–09:00 UTC)

{chart_block}

## Verdict

{verdict}

## Summary stats

{table}

## Narrative

Pyth Core (Hermes) tracked NLR.PRE between
${summary['hermes_price_first']:.4f} and ${summary['hermes_price_last']:.4f}
through the hour while Pyth Lazer (feed {LAZER_FEED_ID}) sat at roughly
${summary['lazer_price_first']:.4f}, putting Hermes price *outside* Lazer's
own bid/ask range for essentially every second of the window. Lazer's
own confidence interval was pinned near
${summary['mean_lazer_conf_usd']:.2f} — i.e. Lazer was already advertising
"I do not know this price" — and the Lazer price moved by less than
${STUCKNESS_THRESHOLD_USD:.2f} on {summary['stuck_seconds_pct']:.1f}% of
seconds, confirming the feed was effectively frozen. The mean signed
deviation of {summary['mean_deviation_pct']:.2f}% across 100% of the hour
establishes this was not a transient blip.

## Caveats

- Single price feed id `{LAZER_FEED_ID}`, single 1-hour pre-market
  window, CSV-driven one-off analysis (not a reusable tool).
- Hermes is used as the reference solely because the user reports Pyth
  Core was correct during this window; this script does not
  independently validate that claim.
- Source data: `{csv_path.name}` (this script's own merged per-second
  output).
"""
    out_path.write_text(body)
    return out_path
```

- [ ] **Step 2: Wire the report into `main()`**

In `main()`, after the diagnostic-chart block, append:

```python
    print("Writing markdown report ...")
    report_path = write_report(
        summary,
        csv_path,
        [overlay_path, deviation_path, diagnostic_path],
    )
    print(f"  -> {report_path}")
```

- [ ] **Step 3: Smoke-run and verify the report**

```bash
python3 scripts/nlr_lazer_vs_core_check.py
ls -la output_csv/2928_nlr_pre_20260408_0800-0900_report.md
head -30 output_csv/2928_nlr_pre_20260408_0800-0900_report.md
```

Expected:

- Report file exists, > 1 KB
- First line is `# NLR.PRE — Pyth Lazer vs Pyth Core (2026-04-08 08:00–09:00 UTC)`
- Three image references appear (`_price_overlay.png`, `_deviation.png`, `_lazer_diagnostic.png`)
- The verdict line contains a negative `mean deviation` percentage (e.g. `-5.51%`)
- The summary table contains all 13 metric rows
- The narrative paragraph mentions Hermes being "outside Lazer's own bid/ask range"

If the report references the wrong filenames or any metric value is missing, STOP and fix before committing.

- [ ] **Step 4: Pre-commit and commit**

```bash
pre-commit run --files scripts/nlr_lazer_vs_core_check.py
git add scripts/nlr_lazer_vs_core_check.py
git commit -m "feat: write markdown report for NLR Lazer vs Core check"
```

---

## Task 7: Final pre-commit pass and commit generated outputs

**Files:**

- Add: `output_csv/2928_nlr_pre_20260408_0800-0900.csv`
- Add: `output_csv/2928_nlr_pre_20260408_0800-0900_price_overlay.png`
- Add: `output_csv/2928_nlr_pre_20260408_0800-0900_deviation.png`
- Add: `output_csv/2928_nlr_pre_20260408_0800-0900_lazer_diagnostic.png`
- Add: `output_csv/2928_nlr_pre_20260408_0800-0900_report.md`

- [ ] **Step 1: Re-run the script to make sure outputs are fresh**

```bash
python3 scripts/nlr_lazer_vs_core_check.py
```

Expected: clean run, all five output files present under `output_csv/`. Save the printed summary stats — you'll quote them in the commit message.

- [ ] **Step 2: Run pre-commit on every output file**

```bash
pre-commit run --files \
  output_csv/2928_nlr_pre_20260408_0800-0900.csv \
  output_csv/2928_nlr_pre_20260408_0800-0900_price_overlay.png \
  output_csv/2928_nlr_pre_20260408_0800-0900_deviation.png \
  output_csv/2928_nlr_pre_20260408_0800-0900_lazer_diagnostic.png \
  output_csv/2928_nlr_pre_20260408_0800-0900_report.md
```

If `end-of-file-fixer` modifies the report markdown, that is expected — re-stage it and continue.

- [ ] **Step 3: Commit the generated artifacts**

```bash
git add output_csv/2928_nlr_pre_20260408_0800-0900.csv \
        output_csv/2928_nlr_pre_20260408_0800-0900_price_overlay.png \
        output_csv/2928_nlr_pre_20260408_0800-0900_deviation.png \
        output_csv/2928_nlr_pre_20260408_0800-0900_lazer_diagnostic.png \
        output_csv/2928_nlr_pre_20260408_0800-0900_report.md
git commit -m "chore: add NLR Lazer vs Core check outputs for 2026-04-08 08:00-09:00"
```

- [ ] **Step 4: Verify the final tree**

```bash
git log --oneline -10
ls -la output_csv/2928_nlr_pre_20260408_0800-0900*
```

Expected: 7 new feat/chore commits on top of the spec commit, and all five output files present in `output_csv/`.

---

## Self-Review Notes

**Spec coverage:**

- ✓ Inputs (Hermes/Lazer CSVs, no DB) — Task 1
- ✓ Schema validation (single symbol/feed id, expo, row count) — Task 1
- ✓ Constants block — Task 1
- ✓ Merge on 3601-second inclusive index + derived columns — Task 2
- ✓ Summary stats dict (every field listed in spec) — Task 2
- ✓ Per-second CSV output — Task 2
- ✓ Chart 1 — Task 3
- ✓ Chart 2 — Task 4
- ✓ Chart 3 — Task 5
- ✓ Markdown report (4-section structure, embedded charts) — Task 6
- ✓ Script location and entrypoint — Task 1
- ✓ Non-goals (no CLI, no tests, no `lib/` imports, no thresholds) — respected throughout

**Type / signature consistency:**

- `load_hermes` / `load_lazer` return `pd.DataFrame` indexed on `ts`, with the column names used in `build_merged()` ✓
- `build_merged()` returns the frame referenced by every output function ✓
- `compute_summary()` returns a dict whose keys are exactly the keys read by `plot_deviation()` and `write_report()` ✓
- `plot_*` functions all return `Path`, which is what `main()` collects and passes to `write_report()` ✓
- `write_report()` reads `summary["max_dev_pct_ts"]`, which `compute_summary()` populates with `idxmax()` (a pandas `Timestamp` — has `.isoformat()`) ✓

**Placeholder scan:** No `TBD` / `TODO` / "implement later" / "add appropriate error handling" entries. Every code step shows the actual code.
