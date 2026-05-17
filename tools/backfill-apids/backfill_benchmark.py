#!/usr/bin/env python3
"""backfill_benchmark.py: phase-2 migration that adds `benchmarkMapping`
skeletons to feeds which already have `allowedPublisherIds` but are
missing benchmarkMapping in one or more sessions.

Selection rules (companion to backfill.py, which handled phase 1):
  * Feed must have top-level `allowedPublisherIds` set (i.e. NOT in
    phase-1's scope — those feeds were already handled).
  * Feed `state` must be COMING_SOON. STABLE feeds are not touched.
    INACTIVE feeds are not touched.
  * Feed `asset_type` must be `equity` or `metal`. All other asset
    types (fx, rates, custom, .Index synthetics, crypto-family, kalshi,
    nav, funding-rate) are skipped — they are either Pyth-native or
    intentionally left without a Datascope mapping.
  * Feed symbol must NOT contain `.Index.` (skips synthetic indices
    like Equity.Index.TSLA/USD).
  * At least one session in the feed must be missing `benchmarkMapping`.

Treatment:
  * **Standard US-equity** (`Equity.US.*` with REGULAR session schedule
    starting `America/New_York;0930-1600,`) — expand to 4 sessions
    (REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT) using AAPL/922's
    schedule templates, same as phase-1:
      - REGULAR session: `allowedPublisherIds` carried over from the
        feed's existing top-level value (those publishers were assigned
        for what is currently the only session);
        `minPublishers` from feed's top-level value;
        `benchmarkMapping` with bare-ticker identifier.
      - PRE_MARKET / POST_MARKET: `allowedPublisherIds: []`,
        `minPublishers` from feed, benchmarkMapping = bare ticker.
      - OVER_NIGHT: `allowedPublisherIds: []`, `minPublishers` from
        feed, benchmarkMapping = `<ticker>.BLUE`.
      - Top-level `allowedPublisherIds` left unchanged.
  * **All other targets** (foreign equities, metals) — single REGULAR
    session preserved as-is, with an empty-identifier benchmarkMapping
    skeleton added. No session-level allowedPublisherIds added
    (single-session feeds in this file don't carry them by convention).

Usage:
    python3 tools/backfill-apids/backfill_benchmark.py --config after.json
    python3 tools/backfill-apids/backfill_benchmark.py --config after.json --apply
"""

import argparse
import json
import sys
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent
_EDIT_CONFIG_ROOT = _TOOL_ROOT.parent / "edit-config"
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))
if str(_EDIT_CONFIG_ROOT) not in sys.path:
    sys.path.insert(0, str(_EDIT_CONFIG_ROOT))

from edit_config_lib.config_text_surgery import find_feed_block  # noqa: E402

from backfill import (  # noqa: E402
    AAPL_OVER_NIGHT_SCHEDULE,
    AAPL_POST_MARKET_SCHEDULE,
    AAPL_PRE_MARKET_SCHEDULE,
    AAPL_REGULAR_SCHEDULE,
    _format_identifier_obj,  # noqa: F401  (re-used indirectly via render helpers)
    _render_benchmark_mapping_from_obj,
    _render_benchmark_skeleton,
    _render_session_block,
    _replace_market_schedules,
)

# Asset types whose feeds we consider for benchmarkMapping backfill.
# Everything else (fx STABLE majors, rates, custom, funding-rate, all
# crypto-family, kalshi, nav) is skipped intentionally.
ELIGIBLE_ASSET_TYPES = {"equity", "metal"}


def _is_standard_us_equity_single_session(feed: dict) -> bool:
    """True iff this is a US cash-equity feed currently in single-session
    REGULAR form with the canonical 0930-1600 schedule, so phase-1's
    AAPL templates apply."""
    if not feed.get("symbol", "").startswith("Equity.US."):
        return False
    ms = feed.get("marketSchedules", [])
    if len(ms) != 1:
        return False
    return ms[0].get("marketSchedule", "").startswith("America/New_York;0930-1600,")


