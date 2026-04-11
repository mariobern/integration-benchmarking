#!/usr/bin/env python3
"""One-off script to update after.json description fields from CSV metadata.

Uses regex replacement to preserve original JSON formatting.
"""

import csv
import json
import re


def main():
    csv_path = "modifications-metadata-20260304_v1.csv"
    json_path = "after.json"

    # Build feedId -> description mapping from CSV
    feed_descriptions = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            feed_id = int(row["pyth_lazer_id"])
            description = row["asset_full_name"]
            feed_descriptions[feed_id] = description

    print(f"Loaded {len(feed_descriptions)} unique feed descriptions from CSV")

    # Read after.json as text
    with open(json_path, "r") as f:
        text = f.read()

    # For each feed ID, find the feedId line, then find the next "description" line
    updated = 0
    for feed_id, new_desc in feed_descriptions.items():
        # Pattern: find "feedId": <id> followed (within ~500 chars) by "description": "..."
        pattern = re.compile(
            r'("feedId":\s*' + str(feed_id) + r'\b)'
            r'(.*?)'
            r'("description":\s*")(.*?)(")',
            re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            print(f"  WARNING: feedId {feed_id} not found in {json_path}")
            continue

        old_desc = match.group(4)
        if old_desc == new_desc:
            continue

        # Escape any special chars in new description for JSON
        escaped_new = new_desc.replace("\\", "\\\\").replace('"', '\\"')
        replacement = match.group(1) + match.group(2) + match.group(3) + escaped_new + match.group(5)
        text = text[:match.start()] + replacement + text[match.end():]

        print(f"  Feed {feed_id}: {old_desc!r} -> {new_desc!r}")
        updated += 1

    print(f"\nUpdated {updated} descriptions")

    with open(json_path, "w") as f:
        f.write(text)

    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
