#!/usr/bin/env python3
"""Volume profile analysis for US equities.

Queries Datascope benchmark data to compute per-session trading volume
and generates a liquidity profile report (CSV + HTML).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from lib.config import get_analytics_client, get_lazer_client, load_config

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def parse_tickers(args) -> list[str]:
    """Parse tickers from --tickers or --ticker-file."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    with open(args.ticker_file) as f:
        return [
            line.strip().upper()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def resolve_tickers(client_lazer, tickers: list[str]) -> dict[str, dict]:
    """Resolve tickers to pyth_lazer_id via feeds_metadata_latest.

    Returns dict mapping ticker -> {pyth_lazer_id, symbol}.
    Matches on the last segment of the symbol (e.g., Equity.US.AAPL/USD -> AAPL).
    """
    query = """
        SELECT pyth_lazer_id, symbol
        FROM feeds_metadata_latest
        WHERE symbol LIKE 'Equity.US.%'
    """
    result = client_lazer.query(query)

    ticker_set = {t.upper() for t in tickers}
    resolved = {}

    for row in result.result_rows:
        feed_id, symbol = row[0], row[1]
        parts = symbol.split(".")
        if len(parts) < 3:
            continue
        ticker_part = parts[-1].split("/")[0]
        if ticker_part.upper() in ticker_set:
            resolved[ticker_part.upper()] = {
                "pyth_lazer_id": feed_id,
                "symbol": symbol,
            }

    return resolved


def get_session_boundaries(d: date) -> dict[str, tuple[datetime, datetime]]:
    """Compute UTC boundaries for each trading session on the given date.

    Returns dict of session_name -> (start_utc, end_utc).
    Handles EST/EDT automatically via zoneinfo.
    """
    dt = datetime(d.year, d.month, d.day, tzinfo=ET)

    pre_start = dt.replace(hour=4, minute=0)
    regular_start = dt.replace(hour=9, minute=30)
    regular_end = dt.replace(hour=16, minute=0)
    after_end = dt.replace(hour=20, minute=0)

    return {
        "pre_market": (pre_start.astimezone(UTC), regular_start.astimezone(UTC)),
        "regular": (regular_start.astimezone(UTC), regular_end.astimezone(UTC)),
        "after_hours": (regular_end.astimezone(UTC), after_end.astimezone(UTC)),
    }


def fetch_session_volume(client_analytics, feed_ids: list[int], d: date) -> list[dict]:
    """Query Datascope for per-session volume and close price.

    Returns list of dicts with keys:
    pyth_lazer_id, ric, session, total_volume, obs_count
    """
    boundaries = get_session_boundaries(d)

    pre_start, pre_end = boundaries["pre_market"]
    reg_start, reg_end = boundaries["regular"]
    ah_start, ah_end = boundaries["after_hours"]

    fmt = "%Y-%m-%d %H:%M:%S"

    query = f"""
        SELECT
            pyth_lazer_id,
            ric,
            CASE
                WHEN date_time >= '{pre_start.strftime(fmt)}'
                     AND date_time < '{pre_end.strftime(fmt)}'
                    THEN 'pre_market'
                WHEN date_time >= '{reg_start.strftime(fmt)}'
                     AND date_time < '{reg_end.strftime(fmt)}'
                    THEN 'regular'
                WHEN date_time >= '{ah_start.strftime(fmt)}'
                     AND date_time < '{ah_end.strftime(fmt)}'
                    THEN 'after_hours'
                ELSE 'other'
            END AS session,
            sum(volume) AS total_volume,
            count() AS obs_count
        FROM datascope_global_equities_benchmark_data
        WHERE pyth_lazer_id IN ({','.join(str(fid) for fid in feed_ids)})
          AND toDate(date_time) = '{d.isoformat()}'
        GROUP BY pyth_lazer_id, ric, session
        HAVING session != 'other'
        ORDER BY pyth_lazer_id, session
    """
    result = client_analytics.query(query)

    rows = []
    for row in result.result_rows:
        rows.append(
            {
                "pyth_lazer_id": row[0],
                "ric": row[1],
                "session": row[2],
                "total_volume": row[3] or 0,
                "obs_count": row[4],
            }
        )
    return rows


def fetch_close_prices(
    client_analytics, feed_ids: list[int], d: date
) -> dict[int, float]:
    """Get the last trade price near market close (4 PM ET) for each feed.

    Returns dict of pyth_lazer_id -> close_price.
    """
    boundaries = get_session_boundaries(d)
    reg_start, reg_end = boundaries["regular"]
    fmt = "%Y-%m-%d %H:%M:%S"

    query = f"""
        SELECT pyth_lazer_id, argMax(price, date_time) AS close_price
        FROM datascope_global_equities_benchmark_data
        WHERE pyth_lazer_id IN ({','.join(str(fid) for fid in feed_ids)})
          AND toDate(date_time) = '{d.isoformat()}'
          AND date_time >= '{reg_start.strftime(fmt)}'
          AND date_time < '{reg_end.strftime(fmt)}'
          AND price IS NOT NULL
        GROUP BY pyth_lazer_id
    """
    result = client_analytics.query(query)
    return {row[0]: row[1] for row in result.result_rows}


def fetch_overnight_obs(client_lazer, feed_ids: list[int], d: date) -> dict[int, int]:
    """Count publisher updates during overnight session (8 PM - 4 AM ET).

    Returns dict of pyth_lazer_id -> observation_count.
    """
    dt = datetime(d.year, d.month, d.day, tzinfo=ET)
    overnight_start = dt.replace(hour=20, minute=0).astimezone(UTC)
    overnight_end = (
        (dt + timedelta(days=1)).replace(hour=4, minute=0, tzinfo=ET).astimezone(UTC)
    )
    fmt = "%Y-%m-%d %H:%M:%S"

    query = f"""
        SELECT price_feed_id, count() AS obs_count
        FROM publisher_updates
        WHERE price_feed_id IN ({','.join(str(fid) for fid in feed_ids)})
          AND publish_time >= '{overnight_start.strftime(fmt)}'
          AND publish_time < '{overnight_end.strftime(fmt)}'
        GROUP BY price_feed_id
    """
    result = client_lazer.query(query)
    return {row[0]: row[1] for row in result.result_rows}


def _price_activity_ratio(session_data: pd.DataFrame) -> float:
    """Fraction of bars with price change (0.0 - 1.0)."""
    if session_data.empty or len(session_data) < 2:
        return 0.0
    closes = session_data["Close"]
    changes = (closes != closes.shift()).sum()
    return round(float(changes / len(session_data)), 4)


def fetch_yfinance_volume(tickers: list[str], d: date) -> list[dict]:
    """Fetch per-session volume from yfinance for tickers not in Datascope.

    Uses two yfinance calls:
    - 5m bars (prepost=True): regular session volume + price activity in extended hours
    - 1d bar: total daily volume (includes extended hours)

    Extended-hours volume is estimated as daily_vol - regular_vol, then split
    proportionally between pre-market and after-hours based on active bar count.

    Returns list of dicts with keys:
    ticker, session, total_volume, close_price, data_source,
    pre_price_activity, ah_price_activity
    """
    if not tickers:
        return []

    start = d.isoformat()
    end = (d + timedelta(days=1)).isoformat()

    print(f"  Fetching {len(tickers)} tickers from yfinance...", file=sys.stderr)

    # 5m bars for session bucketing + price activity
    data_5m = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="5m",
        prepost=True,
        progress=False,
    )

    # 1d bar for total daily volume (includes extended hours)
    data_1d = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        progress=False,
    )

    if data_5m.empty:
        print("  Warning: yfinance returned no data", file=sys.stderr)
        return []

    rows = []
    is_multi_5m = isinstance(data_5m.columns, pd.MultiIndex)
    is_multi_1d = (
        isinstance(data_1d.columns, pd.MultiIndex) if not data_1d.empty else False
    )

    for ticker in tickers:
        try:
            # Extract per-ticker 5m data
            if is_multi_5m:
                ticker_5m = data_5m.xs(ticker, level=1, axis=1)
            else:
                ticker_5m = data_5m

            if ticker_5m.empty:
                continue

            # Extract per-ticker 1d data
            daily_vol = 0
            if not data_1d.empty:
                try:
                    if is_multi_1d:
                        ticker_1d = data_1d.xs(ticker, level=1, axis=1)
                    else:
                        ticker_1d = data_1d
                    if not ticker_1d.empty:
                        daily_vol = int(ticker_1d["Volume"].iloc[0])
                except (KeyError, IndexError):
                    pass

            # Ensure timezone is ET
            idx = ticker_5m.index
            if idx.tz is None:
                idx = idx.tz_localize("America/New_York")
            else:
                idx = idx.tz_convert("America/New_York")
            ticker_5m = ticker_5m.copy()
            ticker_5m.index = idx

            # Bucket by session
            pre = ticker_5m.between_time("04:00", "09:29")
            regular = ticker_5m.between_time("09:30", "15:59")
            after = ticker_5m.between_time("16:00", "19:59")

            # Close price = last regular session bar's Close
            close_price = (
                float(regular["Close"].iloc[-1]) if not regular.empty else None
            )

            # Regular volume from 5m bars (accurate)
            regular_vol = int(regular["Volume"].sum()) if not regular.empty else 0

            # Extended volume estimate = daily total - regular
            extended_vol = max(0, daily_vol - regular_vol)

            # Price activity ratio per session
            pre_activity = _price_activity_ratio(pre)
            ah_activity = _price_activity_ratio(after)

            # Split extended volume proportionally by active bar count
            pre_active_bars = (
                int((pre["Close"] != pre["Close"].shift()).sum())
                if not pre.empty
                else 0
            )
            ah_active_bars = (
                int((after["Close"] != after["Close"].shift()).sum())
                if not after.empty
                else 0
            )
            total_active = pre_active_bars + ah_active_bars

            if total_active > 0 and extended_vol > 0:
                pre_vol = int(extended_vol * pre_active_bars / total_active)
                ah_vol = extended_vol - pre_vol  # remainder to avoid rounding loss
            else:
                pre_vol = 0
                ah_vol = 0

            for session, vol in [
                ("pre_market", pre_vol),
                ("regular", regular_vol),
                ("after_hours", ah_vol),
            ]:
                rows.append(
                    {
                        "ticker": ticker,
                        "session": session,
                        "total_volume": vol,
                        "close_price": close_price,
                        "data_source": "yfinance",
                        "pre_price_activity": pre_activity,
                        "ah_price_activity": ah_activity,
                    }
                )
        except Exception as e:
            print(f"  Warning: yfinance error for {ticker}: {e}", file=sys.stderr)

    return rows