def _select_targets(feeds: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (expand_targets, skeleton_targets).

    expand_targets   -> standard US equities, expand to 4 sessions.
    skeleton_targets -> single-session feeds, add bm skeleton to REGULAR.
    """
    expand: list[dict] = []
    skeleton: list[dict] = []
    for f in feeds:
        if "allowedPublisherIds" not in f:
            continue  # phase-1 handled these
        if f.get("state") != "COMING_SOON":
            continue
        if f["metadata"].get("asset_type") not in ELIGIBLE_ASSET_TYPES:
            continue
        if ".Index." in f.get("symbol", ""):
            continue
        missing = any(
            "benchmarkMapping" not in ms for ms in f.get("marketSchedules", [])
        )
        if not missing:
            continue
        if _is_standard_us_equity_single_session(f):
            expand.append(f)
        else:
            skeleton.append(f)
    return expand, skeleton


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_inline_int_array(values: list[int]) -> str:
    """Render an int array in the file's inline style: '[ 1, 2, 3 ]'."""
    if not values:
        return "[]"
    return "[ " + ", ".join(str(v) for v in values) + " ]"


def _render_session_block_with_apids(
    session: str,
    schedule: str,
    apids: list[int],
    min_publishers: int,
    bm_text: str,
    base_indent: str = "        ",
) -> str:
    """Like backfill._render_session_block but with a configurable
    `allowedPublisherIds` value (not forced to [])."""
    prop_indent = base_indent + "  "
    parts: list[str] = []
    parts.append(f"{base_indent}{{\n")
    parts.append(
        f'{prop_indent}"allowedPublisherIds": {_render_inline_int_array(apids)},\n'
    )
    parts.append(bm_text)
    parts.append(
        f'{prop_indent}"marketSchedule": '
        f"{json.dumps(schedule, ensure_ascii=False)},\n"
    )
    parts.append(f'{prop_indent}"minPublishers": {min_publishers},\n')
    parts.append(f'{prop_indent}"session": "{session}"\n')
    parts.append(f"{base_indent}}}")
    return "".join(parts)


def _render_expanded_us_equity(feed: dict, base_indent: str = "      ") -> str:
    """Render the 4-session marketSchedules array for a phase-2 US-equity
    expansion. Existing top-level allowedPublisherIds is carried into
    the REGULAR session; PRE/POST/OVER_NIGHT start empty."""
    min_pubs = feed["minPublishers"]
    ticker = feed["metadata"].get("name") or ""
    if not ticker:
        raise ValueError(
            f"feed {feed['feedId']} ({feed['symbol']}) has no metadata.name"
        )

    existing_apids: list[int] = list(feed["allowedPublisherIds"])
    session_indent = base_indent + "  "
    prop_indent = session_indent + "  "

    # REGULAR session may have an existing benchmarkMapping that we keep;
    # the other sessions don't exist yet, so we build skeletons.
    src_regular = feed["marketSchedules"][0]
    src_bm = src_regular.get("benchmarkMapping")
    if src_bm is not None:
        cash_bm_text = _render_benchmark_mapping_from_obj(src_bm, prop_indent)
    else:
        cash_bm_text = _render_benchmark_skeleton(ticker, prop_indent)
    overnight_bm_text = _render_benchmark_skeleton(f"{ticker}.BLUE", prop_indent)

    blocks = [
        _render_session_block_with_apids(
            "REGULAR",
            AAPL_REGULAR_SCHEDULE,
            existing_apids,
            min_pubs,
            cash_bm_text,
            session_indent,
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
    return f'{base_indent}"marketSchedules": [\n' f"{body}\n" f"{base_indent}],\n"


def _render_single_session_add_skeleton(feed: dict, base_indent: str = "      ") -> str:
    """Render the marketSchedules array for a single-REGULAR-session
    feed, adding an empty benchmarkMapping skeleton. Preserves the
    feed's existing marketSchedule string and session name. Drops any
    session-level allowedPublisherIds/minPublishers (single-session
    feeds in this file don't carry them by convention)."""
    sessions = feed.get("marketSchedules", [])
    if len(sessions) != 1:
        raise ValueError(
            f"feed {feed['feedId']} expected 1 session, got {len(sessions)}"
        )
    src = sessions[0]
    schedule = src.get("marketSchedule", "")
    session_name = src.get("session", "REGULAR")
    session_indent = base_indent + "  "
    prop_indent = session_indent + "  "

    existing_bm = src.get("benchmarkMapping")
    if existing_bm is not None:
        bm_text = _render_benchmark_mapping_from_obj(existing_bm, prop_indent)
    else:
        bm_text = _render_benchmark_skeleton("", prop_indent)

    parts: list[str] = []
    parts.append(f"{session_indent}{{\n")
    parts.append(bm_text)
    parts.append(
        f'{prop_indent}"marketSchedule": '
        f"{json.dumps(schedule, ensure_ascii=False)},\n"
    )
    parts.append(f'{prop_indent}"session": "{session_name}"\n')
    parts.append(f"{session_indent}}}")
    block = "".join(parts)
    return f'{base_indent}"marketSchedules": [\n' f"{block}\n" f"{base_indent}],\n"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_migration(raw: str, expand: list[dict], skeleton: list[dict]) -> str:
    out = raw
    for f in expand:
        span = find_feed_block(out, f["feedId"])
        if span is None:
            raise RuntimeError(f"could not locate feed {f['feedId']}")
        start, end = span
        block = out[start:end]
        new_ms = _render_expanded_us_equity(f, base_indent="      ")
        block = _replace_market_schedules(block, new_ms)
        out = out[:start] + block + out[end:]
    for f in skeleton:
        span = find_feed_block(out, f["feedId"])
        if span is None:
            raise RuntimeError(f"could not locate feed {f['feedId']}")
        start, end = span
        block = out[start:end]
        new_ms = _render_single_session_add_skeleton(f, base_indent="      ")
        block = _replace_market_schedules(block, new_ms)
        out = out[:start] + block + out[end:]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_benchmark.py",
        description="Phase 2: backfill missing benchmarkMapping (equity + metal COMING_SOON)",
    )
    p.add_argument("--config", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    return p


def _summarize(expand, skeleton) -> None:
    from collections import Counter

    print(f"  US equities to expand to 4 sessions:      {len(expand)}")
    print(f"  Foreign equities + metals (REG skeleton): {len(skeleton)}")
    if skeleton:
        prefixes = Counter(".".join(f["symbol"].split(".")[:2]) for f in skeleton)
        print(
            "    by prefix: " + ", ".join(f"{p}={n}" for p, n in prefixes.most_common())
        )
    if expand:
        sample = ", ".join(f["symbol"] for f in expand[:3])
        print(f"    expand sample: {sample}{' ...' if len(expand) > 3 else ''}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config)
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    feeds = data["feeds"]

    expand, skeleton = _select_targets(feeds)
    total = len(expand) + len(skeleton)

    print(f"Reading {config_path} ({len(feeds)} feeds)")
    print(f"Plan: backfill benchmarkMapping in {total} feed(s)")
    _summarize(expand, skeleton)

    if total == 0:
        print("Nothing to do.")
        return 0

    new_raw = apply_migration(raw, expand, skeleton)

    # Validation.
    try:
        new_data = json.loads(new_raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: produced invalid JSON: {e}", file=sys.stderr)
        return 1
    new_by_id = {f["feedId"]: f for f in new_data["feeds"]}
    orig_by_id = {f["feedId"]: f for f in feeds}

    expected_sessions = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]
    for f in expand:
        nf = new_by_id[f["feedId"]]
        sessions = [ms.get("session") for ms in nf["marketSchedules"]]
        if sessions != expected_sessions:
            print(
                f"FATAL: feed {f['feedId']} sessions {sessions} != {expected_sessions}",
                file=sys.stderr,
            )
            return 1
        # Top-level apids unchanged.
        if nf["allowedPublisherIds"] != orig_by_id[f["feedId"]]["allowedPublisherIds"]:
            print(
                f"FATAL: feed {f['feedId']} top-level apids drifted",
                file=sys.stderr,
            )
            return 1
        # Every session has benchmarkMapping.
        for ms in nf["marketSchedules"]:
            if "benchmarkMapping" not in ms:
                print(
                    f"FATAL: feed {f['feedId']} session {ms['session']} missing bm",
                    file=sys.stderr,
                )
                return 1
        # REGULAR session inherited original top-level apids.
        if (
            nf["marketSchedules"][0]["allowedPublisherIds"]
            != orig_by_id[f["feedId"]]["allowedPublisherIds"]
        ):
            print(
                f"FATAL: feed {f['feedId']} REGULAR session apids not carried over",
                file=sys.stderr,
            )
            return 1

    for f in skeleton:
        nf = new_by_id[f["feedId"]]
        if "benchmarkMapping" not in nf["marketSchedules"][0]:
            print(
                f"FATAL: feed {f['feedId']} REGULAR session missing bm after patch",
                file=sys.stderr,
            )
            return 1
        # Top-level apids unchanged.
        if nf["allowedPublisherIds"] != orig_by_id[f["feedId"]]["allowedPublisherIds"]:
            print(
                f"FATAL: feed {f['feedId']} top-level apids drifted",
                file=sys.stderr,
            )
            return 1

    if not args.apply:
        print()
        print(
            f"[DRY RUN] Would write {total} feed change(s). Re-run with --apply to write."
        )
        return 0

    if not args.no_backup:
        backup_path = config_path.with_suffix(config_path.suffix + ".bak2")
        backup_path.write_text(raw, encoding="utf-8")
        print(f"Backup: {backup_path}")
    config_path.write_text(new_raw, encoding="utf-8")
    print(f"Wrote {total} change(s) to {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
