# Config Linter (Super-Linter) Design Spec

## Overview

A config linter for `after.json` that validates feed definitions, publisher references,
schedule consistency, and business rules. Runs as a CLI tool locally and as a Docker step
in the `pyth-lazer-governance` CI pipeline.

## Problem

Config changes to `after.json` are reviewed manually in PRs. Common errors — duplicate IDs,
orphaned publisher references, unsafe `minPublishers` values, wrong schedules — are easy to
miss in a 74KB JSON file. There is no automated validation today.

## Goals

- Catch config errors before they reach production
- Two-severity model: errors block PRs, warnings are informational
- CLI for local use by the team (integration-benchmarking + research repos)
- Docker image for governance CI integration
- Extensible rule set that grows over time

## Non-Goals

- Schema migration or config transformation (handled by existing `update_*.py` scripts)
- ClickHouse connectivity or benchmark evaluation
- Validation of `before.json` or `transaction.json`
- Diff-based validation (comparing before/after) — lints `after.json` in isolation

## Architecture

```
integration-benchmarking/
  config_linter.py            # Thin CLI wrapper (arg parsing, output formatting)
  lib/config_lint.py          # All lint rule logic
  lib/symbol_utils.py         # Shared symbol helpers (futures detection, extracted from sql_filters.py)
  tests/test_config_lint.py   # Unit tests
  Dockerfile.linter           # Minimal Docker image for CI

pyth-lazer-governance/
  .github/workflows/ci-pr.yml  # Add linter step (consumes Docker image)
```

Follows the existing project pattern: thin CLI delegates to `lib/`.

## Key Data Model Notes

### Asset Type vs. Symbol Prefix

`after.json` uses `metadata.asset_type: "equity"` for all equities regardless of region.
US equities are identified by the symbol prefix `Equity.US.` (e.g., `Equity.US.AAPL/USD`).
Non-US equities use other prefixes (`Equity.GB.`, `Equity.JP.`, etc.). Rules that apply
specifically to US equities (W001, W002) must use symbol prefix matching, not `asset_type`.

### Missing `allowedPublisherIds`

Approximately 36% of feeds (mostly COMING_SOON and INACTIVE) omit the `allowedPublisherIds`
field entirely. A missing field is treated as equivalent to an empty list (`[]`). All
publisher-related rules use `.get("allowedPublisherIds", [])` for null safety.

### Session-Level Publisher Fields

Extended-hours feeds (81 feeds with PRE_MARKET/POST_MARKET/OVER_NIGHT sessions) have their
own `allowedPublisherIds` and `minPublishers` within each `marketSchedules` entry. These
session-level fields must be validated independently from the top-level fields. Example:
a feed may have 10 top-level publishers but a session entry with `minPublishers: 100` and
only 6 session-level publishers — a clear misconfiguration.

### Single-Publisher Feed Exemptions

Feeds with `asset_type` in `funding-rate`, `custom`, `crypto-redemption-rate`, `nav`,
`crypto-index`, `kalshi` are exempt from E004 (minPublishers headroom) because they are
intentionally single-source feeds where `minPublishers == 1` with 1 publisher is valid.
This matches the `DEFAULT_EXCLUDED_ASSET_TYPES` pattern in `lib/min_publishers.py`.

## Lint Rules

### Errors (exit code 1, block PR)

| ID   | Name                              | Description                                                                       | Applies to          |
| ---- | --------------------------------- | --------------------------------------------------------------------------------- | ------------------- |
| E001 | duplicate-feed-id                 | Two feeds share the same `feedId`                                                 | All feeds           |
| E002 | duplicate-symbol                  | Two STABLE or COMING_SOON feeds share the same `symbol`                           | STABLE, COMING_SOON |
| E003 | invalid-publisher-ref             | `allowedPublisherIds` (top-level or session-level) references unknown publisherId | All feeds           |
| E004 | min-publishers-exceeds-count      | `minPublishers >= len(allowedPublisherIds)` at top-level or session-level         | STABLE (non-exempt) |
| E005 | stable-no-publishers              | STABLE feed with missing or empty top-level `allowedPublisherIds`                 | STABLE              |
| E006 | non-equity-extended-session       | Non-equity feed has PRE_MARKET, POST_MARKET, or OVER_NIGHT sessions               | All feeds           |
| E007 | missing-required-fields           | Feed missing `feedId`, `symbol`, `state`, `kind`, or `metadata.asset_type`        | All feeds           |
| E008 | session-publisher-not-in-toplevel | Session-level `allowedPublisherIds` contains IDs not in top-level list            | All feeds           |