def classify_tier(total_dollar_vol: float) -> str:
    """Assign liquidity tier based on total daily dollar volume."""
    if pd.isna(total_dollar_vol):
        return "UNKNOWN"
    if total_dollar_vol >= 50_000_000:
        return "HIGH"
    if total_dollar_vol >= 5_000_000:
        return "MEDIUM"
    return "LOW"


def classify_recommendation(row) -> str:
    """Assign session recommendation based on tier and session percentages."""
    tier = row.get("liquidity_tier", "UNKNOWN")
    ah_pct = row.get("after_hours_pct", 0) or 0
    overnight_obs = row.get("overnight_benchmark_obs", 0) or 0

    if tier == "HIGH" and ah_pct > 1.0 and overnight_obs > 100:
        return "24/5 viable"
    if tier == "HIGH" and ah_pct > 1.0:
        return "Regular + Extended"
    if tier == "MEDIUM" and ah_pct > 0.5:
        return "Regular + Extended (review)"
    return "Regular only"


def build_volume_dataframe(
    resolved: dict[str, dict],
    datascope_rows: list[dict],
    close_prices: dict[int, float],
    yfinance_rows: list[dict],
    overnight_obs: dict[int, int],
) -> pd.DataFrame:
    """Pivot session volume rows into one row per ticker with all metrics.

    Merges Datascope rows (resolved tickers) and yfinance rows (unresolved).
    """
    # --- Datascope tickers ---
    id_to_ticker = {v["pyth_lazer_id"]: k for k, v in resolved.items()}
    records = {}
    for row in datascope_rows:
        fid = row["pyth_lazer_id"]
        ticker = id_to_ticker.get(fid)
        if not ticker:
            continue
        if ticker not in records:
            records[ticker] = {
                "ticker": ticker,
                "pyth_lazer_id": fid,
                "ric": row["ric"],
                "data_source": "datascope",
            }
        session = row["session"]
        records[ticker][f"{session}_vol"] = row["total_volume"]

    # Add Datascope close prices and overnight obs
    for ticker, info in resolved.items():
        if ticker in records:
            fid = info["pyth_lazer_id"]
            records[ticker]["close_price"] = close_prices.get(fid)
            records[ticker]["overnight_benchmark_obs"] = overnight_obs.get(fid, 0)

    # --- yfinance tickers ---
    for row in yfinance_rows:
        ticker = row["ticker"]
        if ticker not in records:
            records[ticker] = {
                "ticker": ticker,
                "pyth_lazer_id": None,
                "ric": "",
                "data_source": "yfinance",
                "close_price": row.get("close_price"),
                "overnight_benchmark_obs": None,
                "pre_price_activity": row.get("pre_price_activity"),
                "ah_price_activity": row.get("ah_price_activity"),
            }
        session = row["session"]
        records[ticker][f"{session}_vol"] = row["total_volume"]

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records.values())

    # Fill missing sessions with 0
    for col in ["pre_market_vol", "regular_vol", "after_hours_vol"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0).astype(int)

    # Total volume
    df["total_vol"] = df["pre_market_vol"] + df["regular_vol"] + df["after_hours_vol"]

    # Dollar volumes
    for session in ["pre_market", "regular", "after_hours", "total"]:
        df[f"{session}_dollar_vol"] = df[f"{session}_vol"] * df["close_price"]

    # Session percentages
    for session in ["pre_market", "regular", "after_hours"]:
        col_name = f"{session}_pct"
        df[col_name] = (
            df[f"{session}_vol"] / df["total_vol"].replace(0, float("nan")) * 100
        ).round(2)

    # Liquidity tier
    df["liquidity_tier"] = df["total_dollar_vol"].apply(classify_tier)

    # Session recommendation
    df["session_recommendation"] = df.apply(classify_recommendation, axis=1)

    # Sort by total dollar volume descending
    df = df.sort_values("total_dollar_vol", ascending=False).reset_index(drop=True)

    return df


