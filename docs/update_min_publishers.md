# Min Publishers Enforcement (update_min_publishers.py)

Enforces minimum `minPublishers` values in `after.json` based on `allowedPublisherIds` count. Reduces single-publisher price bias risk by requiring at least 2-3 publishers for feeds with enough publisher coverage.

## Usage

```bash
# Dry run (preview changes without writing)
python3 update_min_publishers.py --config after.json --dry-run

# Apply changes (creates backup at after.json.bak)
python3 update_min_publishers.py --config after.json

# Filter to specific asset classes only
python3 update_min_publishers.py --config after.json --asset-classes fx commodity

# Custom thresholds
python3 update_min_publishers.py --config after.json --min-publisher-floor 4 --publisher-tier-cutoff 8
```

## Arguments

| Argument                  | Description                                                                 | Required | Default                      |
| ------------------------- | --------------------------------------------------------------------------- | -------- | ---------------------------- |
| `--config`                | Path to after.json config file                                              | Yes      | —                            |
| `--dry-run`               | Preview changes without writing to file                                     | No       | False                        |
| `--output-csv`            | Path for the change report CSV                                              | No       | `min_publishers_changes.csv` |
| `--asset-classes`         | Explicit allowlist of asset types to process (overrides default exclusions) | No       | —                            |
| `--min-publisher-floor`   | Minimum publisher count to start enforcing                                  | No       | 5                            |
| `--publisher-tier-cutoff` | Publisher count boundary for tier 2 vs tier 3                               | No       | 7                            |

## Rule Engine

| `allowedPublisherIds` count | Target `minPublishers` | Status                   |
| --------------------------- | ---------------------- | ------------------------ |
| 0-1                         | No change              | `NEEDS_ATTENTION`        |
| 2-4                         | No change              | `SKIPPED_LOW_PUBLISHERS` |
| 5-6                         | 2                      | `UPDATED`                |
| 7+                          | 3                      | `UPDATED`                |

The lower boundary (default: 5) is configurable via `--min-publisher-floor`. The upper boundary (default: 7) is configurable via `--publisher-tier-cutoff`.

**No-downgrade rule:** The script only increases `minPublishers`. If a feed already has `minPublishers` >= the target, it is skipped (`SKIPPED_EQUAL` or `SKIPPED_HIGHER`).

## What Gets Modified

Only **top-level** `minPublishers` for eligible feeds. Session-level `minPublishers` inside `marketSchedules` is never touched.

### Eligibility Filters

1. **State:** `STABLE` only — `COMING_SOON` and `INACTIVE` feeds are skipped
2. **Asset type exclusion:** Default exclusion list: `funding-rate`, `crypto-redemption-rate`, `nav`, `custom`, `crypto-index`, `kalshi`
3. **Asset type override:** `--asset-classes` acts as an explicit allowlist — only listed types are processed; all others are skipped (bypasses default exclusions)
4. **Extended-hours exclusion:** Feeds with `PRE_MARKET`, `POST_MARKET`, or `OVER_NIGHT` sessions in `marketSchedules` are entirely skipped

### Why extended-hours equities are excluded

Extended-hours equities have `minPublishers` at two levels — top-level (intentionally set to 1) and per-session inside `marketSchedules` (already correct). Modifying the top-level value could interfere with the session override mechanism. Their per-session values are managed by `update_config_from_summary.py`.

## CSV Report

Written in both dry-run and write mode for audit trail.

**Columns:** `feed_id, symbol, asset_type, old_min_publishers, new_min_publishers, allowed_publisher_count, status`

**Status values:**

| Status                   | Meaning                                      |
| ------------------------ | -------------------------------------------- |
| `UPDATED`                | minPublishers was increased                  |
| `SKIPPED_LOW_PUBLISHERS` | 2-4 publishers, left at current value        |
| `SKIPPED_EQUAL`          | Existing minPublishers already equals target |
| `SKIPPED_HIGHER`         | Existing minPublishers exceeds target        |
| `NEEDS_ATTENTION`        | Fewer than 2 allowedPublisherIds             |

## Output

### Dry-run mode

```
Scanning after.json...
  STABLE feeds: 830
  Excluded (asset type): 34 (crypto-redemption-rate: 15, custom: 5, funding-rate: 11, nav: 3)
  Excluded (extended-hours): 81
  Needs attention (<2 publishers): 0
  Skipped (2-4 publishers): 44
  Eligible for rule evaluation: 671

Changes:
  19 feeds: minPublishers 1 -> 2
  32 feeds: minPublishers 1 -> 3
  14 feeds: minPublishers 2 -> 3
  606 feeds: skipped (already >= target)

[DRY RUN] No changes written.
Report: min_publishers_changes.csv
```

### Write mode

```
Scanning after.json...
  ...
Changes:
  ...
Report: min_publishers_changes.csv
Backup: after.json.bak
Updated 65 feeds in after.json
```

## Surgical JSON Modification

Like `update_lazer_symbols.py` and `update_config_from_summary.py`, this script uses regex-based surgical replacements to preserve the original protobuf-JSON formatting of `after.json`. Only `minPublishers` values are changed; all other fields and formatting are preserved exactly.

For feeds with `minPublishers` in both `marketSchedules` and at the top level, the script locates the end of the `marketSchedules` array by bracket-depth tracking and applies the regex substitution only to the portion of the feed block **after** `marketSchedules` ends. This ensures session-level values are never modified.

## Safety Features

- `--dry-run` mode previews all changes without writing
- Backup created automatically before overwriting (`after.json.bak`)
- Only increases `minPublishers` — never downgrades existing values
- Extended-hours equities entirely excluded from modification
- CSV audit trail written in both modes
- **Idempotent:** running the script twice produces no changes on the second run

## Running Tests

```bash
pytest tests/test_min_publishers.py -v
```

37 tests covering rule engine, eligibility filters, JSON surgery, CSV report, console output, and CLI integration.
