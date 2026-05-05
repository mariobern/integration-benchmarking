#!/usr/bin/env python3
"""edit-config: surgical editor for after.json.

See docs/edit_config.md for usage.
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure tools/edit-config is on sys.path when invoked directly.
_TOOL_ROOT = Path(__file__).resolve().parent
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))

from edit_config_lib.config_diff import render_diff  # noqa: E402
from edit_config_lib.config_editor import (  # noqa: E402
    apply_changes,
    build_op_from_args,
    parse_yaml_spec,
    simulate_plan,
    write_with_backup,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="edit_config.py",
        description="Surgical editor for after.json",
    )
    p.add_argument("--config", required=True, help="Path to after.json")

    # Operation flags (mutually exclusive)
    op_group = p.add_mutually_exclusive_group()
    op_group.add_argument("--add-publisher", type=int)
    op_group.add_argument("--remove-publisher", type=int)
    op_group.add_argument("--set-min-publishers", type=int)
    op_group.add_argument(
        "--bump-min-publishers",
        type=str,
        help="Signed integer, e.g. +1 or -2",
    )
    op_group.add_argument("--set-state", choices=("STABLE", "COMING_SOON", "INACTIVE"))
    op_group.add_argument("--from-spec", type=str, help="YAML spec path")

    # Targeting
    p.add_argument(
        "--feed-id",
        type=str,
        help="Selector: e.g. 922 or 100-200,205,3530-3540",
    )
    p.add_argument(
        "--feed-ids-from",
        type=str,
        help="Read selector(s) from file (use - for stdin)",
    )
    p.add_argument("--symbol-pattern", type=str)
    p.add_argument("--asset-class", type=str)
    p.add_argument(
        "--state",
        choices=("STABLE", "COMING_SOON", "INACTIVE"),
        help="Filter (not edit)",
    )

    # Scope
    p.add_argument(
        "--session",
        choices=(
            "REGULAR",
            "PRE_MARKET",
            "POST_MARKET",
            "OVER_NIGHT",
            "ALL",
            "NONE",
        ),
    )

    # Execution
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Default; explicit form for clarity",
    )
    p.add_argument("--apply", action="store_true", help="Write changes")
    p.add_argument("--show-full-diff", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    feeds = data["feeds"]
    print(f"Reading {config_path} ({len(feeds)} feeds)...")

    # Build plan
    if args.from_spec:
        plan = parse_yaml_spec(args.from_spec)
        print(f"Parsing {args.from_spec}... {len(plan)} operations.")
    else:
        try:
            plan = build_op_from_args(args)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    # Simulate
    result = simulate_plan(plan, feeds)

    # Plan summary
    print()
    print("Plan:")
    for i, planned in enumerate(plan, start=1):
        op_type = type(planned.op).__name__
        matched = result.matched_counts[i - 1]
        print(f"  [{i}] {op_type} → {matched} feed(s) matched")

    # Errors and warnings
    print()
    if result.errors:
        print(
            f"Validation: FAIL ({len(result.errors)} errors, "
            f"{len(result.warnings)} warnings)"
        )
        for e in result.errors:
            print(f"  ERROR: {e}")
    else:
        print(f"Validation: PASS (0 errors, {len(result.warnings)} warnings)")
    for w in result.warnings:
        print(f"  WARNING: {w.message}")

    # Diff
    print()
    is_apply = args.apply
    print_diff = (not is_apply) or (is_apply and not result.errors)
    if print_diff:
        print("Diff:")
        print(render_diff(result.changes, show_full=args.show_full_diff))

    summary = (
        f"Summary: {len(result.changes)} changes, "
        f"{len(result.errors)} errors, {len(result.warnings)} warnings."
    )
    if result.skipped_inactive:
        summary += (
            f" Skipped {result.skipped_inactive} INACTIVE feed(s) "
            f"(reactivate via --set-state to edit)."
        )
    print(summary)

    if not is_apply:
        print("[DRY RUN] No changes written. Re-run with --apply to write.")
        return 1 if result.errors else 0

    if result.errors:
        print("Refusing to write due to errors.", file=sys.stderr)
        return 1

    if not result.changes:
        print("No changes to write.")
        return 0

    new_raw = apply_changes(raw, result.changes)
    write_with_backup(str(config_path), new_raw, no_backup=args.no_backup)
    if not args.no_backup:
        print(f"Backup written: {config_path}.bak")
    print(f"Wrote {len(result.changes)} changes to {config_path}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