def get_trading_dates(end_date: date, days: int) -> list[date]:
    """Get the last N calendar dates ending at end_date.

    Note: This uses calendar days, not trading days. Weekends/holidays
    will simply return no data from ClickHouse and are harmless.
    """
    return [end_date - timedelta(days=i) for i in range(days)]


def render_html_report(df: pd.DataFrame, report_date: str, days: int) -> str:
    """Generate a self-contained HTML report from the volume DataFrame."""
    table_rows = []
    for _, row in df.iterrows():
        tier = row.get("liquidity_tier", "UNKNOWN")
        tier_class = tier.lower()

        pre_pct = row.get("pre_market_pct", 0) or 0
        reg_pct = row.get("regular_pct", 0) or 0
        ah_pct = row.get("after_hours_pct", 0) or 0

        pyth_id = row.get("pyth_lazer_id", "")
        pyth_id_str = str(int(pyth_id)) if pd.notna(pyth_id) else ""

        close_price = row.get("close_price", 0)
        close_str = f"${close_price:,.2f}" if pd.notna(close_price) else "N/A"

        overnight = row.get("overnight_benchmark_obs", "")
        overnight_str = (
            f"{int(overnight):,}" if pd.notna(overnight) and overnight != "" else "N/A"
        )

        # Price activity columns (yfinance only)
        pre_act = row.get("pre_price_activity", "")
        ah_act = row.get("ah_price_activity", "")
        pre_act_str = f"{pre_act:.0%}" if pd.notna(pre_act) and pre_act != "" else ""
        ah_act_str = f"{ah_act:.0%}" if pd.notna(ah_act) and ah_act != "" else ""

        table_rows.append(
            f"""
        <tr class="{tier_class}">
            <td>{row['ticker']}</td>
            <td>{pyth_id_str}</td>
            <td>{close_str}</td>
            <td>{row.get('pre_market_vol', 0):,.0f}</td>
            <td>${row.get('pre_market_dollar_vol', 0):,.0f}</td>
            <td>{row.get('regular_vol', 0):,.0f}</td>
            <td>${row.get('regular_dollar_vol', 0):,.0f}</td>
            <td>{row.get('after_hours_vol', 0):,.0f}</td>
            <td>${row.get('after_hours_dollar_vol', 0):,.0f}</td>
            <td>{overnight_str}</td>
            <td>{row.get('total_vol', 0):,.0f}</td>
            <td>${row.get('total_dollar_vol', 0):,.0f}</td>
            <td>
                <div class="session-bar">
                    <div class="pre" style="width:{pre_pct}%" title="Pre {pre_pct:.1f}%"></div>
                    <div class="reg" style="width:{reg_pct}%" title="Reg {reg_pct:.1f}%"></div>
                    <div class="ah" style="width:{ah_pct}%" title="AH {ah_pct:.1f}%"></div>
                </div>
            </td>
            <td>{pre_act_str}</td>
            <td>{ah_act_str}</td>
            <td><span class="tier {tier_class}">{tier}</span></td>
            <td>{row.get('session_recommendation', '')}</td>
            <td>{row.get('data_source', '')}</td>
        </tr>"""
        )

    tier_counts = df["liquidity_tier"].value_counts()
    high = tier_counts.get("HIGH", 0)
    medium = tier_counts.get("MEDIUM", 0)
    low = tier_counts.get("LOW", 0)

    days_label = f" ({days}-day avg)" if days > 1 else ""
    days_col = "<th>Days Sampled</th>" if "days_sampled" in df.columns else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Volume Profile Report - {report_date}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #f8f9fa; color: #333; }}
  h1 {{ margin-bottom: 16px; font-size: 1.6rem; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }}
  .summary-card {{ padding: 12px 20px; border-radius: 8px; font-weight: 600; font-size: 1.1rem; }}
  .summary-card.high {{ background: #d4edda; color: #155724; }}
  .summary-card.medium {{ background: #fff3cd; color: #856404; }}
  .summary-card.low {{ background: #f8d7da; color: #721c24; }}
  .summary-card.total {{ background: #d1ecf1; color: #0c5460; }}
  #search {{ padding: 8px 12px; margin-bottom: 12px; width: 300px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th {{ background: #343a40; color: #fff; padding: 8px 10px; text-align: left; cursor: pointer; white-space: nowrap; user-select: none; }}
  th:hover {{ background: #495057; }}
  th .sort-arrow {{ margin-left: 4px; opacity: 0.5; }}
  th.sorted .sort-arrow {{ opacity: 1; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
  tr.high {{ background: #f0fff0; }}
  tr.medium {{ background: #fffef0; }}
  tr.low {{ background: #fff0f0; }}
  tr.unknown {{ background: #f5f5f5; }}
  tr:hover {{ filter: brightness(0.97); }}
  .session-bar {{ display: flex; height: 16px; width: 120px; border-radius: 3px; overflow: hidden; background: #eee; }}
  .session-bar .pre {{ background: #6c9bd2; }}
  .session-bar .reg {{ background: #2d6a4f; }}
  .session-bar .ah {{ background: #e07b53; }}
  .tier {{ padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }}
  .tier.high {{ background: #28a745; color: #fff; }}
  .tier.medium {{ background: #ffc107; color: #333; }}
  .tier.low {{ background: #dc3545; color: #fff; }}
  .tier.unknown {{ background: #6c757d; color: #fff; }}
  .decision-matrix {{ margin-top: 24px; padding: 16px; background: #fff; border-radius: 8px; border: 1px solid #ddd; }}
  .decision-matrix h2 {{ font-size: 1.1rem; margin-bottom: 8px; }}
  .decision-matrix table {{ font-size: 13px; }}
  .decision-matrix th {{ background: #6c757d; }}
  .legend {{ display: flex; gap: 16px; margin: 12px 0; font-size: 13px; }}
  .legend span {{ display: flex; align-items: center; gap: 4px; }}
  .legend-box {{ width: 14px; height: 14px; border-radius: 2px; display: inline-block; }}
  @media print {{
    body {{ margin: 0; font-size: 11px; }}
    #search {{ display: none; }}
    .summary-card {{ padding: 6px 12px; }}
    tr {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
  <h1>Volume Profile Report &mdash; {report_date}{days_label}</h1>

  <div class="summary">
    <div class="summary-card high">HIGH: {high}</div>
    <div class="summary-card medium">MEDIUM: {medium}</div>
    <div class="summary-card low">LOW: {low}</div>
    <div class="summary-card total">Total: {len(df)}</div>
  </div>

  <div class="legend">
    <span><span class="legend-box" style="background:#6c9bd2"></span> Pre-market</span>
    <span><span class="legend-box" style="background:#2d6a4f"></span> Regular</span>
    <span><span class="legend-box" style="background:#e07b53"></span> After-hours</span>
  </div>

  <input type="text" id="search" placeholder="Filter by ticker..." oninput="filterTable()">

  <table id="volume-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Ticker <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(1)">Lazer ID <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(2)">Close <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(3)">Pre Vol <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(4)">Pre $ <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(5)">Reg Vol <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(6)">Reg $ <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(7)">AH Vol <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(8)">AH $ <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(9)">Overnight Obs <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(10)">Total Vol <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(11)">Total $ <span class="sort-arrow">&#x25B4;</span></th>
        <th>Session Split</th>
        <th onclick="sortTable(13)" title="Pre-market price activity (yfinance only)">Pre Activity <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(14)" title="After-hours price activity (yfinance only)">AH Activity <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(15)">Tier <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(16)">Recommendation <span class="sort-arrow">&#x25B4;</span></th>
        <th onclick="sortTable(17)">Source <span class="sort-arrow">&#x25B4;</span></th>
      </tr>
    </thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>

  <div class="decision-matrix">
    <h2>Decision Matrix</h2>
    <table>
      <thead>
        <tr><th>Tier</th><th>Threshold</th><th>Meaning</th></tr>
      </thead>
      <tbody>
        <tr><td><span class="tier high">HIGH</span></td><td>&ge; $50M/day</td><td>Very liquid, institutional-grade</td></tr>
        <tr><td><span class="tier medium">MEDIUM</span></td><td>$5M &ndash; $50M</td><td>Moderately liquid</td></tr>
        <tr><td><span class="tier low">LOW</span></td><td>&lt; $5M</td><td>Thin liquidity</td></tr>
      </tbody>
    </table>
    <h2 style="margin-top:12px">Session Recommendations</h2>
    <table>
      <thead>
        <tr><th>Condition</th><th>Recommendation</th></tr>
      </thead>
      <tbody>
        <tr><td>HIGH + AH &gt; 1% + overnight obs &gt; 100</td><td>24/5 viable</td></tr>
        <tr><td>HIGH + AH &gt; 1%</td><td>Regular + Extended</td></tr>
        <tr><td>MEDIUM + AH &gt; 0.5%</td><td>Regular + Extended (review)</td></tr>
        <tr><td>Everything else</td><td>Regular only</td></tr>
      </tbody>
    </table>
  </div>

  <script>
    let sortCol = -1, sortAsc = true;
    function sortTable(col) {{
      const table = document.getElementById('volume-table');
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      if (sortCol === col) {{ sortAsc = !sortAsc; }} else {{ sortCol = col; sortAsc = true; }}
      rows.sort((a, b) => {{
        let av = a.cells[col].textContent.replace(/[$,%]/g, '').trim();
        let bv = b.cells[col].textContent.replace(/[$,%]/g, '').trim();
        let an = parseFloat(av.replace(/,/g, '')), bn = parseFloat(bv.replace(/,/g, ''));
        if (!isNaN(an) && !isNaN(bn)) return sortAsc ? an - bn : bn - an;
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }});
      rows.forEach(r => tbody.appendChild(r));
      table.querySelectorAll('th').forEach((h, i) => h.classList.toggle('sorted', i === col));
    }}
    function filterTable() {{
      const q = document.getElementById('search').value.toUpperCase();
      document.querySelectorAll('#volume-table tbody tr').forEach(r => {{
        r.style.display = r.cells[0].textContent.toUpperCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""
    return html


def print_summary(df: pd.DataFrame, date_str: str, unresolved: list[str]) -> None:
    """Print formatted console summary."""
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"  Volume Profile Summary — {date_str}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    tier_counts = df["liquidity_tier"].value_counts()
    for tier in ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        count = tier_counts.get(tier, 0)
        if count:
            print(f"  {tier:8s}: {count} tickers", file=sys.stderr)
    print(f"  {'TOTAL':8s}: {len(df)} tickers", file=sys.stderr)

    # Top 5 by dollar volume
    print(f"\n  Top 5 by daily dollar volume:", file=sys.stderr)
    for _, row in df.head(5).iterrows():
        dvol = row.get("total_dollar_vol", 0)
        if pd.notna(dvol):
            print(
                f"    {row['ticker']:8s}  ${dvol:>14,.0f}  [{row['liquidity_tier']}]",
                file=sys.stderr,
            )

    # Warnings
    missing_price = df[df["close_price"].isna()]
    if not missing_price.empty:
        print(
            f"\n  Warning: {len(missing_price)} tickers missing close price",
            file=sys.stderr,
        )
    if unresolved:
        print(
            f"  Note: {len(unresolved)} tickers via yfinance: {', '.join(unresolved)}",
            file=sys.stderr,
        )

    print(f"{'='*70}\n", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Volume profile analysis for US equities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 volume_profile.py --tickers AAPL,MSFT,NVDA --date 2026-03-03
  python3 volume_profile.py --ticker-file tickers.txt --date 2026-03-01 --days 5
  python3 volume_profile.py --tickers AAPL --date 2026-03-03 --output output_csv/vol.csv
""",
    )

    ticker_group = parser.add_mutually_exclusive_group(required=True)
    ticker_group.add_argument("--tickers", type=str, help="Comma-separated ticker list")
    ticker_group.add_argument(
        "--ticker-file", type=Path, help="File with one ticker per line"
    )

    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
        help="Reference date (default: yesterday)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        choices=range(1, 6),
        help="Trading days to average (1-5, default: 1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="CSV output path (default: output_csv/volume_profile_DATE.csv)",
    )

    args = parser.parse_args()
    tickers = parse_tickers(args)

    if not tickers:
        print("No tickers provided.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Volume profile: {len(tickers)} tickers, date={args.date}, days={args.days}",
        file=sys.stderr,
    )

    config = load_config()
    client_lazer = get_lazer_client(config)
    client_analytics = get_analytics_client(config)

    resolved = resolve_tickers(client_lazer, tickers)
    unresolved = [t for t in tickers if t not in resolved]

    print(
        f"Resolved {len(resolved)}/{len(tickers)} tickers to Lazer feeds",
        file=sys.stderr,
    )
    if unresolved:
        print(
            f"  Unresolved (yfinance fallback): {', '.join(unresolved)}",
            file=sys.stderr,
        )

    feed_ids = [v["pyth_lazer_id"] for v in resolved.values()]

    # Fetch data (multi-day or single-day)
    dates = get_trading_dates(args.date, args.days)
    all_dfs = []

    for d in dates:
        print(f"  Fetching {d}...", file=sys.stderr)
        datascope_rows = (
            fetch_session_volume(client_analytics, feed_ids, d) if feed_ids else []
        )
        close_prices = (
            fetch_close_prices(client_analytics, feed_ids, d) if feed_ids else {}
        )
        overnight_obs = (
            fetch_overnight_obs(client_lazer, feed_ids, d) if feed_ids else {}
        )
        yf_rows = fetch_yfinance_volume(unresolved, d)
        day_df = build_volume_dataframe(
            resolved, datascope_rows, close_prices, yf_rows, overnight_obs
        )
        if not day_df.empty:
            day_df["date"] = d.isoformat()
            all_dfs.append(day_df)

    if not all_dfs:
        print("No data found for any date. Exiting.", file=sys.stderr)
        sys.exit(1)

    if args.days == 1:
        df = all_dfs[0]
        df["date"] = args.date.isoformat()
    else:
        combined = pd.concat(all_dfs, ignore_index=True)
        numeric_cols = [
            c
            for c in combined.columns
            if c.endswith(("_vol", "_dollar_vol", "_pct", "_obs"))
        ]
        df = combined.groupby("ticker", as_index=False).agg(
            {
                **{c: "mean" for c in numeric_cols},
                "pyth_lazer_id": "first",
                "ric": "first",
                "close_price": "mean",
                "data_source": "first",
            }
        )
        df["days_sampled"] = args.days
        df["date"] = args.date.isoformat()
        # Re-classify after averaging
        df["liquidity_tier"] = df["total_dollar_vol"].apply(classify_tier)
        df["session_recommendation"] = df.apply(classify_recommendation, axis=1)
        df = df.sort_values("total_dollar_vol", ascending=False).reset_index(drop=True)

    # CSV output
    output_path = args.output or Path(f"output_csv/volume_profile_{args.date}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"\nCSV written to {output_path}", file=sys.stderr)

    # HTML report
    html_path = output_path.with_suffix(".html")
    html_content = render_html_report(df, args.date.isoformat(), args.days)
    html_path.write_text(html_content)
    print(f"HTML report written to {html_path}", file=sys.stderr)

    # Console summary
    print_summary(df, args.date.isoformat(), unresolved)


if __name__ == "__main__":
    main()
