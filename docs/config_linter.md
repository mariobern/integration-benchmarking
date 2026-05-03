# Config Linter (config_linter.py)

Lints `after.json` for structural mistakes, publisher-reference errors, schedule inconsistencies, and stale state. Pure stdlib — no ClickHouse or network access required. Exits non-zero when any **ERROR** finding is present so it can gate CI.

## Usage

```bash
# Default: diff mode against origin/main (auto-detected via git)
python3 tools/config-linter/config_linter.py --config after.json

# Diff against an explicit baseline file
python3 tools/config-linter/config_linter.py --config after.json --baseline before.json

# Diff against a different ref (e.g. develop)
python3 tools/config-linter/config_linter.py --config after.json --baseline-ref develop

# Force full lint (skip baseline)
python3 tools/config-linter/config_linter.py --config after.json --no-baseline

# JSON output
python3 tools/config-linter/config_linter.py --config after.json --format json

# Write results to file (format auto-detected from extension)
python3 tools/config-linter/config_linter.py --config after.json --output lint.json

# Treat warnings as errors (in diff mode applies to NEW warnings only)
python3 tools/config-linter/config_linter.py --config after.json --warnings-as-errors
```

## Arguments

| Argument               | Description                                                                                        | Required | Default       |
| ---------------------- | -------------------------------------------------------------------------------------------------- | -------- | ------------- |
| `--config`             | Path to `after.json` config file                                                                   | Yes      | —             |
| `--baseline`           | Path to baseline config file (overrides git auto-detect). Mutually exclusive with `--no-baseline`. | No       | (auto-detect) |
| `--baseline-ref`       | Git ref used for auto-detect. Ignored when `--baseline` or `--no-baseline` is provided.            | No       | `origin/main` |
| `--no-baseline`        | Force full lint, skipping baseline-diff mode entirely. Mutually exclusive with `--baseline`.       | No       | False         |
| `--format`             | Output format: `text` or `json`                                                                    | No       | `text`        |
| `--warnings-as-errors` | Exit 1 if any warning is present (in diff mode, applies to **new** warnings only)                  | No       | False         |
| `--output`             | Write findings to file (format auto-detected from extension)                                       | No       | —             |

## Default Behavior (Diff Mode)

By default the linter compares the current working-tree config against the version that existed at the merge-base of the current branch and `origin/main`, and reports only findings introduced by changes on the current branch. Pre-existing findings are silently suppressed.

The baseline is discovered automatically via:

1. `git rev-parse --is-inside-work-tree`
2. `git rev-parse <baseline-ref>` (default: `origin/main`)
3. `git merge-base HEAD <baseline-ref>` (must be different from HEAD)
4. `git show <merge-base>:<config-path>`

If any step fails, the linter prints `NOTE: baseline unavailable (<reason>); running full lint` to stderr and falls back to the legacy full-lint behavior.

### Auto-detect failure modes

| Situation                                             | `<reason>`                                      |
| ----------------------------------------------------- | ----------------------------------------------- |
| Not inside a git work tree                            | `not a git repository`                          |
| Baseline ref does not exist locally                   | `ref 'origin/main' not found`                   |
| Current `HEAD` is on the baseline ref (no divergence) | `on baseline ref, no diff to compute`           |
| Config path was not tracked at the merge-base         | `path 'after.json' not present at <merge-base>` |
| `git` binary not on PATH                              | `git command not available`                     |
| Baseline JSON fails to parse                          | `baseline JSON invalid: <error>`                |

### Diff-mode output

```
ERRORS (1 new):
  E004  Feed 1163 (Equity.US.NVDA/USD): minPublishers (5) >= publisher count (5), no fault tolerance

WARNINGS (1 new):
  W003  Feed 999 (Commodities.GCH6/USD): REGULAR schedule deviates from (commodity, GC) majority

Summary: 1 new errors, 1 new warnings (12 pre-existing findings suppressed)
```

When zero new findings are reported:

```
No new issues found. (12 pre-existing findings suppressed)
```

JSON output is unchanged in shape — a flat array of finding objects, just filtered. Pre-existing-count metadata appears only in text output.

### Comparison key

A finding is considered pre-existing when its `(rule_id, feed_id, symbol)` tuple matches any finding produced by linting the baseline. Message text is intentionally excluded from the key, so magnitude changes within a rule (e.g. a publisher count dropping further on E004) do not surface as new findings. If you want to address those, run with `--no-baseline` periodically.

**Diff-mode caveat for exchange-array rules:** E017, E018, E021, E023, E024, and E025 emit findings keyed by `(rule_id, None, None)` because they describe issues in the publishers or exchanges arrays rather than a specific feed. In diff mode, the suppression count is correct, but when multiple findings of the same rule co-fire, which specific finding is labeled "new" is non-deterministic.

## Exit Codes

- `0` — no errors (warnings allowed unless `--warnings-as-errors`)
- `1` — at least one **ERROR** finding (or any finding when `--warnings-as-errors`)

In diff mode, exit code reflects only **new** findings. Pre-existing findings never affect exit code.

## Rule Scope

