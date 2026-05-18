#!/usr/bin/env python3
"""backfill-apids: one-off migration to add `allowedPublisherIds` and
`benchmarkMapping` to feeds that lack them in after.json.

Behavior (per design discussion 2026-05-17, revised):
  * Targets only feeds with state == COMING_SOON that are missing the
    top-level `allowedPublisherIds` key. INACTIVE feeds are skipped.
  * For standard US-equity COMING_SOON feeds (symbol starts with
    `Equity.US.` and REGULAR session uses the canonical
    `America/New_York;0930-1600,...` schedule), marketSchedules is
    expanded from 1 session (REGULAR) to 4 sessions
    (REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT) using AAPL/922's
    marketSchedule strings as templates. Each session gets
    `allowedPublisherIds: []`, `minPublishers` = the feed's existing
    top-level value, and a `benchmarkMapping`:
      - REGULAR / PRE_MARKET / POST_MARKET: if the original REGULAR
        session had a benchmarkMapping (16/218 feeds), that mapping is
        carried over to all three; otherwise (202/218) the identifier
        is the bare ticker (metadata.name).
      - OVER_NIGHT: always uses `{ticker}.BLUE` (mirrors AAPL's pattern).
  * For other COMING_SOON missing-field feeds that DO have Datascope
    benchmarks (foreign equities, FX, commodity, rates, and the 3 CME
    futures NIDU6/FCDM6/FCDU6 whose 24h schedule isn't cash-equity-like),
    only the top-level `allowedPublisherIds: []` is inserted, AND an
    empty benchmarkMapping skeleton (identifier "") is added to the
    single REGULAR session. The marketSchedule string itself is
    untouched.
  * For "no-benchmark" COMING_SOON feeds — asset_type in {crypto,
    crypto-index, crypto-redemption-rate, kalshi, nav} — only the
    top-level `allowedPublisherIds: []` is inserted; marketSchedules is
    left entirely alone (no Datascope identifiers exist for these).

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

VALID_FROM_EPOCH = "1970-01-01T00:00:00.000000000Z"

# Asset types that do not use Datascope benchmarks: crypto-family is
# Pyth-native; kalshi/nav have no Datascope identifiers. For these we
# only add the top-level `allowedPublisherIds: []` and leave
# marketSchedules untouched.
NO_BENCHMARK_ASSET_TYPES = {
    "crypto",
    "crypto-index",
    "crypto-redemption-rate",
    "kalshi",
    "nav",
}


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
    return sched.startswith("America/New_York;0930-1600,")


def _select_targets(
    feeds: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Partition missing-field feeds.

    Returns (expand, top_only_non_crypto, top_only_no_bm, skipped_inactive):
      expand                  -> 4-session US-equity expansion + skeleton
      top_only_non_crypto     -> top-level [] + skeleton on REGULAR session
      top_only_no_bm         -> top-level [] only (no benchmarkMapping)
      skipped_inactive        -> reported, not touched
    """
    expand: list[dict] = []
    top_non_crypto: list[dict] = []
    top_no_bm: list[dict] = []
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
            continue
        asset = f.get("metadata", {}).get("asset_type")
        if asset in NO_BENCHMARK_ASSET_TYPES:
            top_no_bm.append(f)
        else:
            top_non_crypto.append(f)
    return expand, top_non_crypto, top_no_bm, skipped


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


def _format_identifier_obj(ident: dict) -> str:
    """Render `{ "identifier": "X", "validFrom": "Y" }` matching the
    file's existing style — spaces immediately inside the braces and
    after every separator. Mirrors AAPL's single-line identifier."""
    pairs = ", ".join(
        f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in ident.items()
    )
    return "{ " + pairs + " }"


