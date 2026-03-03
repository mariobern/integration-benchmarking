"""
Update after.json from a feed_readiness summary CSV.

Reads a summary CSV, filters out Test/Lazer publishers, intersects
publishers across dates per feed, and surgically modifies the target
JSON config with per-session publisher lists.
"""
import argparse
import csv
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


def parse_summary_csv(fileobj) -> dict[int, list[dict]]:
    """Parse summary CSV and group rows by feed_id.

    Returns dict mapping feed_id (int) -> list of row dicts.
    """
    reader = csv.DictReader(fileobj)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in reader:
        feed_id = int(row["feed_id"])
        grouped[feed_id].append(row)
    return dict(grouped)


# Excluded publisher IDs (derived from publishers.md)
# Test publishers (.Test suffix)
_EXCLUDED_TEST = {
    23,
    25,
    27,
    30,
    31,
    33,
    36,
    38,
    39,
    40,
    43,
    46,
    47,
    49,
    51,
    53,
    56,
    58,
    60,
    61,
    63,
    66,
    68,
    70,
}
# Lazer publishers (Lazer. prefix)
_EXCLUDED_LAZER = {1, 9, 13, 15}
EXCLUDED_PUBLISHERS = _EXCLUDED_TEST | _EXCLUDED_LAZER

# CSV column → session key mapping
_SESSION_COLUMNS = {
    "fully_passing_publishers": "regular",
    "premarket_fully_passing_publishers": "premarket",
    "afterhours_fully_passing_publishers": "afterhours",
    "overnight_fully_passing_publishers": "overnight",
}

# Asset classes that support extended sessions
_EXTENDED_SESSION_MODES = {"us-equities", "equity-us"}


def _parse_publisher_list(pub_str: str) -> set[int]:
    """Parse semicolon-separated publisher IDs into a set of ints."""
    if not pub_str or not pub_str.strip():
        return set()
    return {int(p) for p in pub_str.split(";")}


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


def compute_feed_publishers(rows: list[dict]) -> dict:
    """Compute per-session publisher lists for a single feed.

    For each session, intersects filtered publishers across all dates.
    Returns dict with keys: regular, premarket, afterhours, overnight,
    top_level (union of all sessions), mode.
    """
    mode = rows[0]["mode"]
    is_extended = mode in _EXTENDED_SESSION_MODES

    session_sets: dict[str, set[int] | None] = {
        "regular": None,
        "premarket": None,
        "afterhours": None,
        "overnight": None,
    }

    for row in rows:
        for csv_col, session_key in _SESSION_COLUMNS.items():
            # Skip extended sessions for non-equities
            if session_key != "regular" and not is_extended:
                continue

            raw_pubs = _parse_publisher_list(row.get(csv_col, ""))
            filtered = raw_pubs - EXCLUDED_PUBLISHERS

            if not filtered:
                if session_sets[session_key] is None:
                    session_sets[session_key] = set()
                else:
                    session_sets[session_key] = set()
                continue

            if session_sets[session_key] is None:
                session_sets[session_key] = filtered
            else:
                session_sets[session_key] &= filtered

    result = {}
    all_pubs: set[int] = set()
    for key in ["regular", "premarket", "afterhours", "overnight"]:
        pubs = sorted(session_sets[key]) if session_sets[key] else []
        result[key] = pubs
        all_pubs.update(pubs)

    result["top_level"] = sorted(all_pubs)
    result["mode"] = mode
    return result


def modify_config(
    config_path: str,
    feed_publishers: dict[int, dict],
    dry_run: bool = False,
) -> dict:
    """Modify after.json with per-session publisher lists.

    Uses surgical regex replacements to preserve the original formatting.
    Returns summary dict with counts.
    """
    with open(config_path) as f:
        raw = f.read()

    data = json.loads(raw)
    feeds = data["feeds"]

    # Build feedId -> {name, state} lookup
    feed_lookup: dict[int, dict] = {}
    for feed in feeds:
        feed_lookup[feed["feedId"]] = {
            "name": feed.get("metadata", {}).get("name", ""),
            "state": feed["state"],
            "symbol": feed.get("symbol", ""),
        }

    newly_stable = 0
    updated_stable = 0
    skipped_empty = 0
    not_found = []

    for feed_id, pub_data in feed_publishers.items():
        if feed_id not in feed_lookup:
            not_found.append(feed_id)
            print(f"  WARNING: feedId={feed_id} not found in config")
            continue

        info = feed_lookup[feed_id]

        # Skip if no publishers at all
        if not pub_data["top_level"]:
            skipped_empty += 1
            print(
                f"  SKIP: {info['name']} (feedId={feed_id})"
                " -> no passing publishers after filtering"
            )
            continue

        # Only handle COMING_SOON and STABLE
        if info["state"] not in ("COMING_SOON", "STABLE"):
            print(
                f"  SKIP: {info['name']} (feedId={feed_id}," f" state={info['state']})"
            )
            continue

        bounds = _find_feed_block(raw, feed_id)
        if not bounds:
            not_found.append(feed_id)
            print(
                f"  WARNING: {info['name']} feedId={feed_id}"
                " block not found in raw text"
            )
            continue

        start, end = bounds
        block = raw[start:end]

        # 1. State transition: COMING_SOON -> STABLE
        if info["state"] == "COMING_SOON":
            block = re.sub(r'"state": "COMING_SOON"', '"state": "STABLE"', block)

        # 2. Update top-level allowedPublisherIds
        pub_str = "[ " + ", ".join(str(p) for p in pub_data["top_level"]) + " ]"
        if re.search(r'"allowedPublisherIds":', block):
            # Replace the FIRST occurrence (top-level, before marketSchedules)
            block = re.sub(
                r'"allowedPublisherIds": \[[^\]]*\]',
                f'"allowedPublisherIds": {pub_str}',
                block,
                count=1,
            )
        else:
            # Insert after opening {
            newline_pos = block.index("\n")
            insert_line = f'\n      "allowedPublisherIds": {pub_str},'
            block = block[:newline_pos] + insert_line + block[newline_pos:]

        # 3. Update top-level minPublishers to 1
        block = re.sub(r'"minPublishers": \d+', '"minPublishers": 1', block, count=1)

        raw = raw[:start] + block + raw[end:]

        if info["state"] == "COMING_SOON":
            newly_stable += 1
            label = "OK"
        else:
            updated_stable += 1
            label = "UPDATE"

        sessions_str = f"regular={pub_data['regular']}"
        if pub_data["premarket"]:
            sessions_str += f", premarket={pub_data['premarket']}"
        if pub_data["afterhours"]:
            sessions_str += f", afterhours={pub_data['afterhours']}"
        if pub_data["overnight"]:
            sessions_str += f", overnight={pub_data['overnight']}"

        state_label = "STABLE" if info["state"] == "COMING_SOON" else "updated"
        print(
            f"  {label}: {info['name']} (feedId={feed_id})"
            f" -> {state_label}, {sessions_str}"
        )

    if not dry_run and (newly_stable + updated_stable) > 0:
        backup_path = config_path + ".bak"
        shutil.copy2(config_path, backup_path)
        with open(config_path, "w") as f:
            f.write(raw)
        print(f"\nBackup saved to {backup_path}")

    return {
        "newly_stable": newly_stable,
        "updated_stable": updated_stable,
        "skipped_empty": skipped_empty,
        "not_found": not_found,
    }
