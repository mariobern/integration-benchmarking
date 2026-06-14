#!/usr/bin/env python3
"""Extract equity overnight candidates from a Lazer config.

Selects feeds in a symbol namespace (default `Equity.US.`, override with
`--symbol-prefix` e.g. `Equity.HK.`) that are STABLE-without-overnight or
COMING_SOON (with or without overnight), writing a ticker list for
volume_profile.py and a metadata side-file (ticker, feedId, state,
overnight_configured) for ranking.

See docs/superpowers/specs/2026-06-12-overnight-candidates-design.md.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

US_EQUITY_PREFIX = "Equity.US."
OVERNIGHT_SESSION = "OVER_NIGHT"
META_FIELDS = ["ticker", "feedId", "state", "overnight_configured"]


def has_overnight_session(feed: dict) -> bool:
    """True iff any market schedule entry is an OVER_NIGHT session."""
    return any(
        ms.get("session") == OVERNIGHT_SESSION for ms in feed.get("marketSchedules", [])
    )


def extract_ticker(symbol: str, prefix: str = US_EQUITY_PREFIX) -> str:
    """'Equity.US.AAPL/USD' -> 'AAPL' (handles dotted tickers like BRK.B).

    Strips the asset-class `prefix` and the quote-currency suffix, so it works
    for any equity namespace (e.g. 'Equity.HK.0002/HKD' -> '0002'). Uppercased
    to match volume_profile.py, which uppercases ticker-file input; keeping the
    case aligned guarantees the downstream join key matches.
    """
    return symbol[len(prefix) :].split("/")[0].upper()


def is_candidate(feed: dict, prefix: str = US_EQUITY_PREFIX) -> bool:
    """Include COMING_SOON (any), or STABLE without an overnight session.

    Only feeds whose symbol starts with `prefix` are considered.
    """
    if not feed.get("symbol", "").startswith(prefix):
        return False
    state = feed.get("state")
    if state == "COMING_SOON":
        return True
    if state == "STABLE" and not has_overnight_session(feed):
        return True
    return False


def build_candidates(feeds: list[dict], prefix: str = US_EQUITY_PREFIX) -> list[dict]:
    """Return candidate rows (for the given symbol `prefix`) sorted by ticker."""
    rows = [
        {
            "ticker": extract_ticker(f["symbol"], prefix),
            "feedId": f["feedId"],
            "state": f["state"],
            "overnight_configured": has_overnight_session(f),
        }
        for f in feeds
        if is_candidate(f, prefix)
    ]
    rows.sort(key=lambda r: r["ticker"])
    return rows


def load_feeds(config_path: Path) -> list[dict]:
    with open(config_path) as f:
        return json.load(f)["feeds"]


def write_tickers(rows: list[dict], path: Path) -> None:
    path.write_text("\n".join(r["ticker"] for r in rows) + "\n")


def write_meta(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=META_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in META_FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("lazer_test.json"))
    parser.add_argument(
        "--symbol-prefix",
        default=US_EQUITY_PREFIX,
        help=(
            "Symbol namespace to extract, e.g. 'Equity.US.' (default) or "
            "'Equity.HK.' for Hong Kong equities."
        ),
    )
    parser.add_argument(
        "--tickers-out", type=Path, default=Path("overnight_candidates_tickers.txt")
    )
    parser.add_argument(
        "--meta-out", type=Path, default=Path("overnight_candidates_meta.csv")
    )
    args = parser.parse_args()

    feeds = load_feeds(args.config)
    rows = build_candidates(feeds, args.symbol_prefix)
    write_tickers(rows, args.tickers_out)
    write_meta(rows, args.meta_out)

    net_new = sum(1 for r in rows if not r["overnight_configured"])
    configured = len(rows) - net_new
    print(
        f"{len(rows)} candidates "
        f"({net_new} net-new, {configured} already-configured) "
        f"-> {args.tickers_out}, {args.meta_out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
