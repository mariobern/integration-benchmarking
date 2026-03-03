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


# Market schedule templates (from feed 922 — AAPL)
_SCHEDULE_TEMPLATES = {
    "REGULAR": (
        "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,"
        "1127/0930-1300,1224/0930-1300,1225/C"
    ),
    "PRE_MARKET": (
        "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
    ),
    "POST_MARKET": (
        "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
    ),
    "OVER_NIGHT": (
        "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,"
        "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;"
        "0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,"
        "0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,"
        "0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,1224/0000-0400,"
        "1225/C,1231/0000-0400,0101/C"
    ),
}

# Session key (from compute_feed_publishers) -> after.json session name
_SESSION_KEY_TO_JSON = {
    "regular": "REGULAR",
    "premarket": "PRE_MARKET",
    "afterhours": "POST_MARKET",
    "overnight": "OVER_NIGHT",
}

# minPublishers per session
_SESSION_MIN_PUBLISHERS = {
    "REGULAR": 3,
    "PRE_MARKET": 2,
    "POST_MARKET": 2,
    "OVER_NIGHT": 1,
}


def _find_session_block(block: str, session_name: str) -> tuple[int, int] | None:
    """Find the start/end of a session entry within a marketSchedules array."""
    pattern = rf'"session":\s*"{session_name}"'
    match = re.search(pattern, block)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening {
    depth = 0
    start = pos - 1
    while start >= 0:
        c = block[start]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(block) and depth > 0:
        c = block[end]
        if c == '"' and (end == 0 or block[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def _build_session_entry(
    session_name: str, pub_ids: list[int], indent: str = "        "
) -> str:
    """Build a JSON session entry string for insertion into marketSchedules."""
    pub_str = ", ".join(str(p) for p in pub_ids)
    schedule = _SCHEDULE_TEMPLATES[session_name]
    min_pub = _SESSION_MIN_PUBLISHERS[session_name]
    return (
        f"{indent}{{\n"
        f'{indent}  "allowedPublisherIds": [ {pub_str} ],\n'
        f'{indent}  "marketSchedule": "{schedule}",\n'
        f'{indent}  "minPublishers": {min_pub},\n'
        f'{indent}  "session": "{session_name}"\n'
        f"{indent}}}"
    )


def _update_market_schedules(block: str, pub_data: dict) -> str:
    """Update marketSchedules entries within a feed block.

    For each session with publishers:
    - If session exists: update allowedPublisherIds and minPublishers
    - If session missing AND mode is us-equities: insert new entry
    """
    is_extended = pub_data["mode"] in _EXTENDED_SESSION_MODES

    for session_key, json_session in _SESSION_KEY_TO_JSON.items():
        pubs = pub_data[session_key]
        if not pubs:
            continue

        min_pub = _SESSION_MIN_PUBLISHERS[json_session]
        pub_str = "[ " + ", ".join(str(p) for p in pubs) + " ]"

        session_bounds = _find_session_block(block, json_session)

        if session_bounds:
            s_start, s_end = session_bounds
            session_block = block[s_start:s_end]

            # Update allowedPublisherIds within this session
            if re.search(r'"allowedPublisherIds":', session_block):
                session_block = re.sub(
                    r'"allowedPublisherIds": \[[^\]]*\]',
                    f'"allowedPublisherIds": {pub_str}',
                    session_block,
                )
            else:
                # Insert allowedPublisherIds after opening {
                nl = session_block.index("\n")
                insert = f'\n            "allowedPublisherIds": {pub_str},'
                session_block = session_block[:nl] + insert + session_block[nl:]

            # Update minPublishers within this session
            if re.search(r'"minPublishers":', session_block):
                session_block = re.sub(
                    r'"minPublishers": \d+',
                    f'"minPublishers": {min_pub}',
                    session_block,
                )
            else:
                # Insert minPublishers before "session" key
                session_match = re.search(r'"session":', session_block)
                if session_match:
                    insert_pos = session_match.start()
                    # Detect indentation from the "session" line
                    line_start = session_block.rfind("\n", 0, insert_pos) + 1
                    indent = session_block[line_start:insert_pos]
                    insert_str = f'"minPublishers": {min_pub},\n{indent}'
                    session_block = (
                        session_block[:insert_pos]
                        + insert_str
                        + session_block[insert_pos:]
                    )

            block = block[:s_start] + session_block + block[s_end:]

        elif is_extended:
            # Session doesn't exist — insert before closing ] of marketSchedules
            # Find the marketSchedules closing bracket
            ms_match = re.search(r'"marketSchedules":\s*\[', block)
            if not ms_match:
                continue

            # Find the ] that closes the marketSchedules array
            ms_start = ms_match.end()
            depth = 1
            pos = ms_start
            in_str = False
            while pos < len(block) and depth > 0:
                c = block[pos]
                if c == '"' and (pos == 0 or block[pos - 1] != "\\"):
                    in_str = not in_str
                elif not in_str:
                    if c == "[":
                        depth += 1
                    elif c == "]":
                        depth -= 1
                pos += 1
            closing_bracket = pos - 1  # position of ]

            # Walk back to find the last } before ]
            p = closing_bracket - 1
            while p >= 0 and block[p] in (" ", "\n", "\t", "\r"):
                p -= 1

            # Insert after the last session entry
            new_entry = ",\n" + _build_session_entry(json_session, pubs)
            block = block[: p + 1] + new_entry + block[p + 1 :]

    return block


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

        # 4. Update per-session marketSchedules
        block = _update_market_schedules(block, pub_data)

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update after.json from a feed_readiness summary CSV"
    )
    parser.add_argument(
        "--summary",
        required=True,
        help="Path to feed_readiness summary CSV",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing to file",
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

    # 1. Parse CSV
    print(f"Reading summary from {summary_path}")
    with open(summary_path) as f:
        grouped_rows = parse_summary_csv(f)
    print(f"Found {len(grouped_rows)} unique feeds across CSV rows")

    # 2. Compute per-feed publisher lists
    feed_publishers = {}
    for feed_id, rows in grouped_rows.items():
        pub_data = compute_feed_publishers(rows)
        feed_publishers[feed_id] = pub_data

    if args.dry_run:
        print("\n=== DRY RUN (no files will be modified) ===\n")
    else:
        print()

    # 3. Apply to config
    result = modify_config(str(config_path), feed_publishers, dry_run=args.dry_run)

    # 4. Print summary
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"  Newly STABLE:             {result['newly_stable']}")
    print(f"  Updated (already STABLE): {result['updated_stable']}")
    print(f"  Skipped (empty):          {result['skipped_empty']}")
    print(f"  Not found in config:      {len(result['not_found'])}")
    if result["not_found"]:
        print(f"  Missing feed IDs: {result['not_found']}")
    total = (
        result["newly_stable"]
        + result["updated_stable"]
        + result["skipped_empty"]
        + len(result["not_found"])
    )
    print(f"  Total processed:          {total}/{len(feed_publishers)}")


if __name__ == "__main__":
    main()
