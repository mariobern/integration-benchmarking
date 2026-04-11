# Config Linter (config_linter.py)

Lints `after.json` for structural mistakes, publisher-reference errors, schedule inconsistencies, and stale state. Pure stdlib — no ClickHouse or network access required. Exits non-zero when any **ERROR** finding is present so it can gate CI.

## Usage

```bash
# Human-readable output
python3 config_linter.py --config after.json

# Machine-readable output (array of findings)
python3 config_linter.py --config after.json --format json

# Treat warnings as errors (strict mode)
python3 config_linter.py --config after.json --warnings-as-errors
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
- E010/E011 are schedule-integrity checks that run on every non-INACTIVE feed.
- E013 requires the linter's current UTC clock; it is evaluated against `datetime.now(timezone.utc)` at runtime.

## Errors

| ID   | Rule                                                                                | Scope                                                  |
| ---- | ----------------------------------------------------------------------------------- | ------------------------------------------------------ |
| E001 | Duplicate `feedId`                                                                  | all feeds                                              |
| E002 | Duplicate `symbol` within STABLE/COMING_SOON                                        | active-pipeline feeds                                  |
| E003 | References unknown `publisherId`                                                    | non-INACTIVE (top-level and session-level)             |
| E004 | `minPublishers >= publisher count` (no headroom)                                    | STABLE, non-exempt asset types                         |
| E005 | STABLE feed with no publishers                                                      | STABLE                                                 |
| E006 | Non-equity feed has extended sessions                                               | non-INACTIVE, non-equity                               |
| E007 | Missing required field (`feedId`, `symbol`, `state`, `kind`, `metadata.asset_type`) | all feeds                                              |
| E008 | Session-level publisher not in top-level list                                       | non-INACTIVE                                           |
| E009 | STABLE feed references a `.Test`-named publisher                                    | STABLE                                                 |
| E010 | Duplicate session in `marketSchedules`                                              | non-INACTIVE                                           |
| E011 | Schedule inconsistency within asset group                                           | non-INACTIVE, grouped by `asset_type` (+ futures root) |
| E012 | Duplicate `metadata.hermes_id`                                                      | non-INACTIVE                                           |
| E013 | COMING_SOON futures past every `validTo`                                            | COMING_SOON futures only                               |

## Warnings

| ID   | Rule                                                                          | Scope               |
| ---- | ----------------------------------------------------------------------------- | ------------------- |
| W001 | US equity missing extended sessions (`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT`) | STABLE US equities  |
| W002 | US equity using a non-`America/New_York` timezone                             | STABLE US equities  |
| W003 | Schedule deviates from the asset-class majority                               | STABLE, non-futures |
| W004 | COMING_SOON feed with no publishers                                           | COMING_SOON         |
| W005 | `minPublishers` leaves only 1 headroom publisher                              | STABLE, non-exempt  |
| W006 | Duplicate `publisherId` in feed                                               | non-INACTIVE        |
| W007 | STABLE feed references a `TEST` key-type publisher                            | STABLE              |

### E011 vs W003

Both flag schedule drift, but with different strictness:

- **E011 (ERROR)** fires whenever two feeds in the same asset group (`asset_type` for spot, `(asset_type, futures_root)` for futures) have **any** distinct schedule signature. It is the hard failure.
- **W003 (WARNING)** only fires on minority deviation from an obvious majority in a given asset type, and exempts futures entirely. It is the soft heads-up.

They intentionally overlap. A future that disagrees with a sibling on the same root will fire E011 but not W003.

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

## Output Formats

### Text (default)

```
ERRORS (3 found):
  E009  Feed 458 (Crypto.JITOSOL/USD): STABLE feed references .Test-suffixed publishers: [49]
  E012  Feed 964 (Equity.US.APTV/USD): hermes_id 'abc...' duplicated across feedIds: 964, 3126
  E013  Feed 2973 (Commodities.ALH6/USD): COMING_SOON futures feed has expired (latest validTo: 2026-03-27T17:00:00+00:00); change state to INACTIVE

WARNINGS (1 found):
  W003  Feed 1775 (Equity.US.XLK/USD): schedule deviates from equity majority

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
