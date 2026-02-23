"""
Promote ready feeds from COMING_SOON to STABLE in after.json.

Reads a markdown summary to get per-ticker publisher lists, then
surgically modifies the target JSON config.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def parse_summary_markdown(text: str) -> dict[str, list[int]]:
    """Parse the ticker/publisher table from the summary markdown.

    Returns dict mapping ticker -> sorted list of consistent publisher IDs.
    """
    result = {}
    pattern = re.compile(
        r"\|\s*\d+\s*\|\s*\*\*([\w./-]+)\*\*\s*\|\s*([^|]*)\|\s*\d+\s*\|"
    )
    for match in pattern.finditer(text):
        ticker = match.group(1)
        pubs_str = match.group(2).strip()
        if pubs_str:
            pubs = sorted(int(p.strip()) for p in pubs_str.split(",") if p.strip())
        else:
            pubs = []
        result[ticker] = pubs
    return result


def _find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Find the start/end positions of a feed entry by feedId in the raw JSON text."""
    pattern = rf'"feedId":\s*{feed_id}\s*[,\n}}]'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening { (string-aware)
    depth = 0
    start = pos - 1
    while start >= 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start >= 0 and raw[start] != '"':
                if raw[start] == "\\" and start > 0:
                    start -= 1
                start -= 1
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward from opening { for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def modify_config(
    config_path: str,
    ticker_pubs: dict[str, list[int]],
    dry_run: bool = False,
) -> dict:
    """Modify after.json: promote COMING_SOON feeds to STABLE.

    Uses surgical regex replacements to preserve the original formatting.
    Returns summary dict with counts of modified/skipped/not_found.
    """
    with open(config_path) as f:
        raw = f.read()

    data = json.loads(raw)
    feeds = data["feeds"]

    # Build name -> feedId + state mapping
    feed_lookup: dict[str, dict] = {}
    for feed in feeds:
        name = feed.get("metadata", {}).get("name", "")
        if name:
            feed_lookup[name] = {
                "feedId": feed["feedId"],
                "state": feed["state"],
            }

    modified = 0
    skipped_not_coming_soon = 0
    not_found = []

    for ticker, pubs in ticker_pubs.items():
        if ticker not in feed_lookup:
            not_found.append(ticker)
            print(f"  WARNING: {ticker} not found in config")
            continue

        info = feed_lookup[ticker]
        if info["state"] != "COMING_SOON":
            skipped_not_coming_soon += 1
            print(f"  SKIP: {ticker} (state={info['state']}, not COMING_SOON)")
            continue

        bounds = _find_feed_block(raw, info["feedId"])
        if not bounds:
            not_found.append(ticker)
            print(
                f"  WARNING: {ticker} feedId={info['feedId']} block not found in raw text"
            )
            continue

        start, end = bounds
        block = raw[start:end]

        # Surgical replacements
        new_block = re.sub(r'"state": "COMING_SOON"', '"state": "STABLE"', block)
        pub_str = "[ " + ", ".join(str(p) for p in sorted(pubs)) + " ]"
        if re.search(r'"allowedPublisherIds":', new_block):
            new_block = re.sub(
                r'"allowedPublisherIds": \[[^\]]*\]',
                f'"allowedPublisherIds": {pub_str}',
                new_block,
            )
        else:
            # Field doesn't exist yet — insert after opening {
            newline_pos = new_block.index("\n")
            insert_line = f'\n      "allowedPublisherIds": {pub_str},'
            new_block = new_block[:newline_pos] + insert_line + new_block[newline_pos:]
        new_block = re.sub(r'"minPublishers": \d+', '"minPublishers": 2', new_block)

        raw = raw[:start] + new_block + raw[end:]
        modified += 1
        print(
            f"  OK: {ticker} (feedId={info['feedId']}) -> STABLE, pubs={sorted(pubs)}, minPub=2"
        )

    if not dry_run and modified > 0:
        backup_path = config_path + ".bak"
        shutil.copy2(config_path, backup_path)
        with open(config_path, "w") as f:
            f.write(raw)
        print(f"\nBackup saved to {backup_path}")

    result = {
        "modified": modified,
        "skipped_not_coming_soon": skipped_not_coming_soon,
        "not_found": not_found,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote ready feeds from COMING_SOON to STABLE in after.json"
    )
    parser.add_argument(
        "--summary", required=True, help="Path to feeds_ready summary markdown file"
    )
    parser.add_argument(
        "--config", required=True, help="Path to after.json config file"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print changes without writing to file"
    )
    args = parser.parse_args()

    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"ERROR: Summary file not found: {summary_path}")
        sys.exit(1)
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    print(f"Reading summary from {summary_path}")
    ticker_pubs = parse_summary_markdown(summary_path.read_text())
    print(f"Found {len(ticker_pubs)} tickers with publisher mappings")

    if args.dry_run:
        print("\n=== DRY RUN (no files will be modified) ===\n")
    else:
        print()

    result = modify_config(str(config_path), ticker_pubs, dry_run=args.dry_run)

    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"  Modified:             {result['modified']}")
    print(f"  Skipped (not coming_soon): {result['skipped_not_coming_soon']}")
    print(f"  Not found in config:  {len(result['not_found'])}")
    if result["not_found"]:
        print(f"  Missing tickers: {', '.join(result['not_found'])}")
    total = (
        result["modified"]
        + result["skipped_not_coming_soon"]
        + len(result["not_found"])
    )
    print(f"  Total processed:      {total}/{len(ticker_pubs)}")


if __name__ == "__main__":
    main()