### Warnings (exit code 0, unless `--warnings-as-errors`)

| ID   | Name                        | Description                                                               | Applies to          |
| ---- | --------------------------- | ------------------------------------------------------------------------- | ------------------- |
| W001 | equity-missing-sessions     | STABLE US equity (`Equity.US.` prefix) with incomplete extended-hours set | STABLE US equity    |
| W002 | schedule-timezone-mismatch  | US equity (`Equity.US.`) using non-`America/New_York` timezone            | STABLE US equity    |
| W003 | schedule-deviation          | Feed's schedule differs from majority of its asset class (futures exempt) | STABLE              |
| W004 | coming-soon-no-publishers   | COMING_SOON feed with missing or empty `allowedPublisherIds`              | COMING_SOON         |
| W005 | high-min-publishers-ratio   | STABLE feed where `minPublishers` leaves only 1 headroom (top or session) | STABLE (non-exempt) |
| W006 | duplicate-publisher-in-feed | Same publisherId appears twice in a feed's `allowedPublisherIds`          | All feeds           |
| W007 | stable-test-publisher       | STABLE feed references a publisher with `keyType: "TEST"`                 | STABLE              |

### State Scoping

| State       | Rules applied                         |
| ----------- | ------------------------------------- |
| STABLE      | All rules (E001-E008, W001-W007)      |
| COMING_SOON | E001-E003, E006-E008, W004, W006      |
| INACTIVE    | E001, E007 only (duplicates + schema) |

## Core Module: `lib/config_lint.py`

### Data Model

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class LintFinding:
    rule_id: str             # "E001", "W003", etc.
    severity: str            # "ERROR" or "WARNING"
    message: str             # Human-readable description
    feed_id: Optional[int]   # Feed that triggered the finding (None for global rules)
    symbol: Optional[str]    # Symbol of the feed (for context)
```

### Functions

```python
def lint_config(config: dict) -> list[LintFinding]:
    """Orchestrator. Takes the full parsed after.json root object.
    Extracts feeds and publishers, calls all checkers, returns combined findings."""

def check_duplicates(feeds: list[dict]) -> list[LintFinding]:
    """E001: duplicate feedId, E002: duplicate symbol (STABLE/COMING_SOON)."""

def check_schema(feeds: list[dict]) -> list[LintFinding]:
    """E007: missing required fields."""

def check_publishers(
    feeds: list[dict], publishers: list[dict]
) -> list[LintFinding]:
    """E003: invalid publisher ref (top-level + session-level),
    E004: minPublishers >= count (top-level + session-level, non-exempt),
    E005: stable no publishers,
    E008: session publisher not in top-level list,
    W004: coming_soon no publishers,
    W005: high ratio (top-level + session-level),
    W006: duplicate publisher in feed,
    W007: stable feed referencing TEST publisher."""

