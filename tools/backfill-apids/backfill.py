#!/usr/bin/env python3
"""backfill-apids: one-off migration to add `allowedPublisherIds` to feeds that
lack it in after.json.

Behavior (per design discussion 2026-05-17):
  * Targets only feeds with state == COMING_SOON that are missing the
    top-level `allowedPublisherIds` key. INACTIVE feeds are skipped.
  * For standard US-equity COMING_SOON feeds (symbol starts with
    `Equity.US.` and REGULAR session uses the canonical
    `America/New_York;0930-1600,...` schedule), the marketSchedules array
    is expanded from 1 session (REGULAR) to 4 sessions
    (REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT). The new sessions
    use AAPL/feedId=922 as the template for the marketSchedule strings.
    Each session gets `allowedPublisherIds: []` and
    `minPublishers` = the feed's existing top-level minPublishers value.
    If the REGULAR session has a `benchmarkMapping`, it is copied to
    PRE_MARKET and POST_MARKET (OVER_NIGHT gets none — AAPL's .BLUE RIC
    is ticker-specific).
  * For all other COMING_SOON missing-field feeds (non-US-equity,
    CME futures like NIDU6/FCDM6/FCDU6, and US equities with
    non-standard schedules), only the top-level
    `allowedPublisherIds: []` is inserted; marketSchedules is left alone.

Output preserves the existing file formatting style (inline arrays of
small ints, 6-space property indent inside each feed block, 8-space
indent inside marketSchedules entries) so the diff stays minimal and
edit_config.py's text-surgery operations keep working.

Usage:
    python3 tools/backfill-apids/backfill.py --config after.json [--apply]
    python3 tools/backfill-apids/backfill.py --config after.json --apply --no-backup
"""

import argparse
import json
import re
import sys
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent
_EDIT_CONFIG_ROOT = _TOOL_ROOT.parent / "edit-config"
if str(_EDIT_CONFIG_ROOT) not in sys.path:
    sys.path.insert(0, str(_EDIT_CONFIG_ROOT))

from edit_config_lib.config_text_surgery import (  # noqa: E402
    find_feed_block,
    find_matching_close,
)

# AAPL (feedId=922) marketSchedule strings — used as templates for the
# 4-session expansion. Standard US cash-equity hours in America/New_York.
AAPL_REGULAR_SCHEDULE = (
    "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
    "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,"
    "1127/0930-1300,1224/0930-1300,1225/C"
)
AAPL_PRE_MARKET_SCHEDULE = (
    "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;"
    "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
)
AAPL_POST_MARKET_SCHEDULE = (
    "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;"
    "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
)
AAPL_OVER_NIGHT_SCHEDULE = (
    "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,"
    "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;"
    "0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,"
    "0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,"
    "0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,"
    "1224/0000-0400,1225/C,1231/0000-0400,0101/C"
)


def _is_standard_us_equity(feed: dict) -> bool:
    """True iff this is a US cash-equity feed whose REGULAR session uses
    the canonical 0930-1600 schedule (so AAPL's session templates apply).
    Excludes CME futures (e.g. NIDU6) which have a near-24h schedule."""
    if not feed.get("symbol", "").startswith("Equity.US."):
        return False
    schedules = feed.get("marketSchedules", [])
    if len(schedules) != 1:
        return False
    sched = schedules[0].get("marketSchedule", "")
    # Canonical US cash-equity REGULAR-hours opener.
    return sched.startswith("America/New_York;0930-1600,")


