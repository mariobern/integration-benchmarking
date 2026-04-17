#!/usr/bin/env python3
"""
One-off analysis: compare hit_rate thresholds (95% vs 90%) for extended hours.

Reads feeds from source_upload_15_Jan.csv, queries ClickHouse for premarket
and afterhours metrics per publisher, and shows which combos flip FAIL->PASS
when lowering the hit_rate threshold from 95% to 90% (for nrmse <= 0.05).
"""

import csv
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import clickhouse_connect
import yaml

# --- Constants ---
DATE = "2026-01-15"
MODE = "us-equities"
CSV_PATH = Path("source_upload_15_Jan.csv")
MIN_OBSERVATIONS = 50

# US Equities session hours (ET)
PREMARKET_START_H, PREMARKET_START_M = 4, 0
MARKET_OPEN_H, MARKET_OPEN_M = 9, 30
MARKET_CLOSE_H, MARKET_CLOSE_M = 16, 0
AFTERHOURS_END_H, AFTERHOURS_END_M = 20, 0


@dataclass
class SessionMetrics:
    """Raw metrics for one publisher in one session."""

    feed_id: int
    ticker: str
    session: str
    publisher_id: int
    n_observations: int
    nrmse: float | None
    hit_rate: float | None
    pass_at_95: bool
    pass_at_90: bool
    error: str | None = None


def load_config() -> dict:
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("ERROR: config.yaml not found", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_clients(config: dict):
    lazer_cfg = config["lazer_clickhouse_prod"]
    analytics_cfg = config["analytics_clickhouse"]
    kwargs = dict(secure=True, connect_timeout=60, send_receive_timeout=300)

    client_lazer = clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        **kwargs,
    )
    client_analytics = clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        **kwargs,
    )
    return client_lazer, client_analytics


def read_feeds(csv_path: Path) -> list[tuple[int, str]]:
    """Read (feed_id, ticker) pairs from source_upload CSV."""
    feeds = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip():
                continue
            feed_id = int(row[4].strip())
            ticker = row[7].strip()
            feeds.append((feed_id, ticker))
    return feeds


