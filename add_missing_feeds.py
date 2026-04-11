#!/usr/bin/env python3
"""Add feeds from after.json that are missing from Price_Feeds_KPIs.csv."""

import csv
import json
from collections import Counter

ASSET_MAP = {
    "crypto": "Crypto",
    "equity": "Equity",
    "fx": "FX",
    "metal": "Metal",
    "commodity": "Commodities",
    "rates": "Rates",
    "crypto-redemption-rate": "Crypto Redemption Rate",
    "crypto-index": "Crypto Index",
    "nav": "Crypto NAV",
    "funding-rate": "Funding Rate",
    "kalshi": "Kalshi",
    "custom": "ECO",
}

STATE_MAP = {
    "STABLE": "active",
    "COMING_SOON": "inactive",
    "INACTIVE": "inactive",
}


def extract_feed_name(symbol, asset_type):
    """Extract display name from after.json symbol.

    Examples:
        Crypto.BTC/USD -> BTC/USD
        Equity.US.AAPL/USD -> AAPL/USD
        Crypto.ALP/USD.RR -> ALP/USD
        FundingRate.Deribit.8h.BTC/USD -> BTC/USD (Deribit 8h)
        FundingRate.Hyperliquid.BTC/USD -> BTC/USD (Hyperliquid)
    """
    # Skip .EXT feeds (deprecated extended-hours)
    if symbol.endswith(".EXT"):
        return None

    parts = symbol.split(".")

    if asset_type == "funding-rate":
        pair = None
        exchange_parts = []
        for p in parts:
            if "/" in p:
                pair = p
            elif p != "FundingRate":
                exchange_parts.append(p)
        if pair:
            exchange_info = " ".join(exchange_parts)
            return f"{pair} ({exchange_info})"
        return None

    # For all others: find the part containing /
    pair_parts = [p for p in parts if "/" in p]
    if pair_parts:
        return pair_parts[0]

    # Fallback
    return parts[-1]


def main():
    # Load existing CSV
    with open("Price_Feeds_KPIs.csv", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        existing_rows = list(reader)

    num_cols = len(header)

    # Build set of existing (name, asset_class) keys
    csv_keys = set()
    last_no = 0
    for row in existing_rows:
        if len(row) > 4 and row[1].strip():
            csv_keys.add((row[1].strip(), row[4].strip()))
        if row[0].strip().isdigit():
            last_no = max(last_no, int(row[0].strip()))

    print(f"Existing CSV rows: {len(existing_rows)}")
    print(f"Existing unique (name, asset_class) pairs: {len(csv_keys)}")
    print(f"Last No: {last_no}")

    # Load after.json
    with open("after.json") as f:
        data = json.load(f)

    # Find missing feeds (deduplicate by (name, asset_class))
    seen = set()
    to_add = []
    skipped_ext = 0
    skipped_dupe = 0

    for feed in data["feeds"]:
        symbol = feed["symbol"]
        asset_type = feed["metadata"]["asset_type"]
        csv_asset = ASSET_MAP.get(asset_type, asset_type)
        state = feed.get("state", "")

        name = extract_feed_name(symbol, asset_type)
        if name is None:
            skipped_ext += 1
            continue

        key = (name, csv_asset)

        # Skip if already in CSV or already queued
        if key in csv_keys:
            continue
        if key in seen:
            skipped_dupe += 1
            continue
        seen.add(key)

        status = STATE_MAP.get(state, "inactive")
        to_add.append((name, csv_asset, status))

    print(f"\nSkipped .EXT feeds: {skipped_ext}")
    print(f"Skipped duplicates: {skipped_dupe}")
    print(f"New feeds to add: {len(to_add)}")

    # Breakdown
    by_class = Counter(ac for _, ac, _ in to_add)
    print("\nBy asset class:")
    for k, v in by_class.most_common():
        print(f"  {k}: {v}")

    by_status = Counter(st for _, _, st in to_add)
    print("\nBy status:")
    for k, v in by_status.most_common():
        print(f"  {k}: {v}")

    # Build new rows
    new_rows = []
    for i, (name, asset_class, status) in enumerate(to_add, start=last_no + 1):
        row = [""] * num_cols
        row[0] = str(i)  # No
        row[1] = name  # Feeds
        # row[2] = ""    # Date - blank
        # row[3] = ""    # Feed Month - blank
        row[4] = asset_class  # Asset Class
        # row[5] = ""    # Region - blank
        row[6] = status  # Status
        # row[7] = ""    # Week Sorted - blank
        new_rows.append(row)

    # Write updated CSV
    with open("Price_Feeds_KPIs.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(existing_rows)
        writer.writerows(new_rows)

    total = len(existing_rows) + len(new_rows)
    print(f"\nDone! Written {total} rows ({len(new_rows)} new) to Price_Feeds_KPIs.csv")


if __name__ == "__main__":
    main()
