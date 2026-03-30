"""Config linter CLI for after.json validation.

Usage:
    python3 config_linter.py --config after.json
    python3 config_linter.py --config after.json --format json
    python3 config_linter.py --config after.json --warnings-as-errors
"""

import argparse
import json
import sys
from pathlib import Path

from lib.config_lint import LintFinding, lint_config

# ANSI color codes
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _supports_color() -> bool:
    """Check if stdout supports ANSI colors."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _format_text(findings: list[LintFinding], use_color: bool) -> str:
    """Format findings as human-readable text."""
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]
    lines: list[str] = []

    if errors:
        header = f"ERRORS ({len(errors)} found):"
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
        header = f"WARNINGS ({len(warnings)} found):"
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
        lines.append("No issues found.")
    else:
        lines.append(f"Summary: {len(errors)} errors, {len(warnings)} warnings")

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

    findings = lint_config(config)

    if args.format == "json":
        print(_format_json(findings))
    else:
        print(_format_text(findings, use_color=_supports_color()))

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if errors:
        sys.exit(1)
    if args.warnings_as_errors and warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
