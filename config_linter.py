"""Config linter CLI for after.json validation.

Usage:
    python3 config_linter.py --config after.json
    python3 config_linter.py --config after.json --baseline before.json
    python3 config_linter.py --config after.json --baseline-ref develop
    python3 config_linter.py --config after.json --no-baseline
    python3 config_linter.py --config after.json --format json
    python3 config_linter.py --config after.json --output lint_results.json
    python3 config_linter.py --config after.json --warnings-as-errors
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.baseline_lookup import lookup_baseline_config
from lib.config_lint import LintFinding, lint_config, lint_config_diff

# ANSI color codes
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _supports_color() -> bool:
    """Check if stdout supports ANSI colors."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _format_text(
    findings: list[LintFinding],
    use_color: bool,
    pre_existing_count: Optional[int] = None,
) -> str:
    """Format findings as human-readable text.

    pre_existing_count: None = full lint mode (today's labels). An int
    means diff mode: the labels read 'N new' instead of 'N found' and
    the summary line tacks on the suppressed count.
    """
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]
    lines: list[str] = []

    label = "new" if pre_existing_count is not None else "found"

    if errors:
        header = f"ERRORS ({len(errors)} {label}):"
        if use_color:
            header = f"{_RED}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in errors:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_RED}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if warnings:
        header = f"WARNINGS ({len(warnings)} {label}):"
        if use_color:
            header = f"{_YELLOW}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in warnings:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_YELLOW}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if not errors and not warnings:
        if pre_existing_count is not None and pre_existing_count > 0:
            lines.append(
                f"No new issues found. ({pre_existing_count} pre-existing"
                f" findings suppressed)"
            )
        else:
            lines.append("No issues found.")
    else:
        if pre_existing_count is not None:
            summary = (
                f"Summary: {len(errors)} new errors, {len(warnings)} new"
                f" warnings ({pre_existing_count} pre-existing findings"
                f" suppressed)"
            )
        else:
            summary = f"Summary: {len(errors)} errors, {len(warnings)} warnings"
        lines.append(summary)

    return "\n".join(lines)


def _format_json(findings: list[LintFinding]) -> str:
    """Format findings as JSON array."""
    return json.dumps(
        [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "feed_id": f.feed_id,
                "symbol": f.symbol,
            }
            for f in findings
        ],
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint after.json config for common errors"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Treat warnings as errors (exit 1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write findings to file (format auto-detected: .json -> JSON, else text)",
    )
    parser.add_argument(
        "--baseline-ref",
        default="origin/main",
        help=(
            "Git ref used for baseline auto-detect (default: origin/main)."
            " Ignored when --baseline or --no-baseline is provided."
        ),
    )
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--baseline",
        type=Path,
        help=(
            "Path to baseline config (overrides git auto-detect). When"
            " provided, only findings absent from the baseline are reported."
        ),
    )
    baseline_group.add_argument(
        "--no-baseline",
        action="store_true",
        help="Force full lint and bypass baseline diff mode entirely.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(config, dict):
        print(
            f"ERROR: Config file {config_path} must contain a JSON object,"
            f" got {type(config).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve baseline.
    baseline_config: Optional[dict] = None
    if args.no_baseline:
        baseline_config = None
    elif args.baseline is not None:
        if not args.baseline.exists():
            print(
                f"ERROR: Baseline file not found: {args.baseline}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            with open(args.baseline) as f:
                baseline_config = json.load(f)
        except json.JSONDecodeError as e:
            print(
                f"ERROR: Invalid JSON in baseline {args.baseline}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(baseline_config, dict):
            print(
                f"ERROR: Baseline file {args.baseline} must contain a JSON"
                f" object, got {type(baseline_config).__name__}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        # Default mode: try git auto-detect.
        baseline_config, reason = lookup_baseline_config(
            config_path=str(config_path),
            baseline_ref=args.baseline_ref,
        )
        if baseline_config is None:
            print(
                f"NOTE: baseline unavailable ({reason}); running full lint",
                file=sys.stderr,
            )

    if baseline_config is not None and not isinstance(baseline_config, dict):
        print(
            f"ERROR: Baseline config must be a JSON object,"
            f" got {type(baseline_config).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run lint (diff or full).
    if baseline_config is not None:
        # Thread the same `now` into both calls so E013 (time-dependent)
        # is evaluated against a single instant in both runs.
        now = datetime.now(timezone.utc)
        findings = lint_config_diff(config, baseline_config, now=now)
        pre_existing_count = len(lint_config(baseline_config, now=now))
    else:
        findings = lint_config(config)
        pre_existing_count = None

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if args.output:
        if args.output.suffix.lower() == ".json":
            content = _format_json(findings)
        else:
            content = _format_text(
                findings, use_color=False, pre_existing_count=pre_existing_count
            )
        try:
            args.output.write_text(content)
        except OSError as e:
            print(f"ERROR: Cannot write to {args.output}: {e}", file=sys.stderr)
            sys.exit(1)

        if not errors and not warnings:
            if pre_existing_count is not None and pre_existing_count > 0:
                print(
                    f"No new issues found. Wrote results to {args.output}"
                    f" ({pre_existing_count} pre-existing findings suppressed)"
                )
            else:
                print(f"No issues found. Wrote results to {args.output}")
        else:
            label = "new " if pre_existing_count is not None else ""
            print(
                f"Wrote {len(errors)} {label}errors,"
                f" {len(warnings)} {label}warnings to {args.output}"
            )
    else:
        if args.format == "json":
            print(_format_json(findings))
        else:
            print(
                _format_text(
                    findings,
                    use_color=_supports_color(),
                    pre_existing_count=pre_existing_count,
                )
            )

    if errors:
        sys.exit(1)
    if args.warnings_as_errors and warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
