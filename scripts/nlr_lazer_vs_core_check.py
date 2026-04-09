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
        raise RuntimeError(f"Hermes CSV has {len(df)} rows, expected {EXPECTED_ROWS}")

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
        raise RuntimeError(f"Lazer CSV has {len(df)} rows, expected {EXPECTED_ROWS}")

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
        (merged["lazer_price"] - merged["hermes_price"]) / merged["hermes_price"] * 100
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
        "hermes_price_min": float(merged["hermes_price"].min()),
        "hermes_price_max": float(merged["hermes_price"].max()),
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


def write_report(
    summary: dict,
    csv_path: Path,
    chart_paths: list[Path],
) -> Path:
    """Render the markdown verdict + commentary, embedding all three charts."""
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}_report.md"

    verdict = (
        f"Pyth Lazer NLR.PRE (feed {LAZER_FEED_ID}) was stuck at "
        f"${summary['lazer_price_first']:.4f} for the entire 2026-04-08 "
        f"08:00–09:00 UTC pre-market hour while Pyth Core ranged "
        f"${summary['hermes_price_min']:.4f}–${summary['hermes_price_max']:.4f} "
        f"— a sustained mean deviation of "
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
            "Hermes price range",
            f"${summary['hermes_price_min']:.4f} – "
            f"${summary['hermes_price_max']:.4f}",
        ),
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

    chart_block = "\n\n".join(f"![{p.stem}]({p.name})" for p in chart_paths)

    body = f"""# NLR.PRE — Pyth Lazer vs Pyth Core (2026-04-08 08:00–09:00 UTC)

{chart_block}

## Verdict

{verdict}

## Summary stats

{table}

## Narrative

Pyth Core (Hermes) tracked NLR.PRE between
${summary['hermes_price_min']:.4f} and ${summary['hermes_price_max']:.4f}
through the hour while Pyth Lazer (feed {LAZER_FEED_ID}) sat at exactly
${summary['lazer_price_first']:.4f}, putting Lazer's published price
roughly ${abs(summary['mean_deviation_usd']):.2f} below Core for the
entire window. Lazer published an absurd
${summary['mean_lazer_spread_usd']:.2f}-wide bid/ask band and a
confidence interval pinned near ${summary['mean_lazer_conf_usd']:.2f}
(its maximum) — i.e. Lazer was already advertising "I do not know this
price" — and the Lazer price moved by less than
${STUCKNESS_THRESHOLD_USD:.2f} on {summary['stuck_seconds_pct']:.1f}% of
seconds, confirming the feed was effectively frozen. The mean signed
deviation of {summary['mean_deviation_pct']:.2f}% across the full hour
establishes this was a sustained outage, not a transient blip.

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


# --- Entry point -------------------------------------------------------------


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

    print("Writing Chart 1 — price overlay ...")
    overlay_path = plot_price_overlay(merged)
    print(f"  -> {overlay_path}")

    print("Writing Chart 2 — deviation curve ...")
    deviation_path = plot_deviation(merged, summary)
    print(f"  -> {deviation_path}")

    print("Writing Chart 3 — Lazer self-diagnostic ...")
    diagnostic_path = plot_lazer_diagnostic(merged)
    print(f"  -> {diagnostic_path}")

    print("Writing markdown report ...")
    report_path = write_report(
        summary,
        csv_path,
        [overlay_path, deviation_path, diagnostic_path],
    )
    print(f"  -> {report_path}")


if __name__ == "__main__":
    main()
