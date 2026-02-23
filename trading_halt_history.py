#!/usr/bin/env python3
"""
LULD Trading Halt History Downloader

Downloads Limit Up-Limit Down (LULD) trading halt data from two sources:
  1. NASDAQ Trader RSS feed (NASDAQ-listed securities only)
  2. NYSE Historical Halt API (all US exchanges)

Cross-references both sources on NASDAQ-listed halts to validate data agreement.

Data sources:
  - https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts
  - https://www.nyse.com/api/trade-halts/historical/download
"""

import argparse
import csv
import io
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- Constants ---

RSS_URL_TEMPLATE = (
    "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={date}"
)
NYSE_API_URL = "https://www.nyse.com/api/trade-halts/historical/download"
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds, doubles each retry

EXCHANGE_NAME_TO_CODE = {
    "Nasdaq": "Q",
    "NYSE": "N",
    "NYSE American": "A",
    "NYSE Arca": "P",
    "Cboe BZX": "Z",
}
EXCHANGE_CODE_TO_NAME = {v: k for k, v in EXCHANGE_NAME_TO_CODE.items()}


# --- Data classes ---


@dataclass
class CrossRefResult:
    """Result of cross-referencing NASDAQ RSS and NYSE API halts."""

    matched: list[dict] = field(default_factory=list)
    nasdaq_only: list[dict] = field(default_factory=list)
    nyse_only: list[dict] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        return len(self.matched)

    @property
    def nasdaq_only_count(self) -> int:
        return len(self.nasdaq_only)

    @property
    def nyse_only_count(self) -> int:
        return len(self.nyse_only)

    @property
    def total(self) -> int:
        return self.matched_count + self.nasdaq_only_count + self.nyse_only_count

    @property
    def agreement_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.matched_count / self.total * 100


# --- NASDAQ RSS functions ---


def fetch_halts_for_date(
    date: datetime, delay: float, retries: int = MAX_RETRIES
) -> list[dict]:
    """Fetch trading halts for a single date from the NASDAQ Trader RSS feed."""
    date_str = date.strftime("%m%d%Y")
    url = RSS_URL_TEMPLATE.format(date=date_str)

    for attempt in range(1, retries + 1):
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")
            break
        except Exception as exc:
            if attempt == retries:
                log.warning(
                    "Failed to fetch %s after %d attempts: %s", date_str, retries, exc
                )
                return []
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            log.debug(
                "Retry %d/%d for %s in %.1fs: %s", attempt, retries, date_str, wait, exc
            )
            time.sleep(wait)

    halts = []
    for entry in feed.entries:
        fields = _parse_entry(entry)
        if not fields:
            continue

        reason = fields.get("reason_code", "").strip()
        if reason != "LUDP":
            continue

        halts.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "ticker": fields.get("ticker", "").strip(),
                "halt_time": fields.get("halt_time", "").strip(),
                "resume_time": fields.get("resume_time", "").strip(),
                "market": fields.get("market", "").strip(),
                "source": "nasdaq_rss",
            }
        )

    if delay > 0:
        time.sleep(delay)

    return halts


def _parse_entry(entry: dict) -> Optional[dict]:
    """Parse a single RSS feed entry into structured fields.

    The NASDAQ Trader RSS feed entries have a summary containing an HTML table:
      [0]=IssueSymbol, [1]=IssueName, [2]=Market, [3]=ReasonCode,
      [4]=PauseThresholdPrice, [5]=HaltDate, [6]=HaltTime,
      [7]=ResumptionDate, [8]=ResumptionQuoteTime, [9]=ResumptionTradeTime
    """
    import re

    summary = entry.get("summary", "")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", summary, re.IGNORECASE | re.DOTALL)

    if len(cells) < 7:
        return None

    return {
        "ticker": _strip_html(cells[0]),
        "halt_time": _strip_html(cells[6]),
        "resume_time": _strip_html(cells[9]) if len(cells) > 9 else "",
        "reason_code": _strip_html(cells[3]),
        "market": _strip_html(cells[2]),
    }


