# Config Linter (config_linter.py)

Lints `after.json` for structural mistakes, publisher-reference errors, schedule inconsistencies, and stale state. Pure stdlib — no ClickHouse or network access required. Exits non-zero when any **ERROR** finding is present so it can gate CI.

## Usage

```bash
# Basic lint (colored text output to terminal)
python3 config_linter.py --config after.json

# JSON output to terminal
python3 config_linter.py --config after.json --format json

# Write results to file (format auto-detected from extension)
python3 config_linter.py --config after.json --output lint_results.json
python3 config_linter.py --config after.json --output lint_results.txt

# Treat warnings as errors (exit 1 on warnings)
python3 config_linter.py --config after.json --warnings-as-errors

# CI usage: JSON output + fail on warnings
python3 config_linter.py --config after.json --output lint.json --warnings-as-errors
```

## Arguments

| Argument               | Description                                              | Required | Default |
| ---------------------- | -------------------------------------------------------- | -------- | ------- |
| `--config`             | Path to `after.json` config file                         | Yes      | —       |
| `--format`             | Output format: `text` or `json`                          | No       | `text`  |
| `--warnings-as-errors` | Exit 1 if any warning is present (in addition to errors) | No       | False   |

## Exit Codes

- `0` — no errors (warnings allowed unless `--warnings-as-errors`)
- `1` — at least one **ERROR** finding (or any finding when `--warnings-as-errors`)

## Rule Scope

- **INACTIVE feeds are skipped** by all publisher, schedule, hermes-id, and expiry checks. Only structural duplicate-ID/duplicate-symbol checks look at them.
- E010 runs on every non-INACTIVE feed. E011 runs on STABLE feeds only (it is a CI blocker).
- W003 runs on STABLE + COMING_SOON feeds (advisory; not a CI blocker unless `--warnings-as-errors`).
- E013 requires the linter's current UTC clock; it is evaluated against `datetime.now(timezone.utc)` at runtime.

## Errors

| ID   | Rule                                                                                | Scope                                                                         |
| ---- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| E001 | Duplicate `feedId`                                                                  | all feeds                                                                     |
| E002 | Duplicate `symbol` within STABLE/COMING_SOON                                        | active-pipeline feeds                                                         |
| E003 | References unknown `publisherId`                                                    | non-INACTIVE (top-level and session-level)                                    |
| E004 | `minPublishers >= publisher count` (no headroom)                                    | STABLE, non-exempt asset types                                                |
| E005 | STABLE feed with no publishers                                                      | STABLE                                                                        |
| E006 | Non-equity feed has extended sessions                                               | non-INACTIVE, non-equity                                                      |
| E007 | Missing required field (`feedId`, `symbol`, `state`, `kind`, `metadata.asset_type`) | all feeds                                                                     |
| E008 | Session-level publisher not in top-level list                                       | non-INACTIVE                                                                  |
| E009 | STABLE feed references a `.Test`-named publisher                                    | STABLE                                                                        |
| E010 | Duplicate session in `marketSchedules`                                              | non-INACTIVE                                                                  |
| E011 | Schedule inconsistency within asset group                                           | STABLE only, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
| E012 | Duplicate `metadata.hermes_id`                                                      | non-INACTIVE                                                                  |
| E013 | COMING_SOON futures past every `validTo`                                            | COMING_SOON futures only                                                      |
| E014 | STABLE benchmarkable feed missing `benchmarkMapping`                                | STABLE, benchmarkable asset types, non-OVERNIGHT                              |
| E015 | `corporateActions` schema violation (missing fields, invalid formats)               | any feed with `corporateActions`                                              |
| E016 | Identifier date range overlap within same vendor/session                            | non-INACTIVE, 2+ identifiers per vendor                                       |

## Warnings

| ID   | Rule                                                                          | Scope                                                                                  |
| ---- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| W001 | US equity missing extended sessions (`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT`) | STABLE US equities                                                                     |
| W002 | US equity using a non-`America/New_York` timezone                             | STABLE US equities                                                                     |
| W003 | Schedule deviates from the asset-class majority                               | STABLE + COMING_SOON, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
| W004 | COMING_SOON feed with no publishers                                           | COMING_SOON                                                                            |
| W005 | `minPublishers` leaves only 1 headroom publisher                              | STABLE, non-exempt                                                                     |
| W006 | Duplicate `publisherId` in feed                                               | non-INACTIVE                                                                           |
| W007 | STABLE feed references a `TEST` key-type publisher                            | STABLE                                                                                 |
| W009 | Unknown `corporateActions` event type (schema not validated)                  | any feed with `corporateActions`                                                       |

