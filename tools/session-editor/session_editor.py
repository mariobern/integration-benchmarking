#!/usr/bin/env python3
"""Session editor for after.json — add or remove market sessions on US-equity feeds.

Dry-run by default. Pass --apply to write.

Examples:
    # Remove OVER_NIGHT from a range
    python3 tools/session-editor/session_editor.py --config after.json \\
        --remove-session OVER_NIGHT --feed-id 2500-2700

    # Add OVER_NIGHT to specific feeds
    python3 tools/session-editor/session_editor.py --config after.json \\
        --add-session OVER_NIGHT --feed-id 1000-1050 --min-publishers 2 --apply

    # Remove all extended sessions across STABLE US equities (dry-run preview)
    python3 tools/session-editor/session_editor.py --config after.json \\
        --remove-session PRE_MARKET,POST_MARKET,OVER_NIGHT --state STABLE
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from session_editor_lib.diff import render_diff
from session_editor_lib.editor import PlanItem, simulate
from session_editor_lib.ops import AddSession, RemoveSession
from session_editor_lib.selector import parse_selector, parse_selector_lines
from session_editor_lib.templates import ADDABLE_SESSIONS, VALID_SESSIONS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Add or remove market sessions on US-equity feeds in after.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--config", required=True, help="Path to after.json")

    op_group = p.add_mutually_exclusive_group(required=False)
    op_group.add_argument(
        "--add-session",
        type=str,
        metavar="SESSIONS",
        help=f"Comma list of sessions to add (subset of {sorted(ADDABLE_SESSIONS)})",
    )
    op_group.add_argument(
        "--remove-session",
        type=str,
        metavar="SESSIONS",
        help=f"Comma list of sessions to remove (subset of {sorted(VALID_SESSIONS)})",
    )
    op_group.add_argument(
        "--from-spec",
        type=str,
        metavar="PATH",
        help="YAML batch spec (see docs/session_editor.md for schema).",
    )

    # Targeting
    p.add_argument(
        "--feed-id",
        type=str,
        help="Selector, e.g. 922 or 1000-1050,2000",
    )
    p.add_argument(
        "--feed-ids-from",
        type=str,
        help="Read selector(s) from file (use - for stdin)",
    )
    p.add_argument("--symbol-pattern", type=str, help="fnmatch glob on feed.symbol")
    p.add_argument(
        "--state",
        choices=("STABLE", "COMING_SOON", "INACTIVE"),
        help="Filter feeds by state",
    )

    # Add-only knobs
    p.add_argument(
        "--min-publishers",
        type=int,
        default=100,
        help=(
            "minPublishers for newly added sessions (default: 100, a sentinel "
            "value indicating the session is intentionally not-yet-ready). "
            "Lower it via edit-config once a real publisher cohort is in place."
        ),
    )
    p.add_argument(
        "--verify-templates",
        action="store_true",
        help=(
            "Compare canonical schedule templates against feedId 922 (AAPL) "
            "in the loaded config and exit. Useful for catching template drift."
        ),
    )

    # Safety
    p.add_argument(
        "--force",
        action="store_true",
        help="Allow removing REGULAR / operating on non-US-equity feeds.",
    )

    # Execution
    p.add_argument("--dry-run", action="store_true", help="Explicit form of default")
    p.add_argument("--apply", action="store_true", help="Write changes to disk")
    p.add_argument("--show-full-diff", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    return p


def _load_feed_ids(args) -> set[int] | None:
    ids: set[int] | None = None
    if args.feed_id:
        ids = parse_selector(args.feed_id)
    if args.feed_ids_from:
        text = (
            sys.stdin.read()
            if args.feed_ids_from == "-"
            else Path(args.feed_ids_from).read_text(encoding="utf-8")
        )
        more = parse_selector_lines(text)
        ids = more if ids is None else ids | more
    return ids


def _build_plan(args) -> list[PlanItem]:
    feed_ids = _load_feed_ids(args)
    common = dict(
        feed_ids=feed_ids,
        symbol_pattern=args.symbol_pattern,
        state=args.state,
        force_non_us=args.force,
    )
    plan: list[PlanItem] = []
    if args.add_session:
        for s in [s.strip() for s in args.add_session.split(",") if s.strip()]:
            plan.append(
                PlanItem(
                    op=AddSession(
                        session=s,
                        min_publishers=args.min_publishers,
                        force=args.force,
                    ),
                    **common,
                )
            )
    elif args.remove_session:
        for s in [s.strip() for s in args.remove_session.split(",") if s.strip()]:
            plan.append(
                PlanItem(
                    op=RemoveSession(session=s, force=args.force),
                    **common,
                )
            )
    return plan


def _summarize_outcomes(plan, outcomes_per_op) -> None:
    print()
    print("Plan:")
    for i, (item, ops) in enumerate(zip(plan, outcomes_per_op), start=1):
        cnt = Counter(o.action for o in ops)
        op_name = type(item.op).__name__
        target = item.op.session
        bits = ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())) or "(no matches)"
        print(f"  [{i}] {op_name} {target} → {bits}")

    skips = [o for op_outs in outcomes_per_op for o in op_outs if o.action == "skipped"]
    if skips:
        print()
        print(f"Skips ({len(skips)}):")
        reasons = Counter(o.reason for o in skips)
        for reason, n in reasons.most_common():
            print(f"  {n:>5}  {reason}")


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _build_text_edits(plan, outcomes_per_op, raw: str):
    """Translate successful per-feed outcomes into TextEdits on raw JSON.

    Returns (edits, errors). Skips outcomes where action != added/removed.
    """
    from session_editor_lib.text_apply import (
        TextApplyError,
        plan_add_session,
        plan_remove_session,
    )
    from session_editor_lib.ops import AddSession, RemoveSession

    edits = []
    errors = []
    for item, op_outcomes in zip(plan, outcomes_per_op):
        op = item.op
        for outcome in op_outcomes:
            if outcome.action not in ("added", "removed"):
                continue
            try:
                if isinstance(op, RemoveSession):
                    edit = plan_remove_session(raw, outcome.feed_id, op.session)
                elif isinstance(op, AddSession):
                    edit = plan_add_session(
                        raw,
                        outcome.feed_id,
                        op.session,
                        op.min_publishers,
                    )
                else:
                    continue
            except TextApplyError as e:
                errors.append(f"feedId={outcome.feed_id} {op.session}: {e}")
                continue
            if edit is not None:
                edits.append(edit)
    return edits, errors


def _verify_templates(feeds: list[dict]) -> int:
    """Diff canonical schedule strings against feedId 922 (AAPL). Return exit code."""
    from session_editor_lib.templates import SCHEDULE_BY_SESSION

    aapl = next((f for f in feeds if f.get("feedId") == 922), None)
    if aapl is None:
        print("ERROR: feedId 922 (AAPL) not found in config", file=sys.stderr)
        return 2
    by_session = {
        s.get("session"): s.get("marketSchedule")
        for s in aapl.get("marketSchedules", [])
    }
    drift = []
    for session, template in SCHEDULE_BY_SESSION.items():
        live = by_session.get(session)
        if live != template:
            drift.append((session, template, live))
    if not drift:
        print(
            f"OK: all {len(SCHEDULE_BY_SESSION)} canonical templates match "
            "feedId 922 (AAPL)."
        )
        return 0
    print(f"DRIFT: {len(drift)} session(s) differ from feedId 922:")
    for session, template, live in drift:
        print(f"  --- {session} (template)\n     {template}")
        print(f"  +++ {session} (AAPL 922)\n     {live}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config)
    raw_text = config_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    feeds = data["feeds"]
    print(f"Reading {config_path} ({len(feeds)} feeds)...")

    if args.verify_templates:
        return _verify_templates(feeds)

    if not (args.add_session or args.remove_session or args.from_spec):
        print(
            "ERROR: must specify --add-session, --remove-session, --from-spec, "
            "or --verify-templates",
            file=sys.stderr,
        )
        return 2

    try:
        if args.from_spec:
            from session_editor_lib.spec import parse_spec

            plan = parse_spec(args.from_spec)
            print(f"Parsing {args.from_spec}... {len(plan)} operation(s).")
        else:
            plan = _build_plan(args)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not plan:
        print("ERROR: empty plan (no sessions specified)", file=sys.stderr)
        return 2

    result = simulate(plan, feeds)
    _summarize_outcomes(plan, result.outcomes)

    diff = render_diff(feeds, result.after_feeds)
    if diff:
        print()
        if args.show_full_diff or len(diff) < 6000:
            print(diff)
        else:
            print(diff[:6000])
            print(
                f"\n... [diff truncated; {len(diff)} bytes total; "
                "use --show-full-diff to see all]"
            )
    else:
        print("\nNo changes.")

    print()
    print(f"Feeds changed: {result.changed_count}")

    if not args.apply:
        print("Dry-run (no file written). Pass --apply to commit.")
        return 0

    if not result.changed_count:
        print("Nothing to apply.")
        return 0

    # Translate the simulation outcomes into text-level edits so the file's
    # original formatting (compact arrays, etc.) is preserved.
    edits, text_errors = _build_text_edits(plan, result.outcomes, raw_text)
    if text_errors:
        print("ERROR: could not translate plan to text edits:", file=sys.stderr)
        for err in text_errors:
            print(f"  {err}", file=sys.stderr)
        return 3
    if not edits:
        print("Nothing to apply.")
        return 0

    from session_editor_lib.text_apply import apply_edits

    new_text = apply_edits(raw_text, edits)

    if not args.no_backup:
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        backup.write_bytes(config_path.read_bytes())
        print(f"Wrote backup → {backup}")

    _atomic_write_text(config_path, new_text)
    print(f"Applied {len(edits)} text edit(s). Wrote {config_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