def _strip_html(text: str) -> str:
    """Remove any remaining HTML tags from text."""
    import re

    return re.sub(r"<[^>]+>", "", text).strip()


def fetch_nasdaq_rss_halts(
    start_date: datetime, end_date: datetime, delay: float
) -> list[dict]:
    """Fetch all LUDP halts from the NASDAQ RSS feed for a date range."""
    bdays = pd.bdate_range(start=start_date, end=end_date)
    log.info(
        "Fetching NASDAQ RSS halts from %s to %s (%d business days)",
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        len(bdays),
    )

    all_halts: list[dict] = []
    for i, day in enumerate(bdays):
        day_dt = day.to_pydatetime()
        halts = fetch_halts_for_date(day_dt, delay=delay)
        all_halts.extend(halts)

        if (i + 1) % 10 == 0 or (i + 1) == len(bdays):
            log.info(
                "NASDAQ RSS progress: %d/%d days (%d halts so far)",
                i + 1,
                len(bdays),
                len(all_halts),
            )

    return all_halts


# --- NYSE API functions ---


def fetch_halts_from_nyse(
    start_date: datetime, end_date: datetime, retries: int = MAX_RETRIES
) -> list[dict]:
    """Fetch LULD halts from the NYSE historical halt API.

    Returns all LULD halts across all US exchanges (Nasdaq, NYSE, NYSE American,
    NYSE Arca, Cboe BZX) in a single request.
    """
    params = {
        "reason": "LULD pause",
        "haltDateFrom": start_date.strftime("%Y-%m-%d"),
        "haltDateTo": end_date.strftime("%Y-%m-%d"),
    }
    url = f"{NYSE_API_URL}?{urllib.parse.urlencode(params)}"

    log.info(
        "Fetching NYSE API halts from %s to %s",
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "trading-halt-history/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            break
        except Exception as exc:
            if attempt == retries:
                log.error(
                    "Failed to fetch NYSE API after %d attempts: %s", retries, exc
                )
                return []
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            log.warning(
                "NYSE API retry %d/%d in %.1fs: %s", attempt, retries, wait, exc
            )
            time.sleep(wait)

    halts = []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        reason = row.get("Reason", "").strip()
        if reason != "LULD pause":
            continue

        exchange_name = row.get("Exchange", "").strip()
        market_code = EXCHANGE_NAME_TO_CODE.get(exchange_name, "?")

        halt_date = row.get("Halt Date", "").strip()
        if not halt_date:
            continue

        halts.append(
            {
                "date": halt_date,
                "ticker": row.get("Symbol", "").strip(),
                "halt_time": row.get("Halt Time", "").strip(),
                "resume_time": row.get("NYSE Resume Time", "").strip(),
                "market": market_code,
                "source": "nyse",
            }
        )

    log.info("NYSE API returned %d LULD halts", len(halts))
    return halts


# --- Cross-reference ---


def _time_to_seconds(t: str) -> Optional[int]:
    """Convert HH:MM:SS (or HH:MM:SS.fff) string to seconds since midnight."""
    parts = t.split(":")
    if len(parts) != 3:
        return None
    try:
        secs = int(float(parts[2]))
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + secs
    except ValueError:
        return None


def cross_reference_halts(
    rss_halts: list[dict], nyse_halts: list[dict], time_tolerance: int = 5
) -> CrossRefResult:
    """Cross-reference NASDAQ RSS halts against NYSE API halts (Nasdaq-listed only).

    Only compares NYSE API records where market == "Q" (Nasdaq) against RSS records.
    Matching is by (date, ticker) with halt_time within time_tolerance seconds.
    """
    # Filter NYSE halts to Nasdaq-listed only and assign stable indices
    nyse_nasdaq = [h for h in nyse_halts if h["market"] == "Q"]

    # Index NYSE-Nasdaq halts by (date, ticker) -> list of (index, halt)
    nyse_index: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for i, h in enumerate(nyse_nasdaq):
        key = (h["date"], h["ticker"])
        nyse_index.setdefault(key, []).append((i, h))

    # Track which NYSE halts have been matched by stable index
    matched_indices: set[int] = set()

    result = CrossRefResult()

    for rss_halt in rss_halts:
        key = (rss_halt["date"], rss_halt["ticker"])
        candidates = nyse_index.get(key, [])

        rss_time = _time_to_seconds(rss_halt["halt_time"])
        best_match = None
        best_diff = float("inf")
        best_idx = -1

        for idx, cand in candidates:
            if idx in matched_indices:
                continue
            cand_time = _time_to_seconds(cand["halt_time"])
            if rss_time is None or cand_time is None:
                continue
            diff = abs(rss_time - cand_time)
            if diff <= time_tolerance and diff < best_diff:
                best_match = cand
                best_diff = diff
                best_idx = idx

        if best_match is not None:
            matched_indices.add(best_idx)
            result.matched.append(
                {
                    "date": rss_halt["date"],
                    "ticker": rss_halt["ticker"],
                    "rss_halt_time": rss_halt["halt_time"],
                    "nyse_halt_time": best_match["halt_time"],
                    "rss_resume_time": rss_halt["resume_time"],
                    "nyse_resume_time": best_match["resume_time"],
                    "time_diff_sec": int(best_diff),
                    "status": "matched",
                }
            )
        else:
            result.nasdaq_only.append(
                {
                    "date": rss_halt["date"],
                    "ticker": rss_halt["ticker"],
                    "rss_halt_time": rss_halt["halt_time"],
                    "nyse_halt_time": "",
                    "rss_resume_time": rss_halt["resume_time"],
                    "nyse_resume_time": "",
                    "time_diff_sec": "",
                    "status": "nasdaq_only",
                }
            )

    # Remaining unmatched NYSE-Nasdaq halts
    for i, h in enumerate(nyse_nasdaq):
        if i not in matched_indices:
            result.nyse_only.append(
                {
                    "date": h["date"],
                    "ticker": h["ticker"],
                    "rss_halt_time": "",
                    "nyse_halt_time": h["halt_time"],
                    "rss_resume_time": "",
                    "nyse_resume_time": h["resume_time"],
                    "time_diff_sec": "",
                    "status": "nyse_only",
                }
            )

    return result


# --- Merge ---


def merge_halts(
    rss_halts: list[dict],
    nyse_halts: list[dict],
    xref: Optional[CrossRefResult],
) -> list[dict]:
    """Merge halts from both sources into a single deduplicated list.

    - Matched halts -> source="both"
    - NASDAQ-only halts -> source="nasdaq_rss"
    - NYSE-only Nasdaq halts -> source="nyse"
    - All non-Nasdaq NYSE halts -> source="nyse"
    """
    merged: list[dict] = []
    dedup: set[tuple[str, str, str, str]] = set()

    def _add(halt: dict) -> None:
        key = (halt["date"], halt["ticker"], halt["halt_time"], halt["market"])
        if key not in dedup:
            dedup.add(key)
            merged.append(halt)

    if xref is not None:
        # Matched halts from cross-reference (prefer RSS data with source="both")
        # Build a lookup from RSS halts for full record
        rss_lookup: dict[tuple[str, str, str], dict] = {}
        for h in rss_halts:
            rss_lookup[(h["date"], h["ticker"], h["halt_time"])] = h

        for m in xref.matched:
            rss_key = (m["date"], m["ticker"], m["rss_halt_time"])
            rss_rec = rss_lookup.get(rss_key)
            if rss_rec:
                _add({**rss_rec, "source": "both"})

        # NASDAQ-only
        for n in xref.nasdaq_only:
            rss_key = (n["date"], n["ticker"], n["rss_halt_time"])
            rss_rec = rss_lookup.get(rss_key)
            if rss_rec:
                _add({**rss_rec, "source": "nasdaq_rss"})

        # NYSE-only Nasdaq halts
        for n in xref.nyse_only:
            _add(
                {
                    "date": n["date"],
                    "ticker": n["ticker"],
                    "halt_time": n["nyse_halt_time"],
                    "resume_time": n["nyse_resume_time"],
                    "market": "Q",
                    "source": "nyse",
                }
            )

        # All non-Nasdaq NYSE halts
        for h in nyse_halts:
            if h["market"] != "Q":
                _add(h)
    else:
        # No cross-reference: just combine both lists
        for h in rss_halts:
            _add(h)
        for h in nyse_halts:
            _add(h)

    return merged


# --- Reporting ---


def _print_cross_reference_report(xref: CrossRefResult) -> None:
    """Print cross-reference analysis between NASDAQ RSS and NYSE API."""
    print(f"\n{'='*60}")
    print("CROSS-REFERENCE REPORT (Nasdaq-Listed Only)")
    print(f"{'='*60}")
    print(f"Matched (both sources):  {xref.matched_count:>6,}")
    print(f"NASDAQ RSS only:         {xref.nasdaq_only_count:>6,}")
    print(f"NYSE API only:           {xref.nyse_only_count:>6,}")
    print(f"Total unique halts:      {xref.total:>6,}")
    print(f"Agreement rate:          {xref.agreement_rate:>6.1f}%")

    if xref.matched:
        diffs = [
            m["time_diff_sec"]
            for m in xref.matched
            if isinstance(m["time_diff_sec"], int)
        ]
        if diffs:
            print(f"\nTime differences (matched halts):")
            print(f"  Exact match (0s):  {sum(1 for d in diffs if d == 0):,}")
            print(f"  Within 1s:         {sum(1 for d in diffs if d <= 1):,}")
            print(f"  Within 5s:         {sum(1 for d in diffs if d <= 5):,}")
            print(f"  Max diff:          {max(diffs)}s")

    if xref.nasdaq_only:
        print(f"\nNASDAQ-only examples (first 10):")
        for m in xref.nasdaq_only[:10]:
            print(f"  {m['date']} {m['ticker']:<10s} halt={m['rss_halt_time']}")

    if xref.nyse_only:
        print(f"\nNYSE-only examples (first 10):")
        for m in xref.nyse_only[:10]:
            print(f"  {m['date']} {m['ticker']:<10s} halt={m['nyse_halt_time']}")

    print(f"{'='*60}")


def _print_summary(halts: list[dict]) -> None:
    """Print summary statistics about the downloaded halts."""
    if not halts:
        print("\nNo LULD halts found in the date range.")
        return

    tickers = [h["ticker"] for h in halts]
    dates = [h["date"] for h in halts]
    unique_tickers = sorted(set(tickers))

    # Count halts per ticker
    ticker_counts: dict[str, int] = {}
    for t in tickers:
        ticker_counts[t] = ticker_counts.get(t, 0) + 1

    top_tickers = sorted(ticker_counts.items(), key=lambda x: -x[1])[:20]

    print(f"\n{'='*60}")
    print("LULD TRADING HALT SUMMARY")
    print(f"{'='*60}")
    print(f"Total LULD halts:    {len(halts):,}")
    print(f"Unique tickers:      {len(unique_tickers):,}")
    print(f"Date range:          {min(dates)} to {max(dates)}")
    print(f"Days with halts:     {len(set(dates)):,}")

    # Exchange breakdown
    exchange_counts: dict[str, int] = {}
    for h in halts:
        code = h.get("market", "?")
        name = EXCHANGE_CODE_TO_NAME.get(code, code)
        exchange_counts[name] = exchange_counts.get(name, 0) + 1
    if exchange_counts:
        print(f"\nBy exchange:")
        for name, count in sorted(exchange_counts.items(), key=lambda x: -x[1]):
            pct = count / len(halts) * 100
            print(f"  {name:<16s} {count:>6,}  ({pct:.1f}%)")

    # Source breakdown
    source_counts: dict[str, int] = {}
    for h in halts:
        src = h.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        print(f"\nBy source:")
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            pct = count / len(halts) * 100
            print(f"  {src:<16s} {count:>6,}  ({pct:.1f}%)")

    print(f"\nTop 20 most-halted tickers:")
    for ticker, count in top_tickers:
        print(f"  {ticker:<10s} {count:>5,} halts")
    print(f"{'='*60}")


def _write_xref_csv(xref: CrossRefResult, path: str) -> None:
    """Write cross-reference detail to a CSV file."""
    fieldnames = [
        "date",
        "ticker",
        "rss_halt_time",
        "nyse_halt_time",
        "rss_resume_time",
        "nyse_resume_time",
        "time_diff_sec",
        "status",
    ]
    all_rows = xref.matched + xref.nasdaq_only + xref.nyse_only
    all_rows.sort(key=lambda r: (r["date"], r["ticker"]))

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    log.info("Wrote %d cross-reference rows to %s", len(all_rows), path)


# --- Main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download LULD trading halt history from NASDAQ RSS and NYSE API."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Number of calendar days to look back (default: 365)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="ludp_halts.csv",
        help="Output CSV file path (default: ludp_halts.csv)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between NASDAQ RSS requests in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--no-nyse",
        action="store_true",
        help="Skip NYSE API (original RSS-only behavior)",
    )
    parser.add_argument(
        "--no-nasdaq-rss",
        action="store_true",
        help="Skip NASDAQ RSS (NYSE API only)",
    )
    parser.add_argument(
        "--xref-output",
        type=str,
        default=None,
        help="Path for cross-reference detail CSV",
    )
    parser.add_argument(
        "--time-tolerance",
        type=int,
        default=5,
        help="Max seconds for halt time matching in cross-reference (default: 5)",
    )
    args = parser.parse_args()

    if args.no_nyse and args.no_nasdaq_rss:
        log.error(
            "Cannot skip both sources. Use --no-nyse OR --no-nasdaq-rss, not both."
        )
        return

    if args.days <= 0:
        log.error("--days must be a positive integer, got %d", args.days)
        return

    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)

    # Fetch from NASDAQ RSS
    rss_halts: list[dict] = []
    if not args.no_nasdaq_rss:
        rss_halts = fetch_nasdaq_rss_halts(start_date, end_date, delay=args.delay)

    # Fetch from NYSE API
    nyse_halts: list[dict] = []
    if not args.no_nyse:
        nyse_halts = fetch_halts_from_nyse(start_date, end_date)

    # Cross-reference (only if both sources present)
    xref: Optional[CrossRefResult] = None
    if rss_halts and nyse_halts:
        xref = cross_reference_halts(
            rss_halts, nyse_halts, time_tolerance=args.time_tolerance
        )

    # Merge halts
    all_halts = merge_halts(rss_halts, nyse_halts, xref)

    # Sort by date ascending, then halt_time ascending
    all_halts.sort(key=lambda h: (h["date"], h["halt_time"]))

    # Write output CSV
    fieldnames = ["date", "ticker", "halt_time", "resume_time", "market", "source"]
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_halts)

    log.info("Wrote %d LULD halts to %s", len(all_halts), args.output)

    # Write cross-reference CSV
    if xref and args.xref_output:
        _write_xref_csv(xref, args.xref_output)

    # Print summary
    _print_summary(all_halts)

    # Print cross-reference report
    if xref:
        _print_cross_reference_report(xref)


if __name__ == "__main__":
    main()