- **INACTIVE feeds are skipped** by all publisher, schedule, hermes-id, and expiry checks. Only structural duplicate-ID/duplicate-symbol checks look at them.
- E010 runs on every non-INACTIVE feed. E011 runs on STABLE feeds only (it is a CI blocker).
- W003 runs on STABLE + COMING_SOON feeds (advisory; not a CI blocker unless `--warnings-as-errors`).
- E013 requires the linter's current UTC clock; it is evaluated against `datetime.now(timezone.utc)` at runtime.

## Errors

| ID   | Rule                                                                                                  | Scope                                                                         |
| ---- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| E001 | Duplicate `feedId`                                                                                    | all feeds                                                                     |
| E002 | Duplicate `symbol` within STABLE/COMING_SOON                                                          | active-pipeline feeds                                                         |
| E003 | References unknown `publisherId`                                                                      | non-INACTIVE (top-level and session-level)                                    |
| E004 | `minPublishers >= publisher count` (no headroom)                                                      | STABLE, non-exempt asset types                                                |
| E005 | STABLE feed with no publishers                                                                        | STABLE                                                                        |
| E006 | Non-equity feed has extended sessions                                                                 | non-INACTIVE, non-equity                                                      |
| E007 | Missing required field (`feedId`, `symbol`, `state`, `kind`, `metadata.asset_type`)                   | all feeds                                                                     |
| E008 | Session-level publisher not in top-level list                                                         | non-INACTIVE                                                                  |
| E009 | STABLE feed references a `.Test`-named publisher                                                      | STABLE                                                                        |
| E010 | Duplicate session in `marketSchedules`                                                                | non-INACTIVE                                                                  |
| E011 | Schedule inconsistency within asset group                                                             | STABLE only, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
| E012 | Duplicate `metadata.hermes_id`                                                                        | non-INACTIVE                                                                  |
| E013 | COMING_SOON futures past every `validTo`                                                              | COMING_SOON futures only                                                      |
| E014 | STABLE benchmarkable feed missing `benchmarkMapping`                                                  | STABLE, benchmarkable asset types, non-OVERNIGHT                              |
| E015 | `corporateActions` schema violation (missing fields, invalid formats)                                 | any feed with `corporateActions`                                              |
| E016 | Identifier date range overlap within same vendor/session                                              | non-INACTIVE, 2+ identifiers per vendor                                       |
| E017 | Duplicate `publisherId` in publishers array                                                           | publishers array                                                              |
| E018 | Duplicate publisher `name` in publishers array                                                        | publishers array                                                              |
| E019 | feed references `exchangeId` not in `exchanges[]` (dangling reference)                                | any feed                                                                      |
| E020 | session has no schedule source (no inline `marketSchedule`, no resolvable inheritance)                | any feed                                                                      |
| E021 | duplicate exchange tuple `(name, assetClass, assetSubclass, assetSector)` across distinct exchangeIds | exchanges array                                                               |
| E022 | invalid syntax in `scheduleOverrides.holidayOverrides[]` token                                        | any feed                                                                      |
| E023 | duplicate `exchangeId` value in `exchanges[]`                                                         | exchanges array                                                               |
| E024 | exchange entry missing required field (`exchangeId`/`name`/non-empty `sessions`)                      | exchanges array                                                               |
| E025 | unknown enum value for `assetClass`/`assetSubclass`/`assetSector`                                     | exchanges array                                                               |

## Warnings

| ID   | Rule                                                                                         | Scope                                                                                  |
| ---- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| W001 | US equity missing extended sessions (`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT`)                | STABLE US equities                                                                     |
| W002 | US equity using a non-`America/New_York` timezone                                            | STABLE US equities                                                                     |
| W003 | Schedule deviates from the asset-class majority                                              | STABLE + COMING_SOON, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
| W004 | COMING_SOON feed with no publishers                                                          | COMING_SOON                                                                            |
| W005 | `minPublishers` leaves only 1 headroom publisher                                             | STABLE, non-exempt                                                                     |
| W006 | Duplicate `publisherId` in feed                                                              | non-INACTIVE                                                                           |
| W007 | STABLE feed references a `TEST` key-type publisher                                           | STABLE                                                                                 |
| W009 | Unknown `corporateActions` event type (schema not validated)                                 | any feed with `corporateActions`                                                       |
| W010 | feed session has both inline `marketSchedule` and `exchangeId` (inline shadows exchange)     | any feed                                                                               |
| W011 | feed has `exchangeId` but every session has an inline `marketSchedule` (`exchangeId` unused) | any feed                                                                               |

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

## Notes on E017 / E018 (Publisher Uniqueness)

Both rules mirror invariants the Rust governance tool enforces in `diff_publishers`. The governance tool aborts the proposal pipeline with `Error: publisher ids are not unique` (or `... names are not unique`); catching the same condition in our linter surfaces a readable error message before the Rust tool's stack trace reaches CI.

- **E017** fires when two entries in the top-level `publishers` array share the same `publisherId`. The `feed_id` slot of the finding holds the duplicated id.
- **E018** fires when two entries share the same `name` (case-sensitive). The `symbol` slot of the finding holds the duplicated name.

Publishers missing either field are skipped by these checks (a separate schema rule would be the right place to flag missing fields).

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