def _render_benchmark_mapping_from_obj(bm: dict, prop_indent: str) -> str:
    """Render an existing benchmarkMapping dict in AAPL's compact style.
    Returns the key+value text (with trailing comma + newline)."""
    inner_indent = prop_indent + "  "
    lines = [f'{prop_indent}"benchmarkMapping": {{']
    keys = list(bm.keys())
    for i, top_key in enumerate(keys):
        top_val = bm[top_key]
        lines.append(f'{inner_indent}"{top_key}": {{')
        idents = top_val.get("identifiers", [])
        if len(idents) == 1:
            ident_json = _format_identifier_obj(idents[0])
            lines.append(f'{inner_indent}  "identifiers": [ {ident_json} ]')
        else:
            lines.append(f'{inner_indent}  "identifiers": [')
            for j, ident in enumerate(idents):
                comma = "," if j < len(idents) - 1 else ""
                lines.append(
                    f"{inner_indent}    {_format_identifier_obj(ident)}{comma}"
                )
            lines.append(f"{inner_indent}  ]")
        comma = "," if i < len(keys) - 1 else ""
        lines.append(f"{inner_indent}}}{comma}")
    lines.append(f"{prop_indent}}},")
    return "\n".join(lines) + "\n"


def _render_benchmark_skeleton(identifier: str, prop_indent: str) -> str:
    """Render a fresh benchmarkMapping with a single datascope_ric
    identifier. Used when the feed has no original benchmarkMapping."""
    bm = {
        "datascope_ric": {
            "identifiers": [
                {"identifier": identifier, "validFrom": VALID_FROM_EPOCH}
            ]
        }
    }
    return _render_benchmark_mapping_from_obj(bm, prop_indent)


def _render_session_block(
    session: str,
    schedule: str,
    min_publishers: int,
    benchmark_mapping_text: str,
    base_indent: str = "        ",
) -> str:
    """Render a single marketSchedules entry. Property order matches
    AAPL: allowedPublisherIds, benchmarkMapping, marketSchedule,
    minPublishers, session."""
    prop_indent = base_indent + "  "
    parts: list[str] = []
    parts.append(f"{base_indent}{{\n")
    parts.append(f'{prop_indent}"allowedPublisherIds": [],\n')
    parts.append(benchmark_mapping_text)  # already includes trailing ",\n"
    parts.append(
        f'{prop_indent}"marketSchedule": '
        f"{json.dumps(schedule, ensure_ascii=False)},\n"
    )
    parts.append(f'{prop_indent}"minPublishers": {min_publishers},\n')
    parts.append(f'{prop_indent}"session": "{session}"\n')
    parts.append(f"{base_indent}}}")
    return "".join(parts)


def _render_expanded_market_schedules(
    feed: dict, base_indent: str = "      "
) -> str:
    """Render the full `"marketSchedules": [ ... ]` property text for a
    US-equity feed being expanded to 4 sessions."""
    min_pubs = feed["minPublishers"]
    ticker = feed["metadata"].get("name") or ""
    if not ticker:
        raise ValueError(
            f"feed {feed['feedId']} ({feed['symbol']}) has no metadata.name"
        )

    original_bm = feed["marketSchedules"][0].get("benchmarkMapping")
    session_indent = base_indent + "  "  # 8 spaces
    prop_indent = session_indent + "  "  # 10 spaces

    # REGULAR / PRE / POST share a benchmarkMapping (original if present,
    # else skeleton with bare ticker).
    if original_bm is not None:
        cash_bm_text = _render_benchmark_mapping_from_obj(original_bm, prop_indent)
    else:
        cash_bm_text = _render_benchmark_skeleton(ticker, prop_indent)
    # OVER_NIGHT always uses <ticker>.BLUE (mirrors AAPL's pattern).
    overnight_bm_text = _render_benchmark_skeleton(f"{ticker}.BLUE", prop_indent)

    blocks = [
        _render_session_block(
            "REGULAR", AAPL_REGULAR_SCHEDULE, min_pubs, cash_bm_text, session_indent
        ),
        _render_session_block(
            "PRE_MARKET",
            AAPL_PRE_MARKET_SCHEDULE,
            min_pubs,
            cash_bm_text,
            session_indent,
        ),
        _render_session_block(
            "POST_MARKET",
            AAPL_POST_MARKET_SCHEDULE,
            min_pubs,
            cash_bm_text,
            session_indent,
        ),
        _render_session_block(
            "OVER_NIGHT",
            AAPL_OVER_NIGHT_SCHEDULE,
            min_pubs,
            overnight_bm_text,
            session_indent,
        ),
    ]
    body = ",\n".join(blocks)
    return (
        f'{base_indent}"marketSchedules": [\n'
        f"{body}\n"
        f"{base_indent}],\n"
    )