def _select_targets(feeds: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (expand_targets, top_level_only_targets, skipped_inactive).

    expand_targets: standard US equities, COMING_SOON, missing field.
    top_level_only_targets: all other COMING_SOON missing-field feeds.
    skipped_inactive: INACTIVE missing-field feeds (reported, not touched).
    """
    expand: list[dict] = []
    top_only: list[dict] = []
    skipped: list[dict] = []
    for f in feeds:
        if "allowedPublisherIds" in f:
            continue
        state = f.get("state")
        if state == "INACTIVE":
            skipped.append(f)
            continue
        if state != "COMING_SOON":
            continue
        if _is_standard_us_equity(f):
            expand.append(f)
        else:
            top_only.append(f)
    return expand, top_only, skipped


# ---------------------------------------------------------------------------
# Text-surgery helpers
# ---------------------------------------------------------------------------


def _insert_top_level_apids(feed_text: str) -> str:
    """Insert `"allowedPublisherIds": [],` as the first property of the
    feed block. Assumes the block starts with `{\\n      <first_key>`."""
    m = re.match(r"(\{\s*\n)(\s*)", feed_text)
    if m is None:
        raise ValueError("feed block does not start with '{\\n<indent>'")
    open_brace, indent = m.group(1), m.group(2)
    insertion = f'{indent}"allowedPublisherIds": [],\n'
    return open_brace + insertion + feed_text[len(open_brace) :]


def _render_benchmark_mapping(bm: dict | None, prop_indent: str) -> str:
    """Render benchmarkMapping in the file's compact style, matching
    AAPL's formatting. Returns the rendered key+value (no trailing comma)
    or '' if bm is None."""
    if bm is None:
        return ""
    # Single-identifier, datascope_ric is the only shape we see in
    # missing US-equity REGULAR sessions; render generically just in case.
    inner_indent = prop_indent + "  "  # +2
    lines = [f'{prop_indent}"benchmarkMapping": {{']
    keys = list(bm.keys())
    for i, top_key in enumerate(keys):
        top_val = bm[top_key]
        lines.append(f'{inner_indent}"{top_key}": {{')
        idents = top_val.get("identifiers", [])
        # Render identifiers inline if 1, else multi-line.
        if len(idents) == 1:
            ident_json = json.dumps(idents[0], ensure_ascii=False)
            lines.append(f'{inner_indent}  "identifiers": [ {ident_json} ]')
        else:
            lines.append(f'{inner_indent}  "identifiers": [')
            for j, ident in enumerate(idents):
                comma = "," if j < len(idents) - 1 else ""
                lines.append(
                    f"{inner_indent}    {json.dumps(ident, ensure_ascii=False)}{comma}"
                )
            lines.append(f"{inner_indent}  ]")
        comma = "," if i < len(keys) - 1 else ""
        lines.append(f"{inner_indent}}}{comma}")
    lines.append(f"{prop_indent}}},")
    return "\n".join(lines) + "\n"


def _render_session_block(
    session: str,
    schedule: str,
    min_publishers: int,
    benchmark_mapping: dict | None,
    base_indent: str = "        ",
) -> str:
    """Render a single marketSchedules entry. Property order matches
    AAPL: allowedPublisherIds, benchmarkMapping (optional),
    marketSchedule, minPublishers, session."""
    prop_indent = base_indent + "  "  # +2
    parts: list[str] = []
    parts.append(f"{base_indent}{{\n")
    parts.append(f'{prop_indent}"allowedPublisherIds": [],\n')
    if benchmark_mapping is not None:
        parts.append(_render_benchmark_mapping(benchmark_mapping, prop_indent))
    # marketSchedule string — must be JSON-escaped.
    parts.append(
        f'{prop_indent}"marketSchedule": {json.dumps(schedule, ensure_ascii=False)},\n'
    )
    parts.append(f'{prop_indent}"minPublishers": {min_publishers},\n')
    parts.append(f'{prop_indent}"session": "{session}"\n')
    parts.append(f"{base_indent}}}")
    return "".join(parts)


def _render_expanded_market_schedules(feed: dict, base_indent: str = "      ") -> str:
    """Render the full `"marketSchedules": [ ... ]` property text for a
    US-equity feed being expanded to 4 sessions. Trailing comma is
    included because marketSchedules is never the last key in the file's
    canonical ordering (metadata, minChannel, minPublishers, state,
    symbol all follow alphabetically)."""
    min_pubs = feed["minPublishers"]
    regular_bm = feed["marketSchedules"][0].get("benchmarkMapping")
    session_indent = base_indent + "  "  # +2 -> 8 spaces
    blocks = [
        _render_session_block(
            "REGULAR", AAPL_REGULAR_SCHEDULE, min_pubs, regular_bm, session_indent
        ),
        _render_session_block(
            "PRE_MARKET",
            AAPL_PRE_MARKET_SCHEDULE,
            min_pubs,
            regular_bm,
            session_indent,
        ),
        _render_session_block(
            "POST_MARKET",
            AAPL_POST_MARKET_SCHEDULE,
            min_pubs,
            regular_bm,
            session_indent,
        ),
        _render_session_block(
            "OVER_NIGHT", AAPL_OVER_NIGHT_SCHEDULE, min_pubs, None, session_indent
        ),
    ]
    body = ",\n".join(blocks)
    return f'{base_indent}"marketSchedules": [\n' f"{body}\n" f"{base_indent}],\n"


def _replace_market_schedules(feed_text: str, new_ms_text: str) -> str:
    """Replace the existing `"marketSchedules": [ ... ],?` property in
    feed_text with new_ms_text. Preserves leading indent."""
    m = re.search(r'( *)"marketSchedules":\s*\[', feed_text)
    if m is None:
        raise ValueError("feed has no marketSchedules property")
    arr_open = m.end() - 1  # position of '['
    arr_close = find_matching_close(feed_text, arr_open)
    if arr_close is None:
        raise ValueError("unbalanced marketSchedules array")
    # Include the leading indent and any trailing comma+newline.
    prop_start = m.start(1)
    end = arr_close + 1
    # Consume trailing ',' and newline if present.
    if end < len(feed_text) and feed_text[end] == ",":
        end += 1
    if end < len(feed_text) and feed_text[end] == "\n":
        end += 1
    return feed_text[:prop_start] + new_ms_text + feed_text[end:]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_migration(raw: str, expand: list[dict], top_only: list[dict]) -> str:
    """Apply migration to raw text. Patches are applied to a copy of raw;
    each feed is located fresh by feedId (regex), so apply order doesn't
    matter."""
    out = raw
    # Process expand targets first (larger patches) then top-only.
    for f in expand:
        span = find_feed_block(out, f["feedId"])
        if span is None:
            raise RuntimeError(f"could not locate feed {f['feedId']} in raw text")
        start, end = span
        block = out[start:end]
        block = _insert_top_level_apids(block)
        new_ms = _render_expanded_market_schedules(f, base_indent="      ")
        block = _replace_market_schedules(block, new_ms)
        out = out[:start] + block + out[end:]
    for f in top_only:
        span = find_feed_block(out, f["feedId"])
        if span is None:
            raise RuntimeError(f"could not locate feed {f['feedId']} in raw text")
        start, end = span
        block = out[start:end]
        block = _insert_top_level_apids(block)
        out = out[:start] + block + out[end:]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill.py",
        description="Backfill missing top-level allowedPublisherIds in after.json",
    )
    p.add_argument("--config", required=True, help="Path to after.json")
    p.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip writing <config>.bak when applying",
    )
    return p


def _summarize(expand, top_only, skipped) -> None:
    print(f"  Standard US equities to expand (4 sessions): {len(expand)}")
    print(f"  Other COMING_SOON feeds (top-level [] only): {len(top_only)}")
    print(f"  INACTIVE feeds skipped: {len(skipped)}")
    if expand:
        sample = ", ".join(f["symbol"] for f in expand[:3])
        print(f"    expand sample: {sample}{' ...' if len(expand) > 3 else ''}")
    if top_only:
        # Break down by symbol prefix for visibility.
        from collections import Counter

        prefixes = Counter(".".join(f["symbol"].split(".")[:2]) for f in top_only)
        top_pref = ", ".join(f"{p}={n}" for p, n in prefixes.most_common(6))
        print(f"    top-only by prefix: {top_pref}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config)
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    feeds = data["feeds"]

    expand, top_only, skipped = _select_targets(feeds)
    total_changes = len(expand) + len(top_only)

    print(f"Reading {config_path} ({len(feeds)} feeds)")
    print(f"Plan: backfill allowedPublisherIds in {total_changes} feed(s)")
    _summarize(expand, top_only, skipped)

    if total_changes == 0:
        print("Nothing to do.")
        return 0

    new_raw = apply_migration(raw, expand, top_only)

    # Sanity check: JSON must still parse, and every targeted feed must
    # now have the field at top level.
    try:
        new_data = json.loads(new_raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: produced invalid JSON: {e}", file=sys.stderr)
        return 1
    new_feeds_by_id = {f["feedId"]: f for f in new_data["feeds"]}
    failed: list[int] = []
    for f in expand + top_only:
        nf = new_feeds_by_id.get(f["feedId"])
        if nf is None or "allowedPublisherIds" not in nf:
            failed.append(f["feedId"])
    if failed:
        print(
            f"FATAL: {len(failed)} feed(s) missing the field after patch: "
            f"{failed[:10]}{' ...' if len(failed) > 10 else ''}",
            file=sys.stderr,
        )
        return 1
    # Expand targets must now have 4 sessions.
    for f in expand:
        nf = new_feeds_by_id[f["feedId"]]
        sessions = [ms.get("session") for ms in nf.get("marketSchedules", [])]
        expected = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]
        if sessions != expected:
            print(
                f"FATAL: feed {f['feedId']} sessions are {sessions}, "
                f"expected {expected}",
                file=sys.stderr,
            )
            return 1

    if not args.apply:
        print()
        print(
            f"[DRY RUN] Would write {total_changes} feed change(s). "
            f"Re-run with --apply to write."
        )
        return 0

    if not args.no_backup:
        backup_path = config_path.with_suffix(config_path.suffix + ".bak")
        backup_path.write_text(raw, encoding="utf-8")
        print(f"Backup: {backup_path}")
    config_path.write_text(new_raw, encoding="utf-8")
    print(f"Wrote {total_changes} change(s) to {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