def get_session_filter_sql(
    session: str, date: str, column: str
) -> str:
    """Generate UTC time filter for premarket or afterhours."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    if session == "premarket":
        start = dt.replace(hour=PREMARKET_START_H, minute=PREMARKET_START_M, tzinfo=est)
        end = dt.replace(hour=MARKET_OPEN_H, minute=MARKET_OPEN_M, tzinfo=est)
    elif session == "afterhours":
        start = dt.replace(hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M, tzinfo=est)
        end = dt.replace(hour=AFTERHOURS_END_H, minute=AFTERHOURS_END_M, tzinfo=est)
    else:
        return ""

    start_utc = start.astimezone(utc)
    end_utc = end.astimezone(utc)
    return (
        f"AND {column} >= '{start_utc.strftime('%Y-%m-%d %H:%M:%S')}' "
        f"AND {column} < '{end_utc.strftime('%Y-%m-%d %H:%M:%S')}'"
    )


def get_feed_divisor(client_lazer, feed_id: int) -> tuple[str | None, float | None]:
    """Get symbol and divisor for a feed."""
    query = f"""
        SELECT symbol, exponent
        FROM feeds_metadata_latest FINAL
        WHERE pyth_lazer_id = {feed_id} AND exponent IS NOT NULL
        ORDER BY updated_at DESC LIMIT 1
    """
    result = client_lazer.query(query)
    if result.result_rows:
        symbol, exponent = result.result_rows[0]
        return symbol, 10 ** abs(exponent)
    return None, None


def evaluate_session(
    client_lazer,
    client_analytics,
    feed_id: int,
    ticker: str,
    date: str,
    session: str,
    divisor: float,
) -> list[SessionMetrics]:
    """Query one session for all publishers, return metrics with dual threshold."""

    pub_filter = get_session_filter_sql(session, date, "publish_time")
    bench_filter = get_session_filter_sql(session, date, "date_time")

    pub_query = f"""
        SELECT publisher_id, toStartOfSecond(publish_time) AS ts_second,
               avg(price) / {divisor} AS avg_price, count() AS cnt
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND toDate(publish_time) = '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL {pub_filter}
        GROUP BY publisher_id, ts_second
        ORDER BY publisher_id, ts_second
    """

    bench_query = f"""
        SELECT toStartOfSecond(date_time) AS ts_second,
               avg(COALESCE(price, (bid_price + ask_price) / 2)) AS avg_price,
               avg(CASE WHEN ask_price IS NOT NULL AND bid_price IS NOT NULL
                        THEN ask_price - bid_price ELSE NULL END) AS avg_spread
        FROM datascope_global_equities_benchmark_data
        WHERE toDate(date_time) = '{date}'
          AND pyth_lazer_id = {feed_id}
          AND (bid_price IS NOT NULL AND ask_price IS NOT NULL OR price IS NOT NULL)
          {bench_filter}
        GROUP BY ts_second ORDER BY ts_second
    """

    pub_result = client_lazer.query(pub_query)
    if not pub_result.result_rows:
        return []

    all_pubs = sorted({row[0] for row in pub_result.result_rows})

    bench_result = client_analytics.query(bench_query)
    if not bench_result.result_rows:
        return [
            SessionMetrics(
                feed_id=feed_id, ticker=ticker, session=session,
                publisher_id=p, n_observations=0, nrmse=None, hit_rate=None,
                pass_at_95=False, pass_at_90=False,
                error="No benchmark data",
            )
            for p in all_pubs
        ]

    bench_by_ts = {
        row[0]: (row[1], row[2]) for row in bench_result.result_rows if row[1] is not None
    }

    # Accumulate per-publisher
    pub_metrics: dict[int, dict] = {
        p: {"sq_err": [], "pct_diffs": [], "bench_prices": []} for p in all_pubs
    }
    for pub_id, ts, pub_price, _ in pub_result.result_rows:
        if ts not in bench_by_ts:
            continue
        bench_price, _ = bench_by_ts[ts]
        diff = pub_price - bench_price
        pct_diff = abs(diff / bench_price) * 100 if bench_price else 0
        m = pub_metrics[pub_id]
        m["sq_err"].append(diff**2)
        m["pct_diffs"].append(pct_diff)
        m["bench_prices"].append(bench_price)

    results = []
    for pub_id in all_pubs:
        m = pub_metrics[pub_id]
        n = len(m["sq_err"])

        if n < MIN_OBSERVATIONS:
            err = (
                "No matched observations"
                if n == 0
                else f"Insufficient observations ({n} < {MIN_OBSERVATIONS})"
            )
            results.append(
                SessionMetrics(
                    feed_id=feed_id, ticker=ticker, session=session,
                    publisher_id=pub_id, n_observations=n,
                    nrmse=None, hit_rate=None,
                    pass_at_95=False, pass_at_90=False, error=err,
                )
            )
            continue

        rmse = (sum(m["sq_err"]) / n) ** 0.5
        bench_range = max(m["bench_prices"]) - min(m["bench_prices"])
        nrmse = rmse / bench_range if bench_range > 0 else None
        hits = sum(1 for p in m["pct_diffs"] if p <= 0.1)
        hit_rate = (hits / n) * 100

        if nrmse is not None:
            pass_95 = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 95)
            pass_90 = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 90)
        else:
            pass_95 = False
            pass_90 = False

        results.append(
            SessionMetrics(
                feed_id=feed_id, ticker=ticker, session=session,
                publisher_id=pub_id, n_observations=n,
                nrmse=nrmse, hit_rate=hit_rate,
                pass_at_95=pass_95, pass_at_90=pass_90,
            )
        )

    return results


def main():
    print("=" * 72)
    print("Hit Rate Threshold Analysis: 95% vs 90%")
    print(f"Date: {DATE} | Sessions: premarket, afterhours")
    print(f"Criteria: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= threshold)")
    print("=" * 72)

    config = load_config()
    client_lazer, client_analytics = get_clients(config)

    feeds = read_feeds(CSV_PATH)
    print(f"\nFeeds to analyze: {len(feeds)}")
    for fid, ticker in feeds:
        print(f"  {fid}: {ticker}")

    all_metrics: list[SessionMetrics] = []

    for feed_id, ticker in feeds:
        symbol, divisor = get_feed_divisor(client_lazer, feed_id)
        if divisor is None:
            print(f"\n  WARNING: No metadata for feed {feed_id} ({ticker}), skipping")
            continue

        for session in ("premarket", "afterhours"):
            print(f"\n  Querying {ticker} ({feed_id}) - {session}...", end=" ", flush=True)
            start = time.time()
            metrics = evaluate_session(
                client_lazer, client_analytics,
                feed_id, ticker, DATE, session, divisor,
            )
            elapsed = time.time() - start
            print(f"{len(metrics)} publishers ({elapsed:.1f}s)")
            all_metrics.extend(metrics)

    # --- Print detailed table ---
    print("\n" + "=" * 72)
    print(f"{'Ticker':<8} {'Session':<12} {'Pub':>5} {'nObs':>6} "
          f"{'nrmse':>8} {'hit_rate':>9} {'@95%':>6} {'@90%':>6} {'Flip?':>6}")
    print("-" * 72)

    flipped = []
    total_evaluated = 0
    total_pass_95 = 0
    total_pass_90 = 0
    premarket_flips = 0
    afterhours_flips = 0

    for m in sorted(all_metrics, key=lambda x: (x.ticker, x.session, x.publisher_id)):
        if m.error:
            print(f"{m.ticker:<8} {m.session:<12} {m.publisher_id:>5} "
                  f"{m.n_observations:>6} {'--':>8} {'--':>9} "
                  f"{'FAIL':>6} {'FAIL':>6} {'ERR':>6}  ({m.error})")
            continue

        total_evaluated += 1
        if m.pass_at_95:
            total_pass_95 += 1
        if m.pass_at_90:
            total_pass_90 += 1

        did_flip = not m.pass_at_95 and m.pass_at_90
        if did_flip:
            flipped.append(m)
            if m.session == "premarket":
                premarket_flips += 1
            else:
                afterhours_flips += 1

        nrmse_str = f"{m.nrmse:.5f}" if m.nrmse is not None else "--"
        hr_str = f"{m.hit_rate:.1f}%" if m.hit_rate is not None else "--"
        p95 = "PASS" if m.pass_at_95 else "FAIL"
        p90 = "PASS" if m.pass_at_90 else "FAIL"
        flip_str = "<<YES" if did_flip else ""

        print(f"{m.ticker:<8} {m.session:<12} {m.publisher_id:>5} "
              f"{m.n_observations:>6} {nrmse_str:>8} {hr_str:>9} "
              f"{p95:>6} {p90:>6} {flip_str:>6}")

    # --- Summary ---
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"Total publisher-session combos evaluated: {total_evaluated}")
    print(f"Pass @95%: {total_pass_95}")
    print(f"Pass @90%: {total_pass_90}")
    print(f"Flipped FAIL->PASS: {len(flipped)} "
          f"(premarket: {premarket_flips}, afterhours: {afterhours_flips})")

    if flipped:
        print("\nFlipped publishers:")
        for m in flipped:
            print(f"  {m.ticker} ({m.feed_id}) | {m.session} | pub {m.publisher_id} "
                  f"| nrmse={m.nrmse:.5f} | hit_rate={m.hit_rate:.1f}%")


if __name__ == "__main__":
    main()