def _replace_market_schedules(feed_text: str, new_ms_text: str) -> str:
    """Replace the existing `"marketSchedules": [ ... ],?` property."""
    m = re.search(r'( *)"marketSchedules":\s*\[', feed_text)
    if m is None:
        raise ValueError("feed has no marketSchedules property")
    arr_open = m.end() - 1
    arr_close = find_matching_close(feed_text, arr_open)
    if arr_close is None:
        raise ValueError("unbalanced marketSchedules array")
    prop_start = m.start(1)
    end = arr_close + 1
    if end < len(feed_text) and feed_text[end] == ",":
        end += 1
    if end < len(feed_text) and feed_text[end] == "\n":
        end += 1
    return feed_text[:prop_start] + new_ms_text + feed_text[end:]


def _render_single_session_with_skeleton(
    feed: dict, base_indent: str = "      "
) -> str:
    """Render the `marketSchedules` array for a single-REGULAR-session
    feed, preserving the original session contents (marketSchedule
    string and any other keys) and adding an empty benchmarkMapping
    skeleton. Output is always canonical multi-line format, regardless
    of the original layout (some feeds, e.g. Rates.EPE-USDC, are on one
    line). This also drops session-level allowedPublisherIds/minPublishers
    since single-session feeds in this file do not carry them."""
    sessions = feed.get("marketSchedules", [])
    if len(sessions) != 1:
        raise ValueError(
            f"feed {feed['feedId']} expected 1 session, got {len(sessions)}"
        )
    src = sessions[0]
    schedule = src.get("marketSchedule", "")
    session_name = src.get("session", "REGULAR")
    session_indent = base_indent + "  "  # 8 spaces
    prop_indent = session_indent + "  "  # 10 spaces

    # Use existing benchmarkMapping if the feed already has one (rare in
    # this bucket); otherwise build empty skeleton.
    existing_bm = src.get("benchmarkMapping")
    if existing_bm is not None:
        bm_text = _render_benchmark_mapping_from_obj(existing_bm, prop_indent)
    else:
        bm_text = _render_benchmark_skeleton("", prop_indent)

    parts: list[str] = []
    parts.append(f"{session_indent}{{\n")
    parts.append(bm_text)  # benchmarkMapping (with trailing ",\n")
    parts.append(
        f'{prop_indent}"marketSchedule": '
        f"{json.dumps(schedule, ensure_ascii=False)},\n"
    )
    parts.append(f'{prop_indent}"session": "{session_name}"\n')
    parts.append(f"{session_indent}}}")
    block = "".join(parts)
    return (
        f'{base_indent}"marketSchedules": [\n'
        f"{block}\n"
        f"{base_indent}],\n"
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_migration(
    raw: str,
    expand: list[dict],
    top_non_crypto: list[dict],
    top_no_bm: list[dict],
) -> str:
    out = raw
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
    for f in top_non_crypto:
        span = find_feed_block(out, f["feedId"])
        if span is None:
            raise RuntimeError(f"could not locate feed {f['feedId']} in raw text")
        start, end = span
        block = out[start:end]
        block = _insert_top_level_apids(block)
        new_ms = _render_single_session_with_skeleton(f, base_indent="      ")
        block = _replace_market_schedules(block, new_ms)
        out = out[:start] + block + out[end:]
    for f in top_no_bm:
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
        description="Backfill missing allowedPublisherIds + benchmarkMapping in after.json",
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


def _summarize(expand, top_non_crypto, top_no_bm, skipped) -> None:
    print(f"  Standard US equities to expand (4 sessions, +bm):  {len(expand)}")
    print(f"  With-benchmark COMING_SOON (top-level [] + skel):  {len(top_non_crypto)}")
    print(f"  No-benchmark COMING_SOON (top-level [] only):      {len(top_no_bm)}")
    print(f"  INACTIVE feeds skipped:                            {len(skipped)}")
    if expand:
        sample = ", ".join(f["symbol"] for f in expand[:3])
        print(f"    expand sample: {sample}{' ...' if len(expand) > 3 else ''}")
    if top_non_crypto:
        from collections import Counter
        prefixes = Counter(
            ".".join(f["symbol"].split(".")[:2]) for f in top_non_crypto
        )
        top_pref = ", ".join(f"{p}={n}" for p, n in prefixes.most_common(6))
        print(f"    non-crypto by prefix: {top_pref}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config)
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    feeds = data["feeds"]

    expand, top_non_crypto, top_no_bm, skipped = _select_targets(feeds)
    total_changes = len(expand) + len(top_non_crypto) + len(top_no_bm)

    print(f"Reading {config_path} ({len(feeds)} feeds)")
    print(f"Plan: backfill {total_changes} feed(s)")
    _summarize(expand, top_non_crypto, top_no_bm, skipped)

    if total_changes == 0:
        print("Nothing to do.")
        return 0

    new_raw = apply_migration(raw, expand, top_non_crypto, top_no_bm)

    # Sanity check.
    try:
        new_data = json.loads(new_raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: produced invalid JSON: {e}", file=sys.stderr)
        return 1
    new_feeds_by_id = {f["feedId"]: f for f in new_data["feeds"]}

    # Every target now has top-level allowedPublisherIds.
    targeted = expand + top_non_crypto + top_no_bm
    missing_after = [
        f["feedId"]
        for f in targeted
        if "allowedPublisherIds" not in new_feeds_by_id.get(f["feedId"], {})
    ]
    if missing_after:
        print(
            f"FATAL: {len(missing_after)} feed(s) missing the field after patch: "
            f"{missing_after[:10]}",
            file=sys.stderr,
        )
        return 1

    # Expand targets: 4 sessions in correct order; every session has a
    # benchmarkMapping.
    expected = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]
    for f in expand:
        nf = new_feeds_by_id[f["feedId"]]
        sessions = [ms.get("session") for ms in nf.get("marketSchedules", [])]
        if sessions != expected:
            print(
                f"FATAL: feed {f['feedId']} sessions are {sessions}, expected {expected}",
                file=sys.stderr,
            )
            return 1
        for ms in nf["marketSchedules"]:
            if "benchmarkMapping" not in ms:
                print(
                    f"FATAL: feed {f['feedId']} session {ms['session']} "
                    "missing benchmarkMapping",
                    file=sys.stderr,
                )
                return 1

    # Top non-crypto: REGULAR session now has benchmarkMapping.
    for f in top_non_crypto:
        nf = new_feeds_by_id[f["feedId"]]
        ms = nf["marketSchedules"][0]
        if "benchmarkMapping" not in ms:
            print(
                f"FATAL: feed {f['feedId']} REGULAR session missing benchmarkMapping",
                file=sys.stderr,
            )
            return 1

    # Top crypto: marketSchedules unchanged from original.
    orig_feeds_by_id = {f["feedId"]: f for f in feeds}
    for f in top_no_bm:
        nf = new_feeds_by_id[f["feedId"]]
        if nf["marketSchedules"] != orig_feeds_by_id[f["feedId"]]["marketSchedules"]:
            print(
                f"FATAL: crypto feed {f['feedId']} marketSchedules drifted",
                file=sys.stderr,
            )
            return 1

    if not args.apply:
        print()
        print(
            f"[DRY RUN] Would write {total_changes} feed change(s). "
            "Re-run with --apply to write."
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