### E011 vs W003

Both flag schedule drift, but with different scopes and severity:

- **E011 (ERROR)** is the CI-blocking rule. It fires when two **STABLE** feeds in the same group have any distinct schedule signature. Groups are `(asset_type, equity_listing_prefix, futures_root?)` for equities and `(asset_type, futures_root?)` for everything else. Equity futures are sub-grouped by both listing prefix and root. Comparison is per-session within a group; a feed missing a session is not penalized.
- **W003 (WARNING)** is the soft heads-up. It fires on minority deviation from the group majority across **STABLE + COMING_SOON** feeds. It uses the same group key as E011, including futures sub-grouping. Comparison is per-session within a group; a feed missing a session is not penalized.

They intentionally overlap on STABLE feeds. W003 additionally surfaces drift that E011 cannot see — namely COMING_SOON spot or futures feeds that disagree with their STABLE peers — without blocking CI.

## Asset Types Exempt from E004 / W005

Single-source asset types where `minPublishers >= publisher count` is acceptable:

- `funding-rate`
- `custom`
- `crypto-redemption-rate`
- `nav`
- `crypto-index`
- `kalshi`

These exemptions apply only to the publisher-count headroom rules, not to any other check.

## Notes on E013 (Expired COMING_SOON Futures)

A COMING_SOON futures feed is considered expired if **every** `validTo` timestamp found under `marketSchedules[*].benchmarkMapping.*.identifiers[*].validTo` is earlier than the current UTC time. Feeds with no `validTo` identifiers are skipped — E013 only fires when there is evidence that every mapped contract has already rolled off. The fix is usually to flip the feed to `INACTIVE`.

## Notes on E014 (Benchmark Mapping)

Benchmarkable asset types are: `equity`, `fx`, `metal`, `commodity`, `rates`. All other asset types are skipped. The `OVER_NIGHT` session is always exempt since it uses publisher 32 peer comparison rather than Datascope benchmarks.

## Notes on E015 / W009 (Corporate Actions)

E015 validates the full schema for known event types. Currently the only known type is `SPLIT`. When a new event type is added to `after.json` before the linter is updated, W009 fires as a warning instead of E015, allowing the config change to pass CI while signaling the linter needs updating.

To add support for a new event type, add an entry to `_CORPORATE_ACTION_SCHEMAS` in `lib/config_lint.py` and add the event type string to `_KNOWN_EVENT_TYPES`.

### SPLIT schema

| Field                         | Location                           | Format                  |
| ----------------------------- | ---------------------------------- | ----------------------- |
| `adjustmentFactorNumerator`   | top-level                          | positive integer string |
| `adjustmentFactorDenominator` | top-level                          | positive integer string |
| `rejectionThresholdBips`      | top-level                          | positive integer string |
| `rejectionWindow`             | top-level                          | `N.Ns` duration string  |
| `exDate`                      | `activation.usEquityExDate.exDate` | `YYYY-MM-DD` date       |

## Notes on E016 (Identifier Continuity)

Checks for date range overlaps when a vendor has multiple identifiers in a single session (e.g., futures contract rolls). Identifiers are sorted by `validFrom` and consecutive pairs are checked. A non-last identifier missing `validTo` is flagged because it creates an unbounded range that logically conflicts with its successor. The last identifier in the chain may omit `validTo` (open-ended current contract).

## Output Formats

### Text (default)

```
ERRORS (3 found):
  E009  Feed 458 (Crypto.JITOSOL/USD): STABLE feed references .Test-suffixed publishers: [49]
  E012  Feed 964 (Equity.US.APTV/USD): hermes_id 'abc...' duplicated across feedIds: 964, 3126
  E013  Feed 2973 (Commodities.ALH6/USD): COMING_SOON futures feed has expired (latest validTo: 2026-03-27T17:00:00+00:00); change state to INACTIVE

WARNINGS (1 found):
  W003  Feed 1775 (Equity.US.XLK/USD): REGULAR schedule deviates from (equity, US) majority

Summary: 3 errors, 1 warnings
```

### JSON

A flat array of finding objects:

```json
[
  {
    "rule_id": "E009",
    "severity": "ERROR",
    "message": "STABLE feed references .Test-suffixed publishers: [49]",
    "feed_id": 458,
    "symbol": "Crypto.JITOSOL/USD"
  }
]
```