def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006: non-equity extended session, W001: US equity missing sessions,
    W002: US equity timezone mismatch, W003: schedule deviation (futures exempt)."""
```

### Shared Symbol Utilities: `lib/symbol_utils.py`

Extracted from `lib/sql_filters.py` to avoid pulling in ClickHouse dependencies:

```python
def is_futures_symbol(symbol: str) -> bool:
    """Detect futures contracts by [ROOT][MONTH_CODE][YEAR_DIGIT] pattern."""

def is_us_equity(feed: dict) -> bool:
    """True if symbol starts with 'Equity.US.'"""
```

Both `sql_filters.py` and `config_lint.py` import from this shared module.

### Schedule Majority Detection (W003)

For each `metadata.asset_type`, collect all `marketSchedules` configurations from STABLE
feeds. Determine the majority schedule (by frequency). Flag any STABLE feed that deviates,
unless it's a futures contract (detected by `is_futures_symbol`). If an asset class has
only one feed, no deviation is possible — skip.

## CLI: `config_linter.py`

```
python3 config_linter.py --config after.json [--format text|json] [--warnings-as-errors]
```

### Arguments

| Flag                   | Default  | Description                       |
| ---------------------- | -------- | --------------------------------- |
| `--config`             | required | Path to `after.json`              |
| `--format`             | `text`   | Output format: `text` or `json`   |
| `--warnings-as-errors` | `false`  | Treat warnings as errors (exit 1) |

### Exit Codes

| Code | Meaning                              |
| ---- | ------------------------------------ |
| 0    | Clean, or warnings only              |
| 1    | Errors found (or warnings with flag) |

### Text Output Format

```
ERRORS (3 found):
  E001  feedId 327 is duplicated (feeds[42], feeds[1847])
  E004  Feed 1163 (Equity.US.AAPL/USD): minPublishers (5) >= publisher count (5)
  E005  Feed 892 (FX.EUR/USD): STABLE with no publishers

WARNINGS (2 found):
  W001  Feed 1163 (Equity.US.AAPL/USD): STABLE US equity missing POST_MARKET session
  W005  Feed 340 (FX.GBP/USD): minPublishers (4) leaves only 1 headroom (5 publishers)

Summary: 3 errors, 2 warnings
```

Errors in red, warnings in yellow (when terminal supports color).

### JSON Output Format

```json
[
  {
    "rule_id": "E001",
    "severity": "ERROR",
    "message": "feedId 327 is duplicated",
    "feed_id": 327,
    "symbol": null
  }
]
```

## Docker Image: `Dockerfile.linter`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY config_linter.py .
COPY lib/__init__.py lib/
COPY lib/config_lint.py lib/
COPY lib/symbol_utils.py lib/
ENTRYPOINT ["python3", "config_linter.py"]
```

Zero external dependencies — pure Python stdlib. Published to
`ghcr.io/pyth-network/config-linter`, tagged by version.

## Governance CI Integration

Add to `pyth-lazer-governance/.github/workflows/ci-pr.yml` after proposal detection:

```yaml
- name: Lint after.json
  run: |
    docker run --rm -v ${{ github.workspace }}:/repo \
      ghcr.io/pyth-network/config-linter:latest \
      --config /repo/${{ env.PROPOSAL_DIR }}/after.json \
      --format text --warnings-as-errors
```

Findings appear in the CI log. Errors fail the PR check. This step runs alongside
the existing `pyth-lazer-governance-tool diff` step.

## Testing

### Unit Tests (`tests/test_config_lint.py`)

One test per rule using minimal JSON fixtures:

- **E001**: config with two feeds sharing feedId
- **E002**: two STABLE feeds with same symbol; INACTIVE duplicate should not trigger
- **E003**: feed referencing publisherId not in publishers array (top-level + session-level)
- **E004**: STABLE feed with minPublishers == len(allowedPublisherIds); exempt asset type passes
- **E005**: STABLE feed with empty/missing allowedPublisherIds
- **E006**: FX feed with PRE_MARKET session
- **E007**: feed missing `kind` field
- **E008**: session-level publisher not in top-level list
- **W001**: STABLE US equity with only REGULAR session
- **W002**: US equity with UTC timezone
- **W003**: commodity with different schedule from majority; futures exempt
- **W004**: COMING_SOON with missing allowedPublisherIds
- **W005**: STABLE feed with minPublishers = count - 1 (top-level + session-level)
- **W006**: feed with duplicate publisherId in allowedPublisherIds
- **W007**: STABLE feed referencing TEST-keyed publisher

### Edge Cases

- Empty feeds array (should return clean)
- INACTIVE feeds skip most rules
- Futures symbol detection (month codes, year digits)
- Feed with minPublishers = 0 (should not trigger E004)
- Single feed in asset class (no majority to deviate from for W003)
- Feed with missing `allowedPublisherIds` field (null-safe handling)
- Non-US equity with non-NYC timezone (should NOT trigger W002)
- Session-level minPublishers violation (e.g. ARKB `minPublishers: 100`)

### Coverage Target

80%+ line coverage on `lib/config_lint.py`.

## Extensibility

Adding a new rule:

1. Add the check to the appropriate `check_*` function in `lib/config_lint.py`
2. Document the rule ID in the table above
3. Add unit test(s) in `tests/test_config_lint.py`

No registration, decorators, or plugin system needed.

## Dependencies

- **Runtime**: Python 3.11+ stdlib only (json, re, dataclasses, argparse, sys)
- **Test**: pytest
- **CI**: Docker

## Future Considerations

These are explicitly out of scope for v1 but noted for future iterations:

- Diff-based rules (comparing `before.json` to `after.json` for state transition validation)
- PR comment integration (post findings as GitHub PR comment instead of just CI log)
- Rule suppression (inline `# noqa: E001` equivalent for known exceptions)
- Config file for rule customization (disable specific rules, adjust thresholds)
