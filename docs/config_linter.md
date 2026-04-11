# Config Linter (config_linter.py)

Validates `after.json` for common configuration errors before deployment. Catches duplicate feeds, invalid publisher references, insufficient fault tolerance, missing required fields, and schedule inconsistencies. Pure stdlib -- no ClickHouse or external API access required.

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

| Argument               | Description                                                               | Required | Default |
| ---------------------- | ------------------------------------------------------------------------- | -------- | ------- |
| `--config`             | Path to after.json config file                                            | Yes      | --      |
| `--format`             | Output format for stdout: `text` or `json`                                | No       | `text`  |
| `--output`             | Write findings to file (format auto-detected: `.json` -> JSON, else text) | No       | --      |
| `--warnings-as-errors` | Treat warnings as errors (exit code 1)                                    | No       | False   |

When `--output` is provided, format is determined by file extension (`--format` is ignored). Stdout prints a one-line summary instead of full findings.

## Exit Codes

| Code | Meaning                                                    |
| ---- | ---------------------------------------------------------- |
| `0`  | No errors (warnings allowed unless `--warnings-as-errors`) |
| `1`  | Errors found, or warnings with `--warnings-as-errors`      |

## Lint Rules

### Errors

| Rule | Name                               | Description                                                                           |
| ---- | ---------------------------------- | ------------------------------------------------------------------------------------- |
| E001 | Duplicate feedId                   | Two or more feeds share the same `feedId`                                             |
| E002 | Duplicate symbol                   | Same `symbol` appears in multiple STABLE or COMING_SOON feeds                         |
| E003 | Invalid publisher reference        | `allowedPublisherIds` references a `publisherId` not in the `publishers` array        |
| E004 | No fault tolerance                 | `minPublishers` >= publisher count (feed cannot tolerate any publisher going offline) |
| E005 | STABLE with no publishers          | STABLE feed has empty or missing `allowedPublisherIds`                                |
| E006 | Non-equity extended sessions       | Non-equity feed has PRE_MARKET, POST_MARKET, or OVER_NIGHT sessions                   |
| E007 | Missing required fields            | Feed missing `feedId`, `symbol`, `state`, `kind`, or `metadata.asset_type`            |
| E008 | Session publisher not in top-level | Session-level `allowedPublisherIds` contains IDs not in the top-level list            |

### Warnings

| Rule | Name                        | Description                                                                      |
| ---- | --------------------------- | -------------------------------------------------------------------------------- |
| W001 | Missing extended sessions   | STABLE US equity missing expected sessions (PRE_MARKET, POST_MARKET, OVER_NIGHT) |
| W002 | Wrong timezone              | US equity using a timezone other than `America/New_York`                         | E
| W003 | Schedule deviation          | Feed's schedule differs from the majority in its asset class                     | E
| W004 | COMING_SOON no publishers   | COMING_SOON feed with no publishers assigned                                     |
| W005 | Low headroom                | `minPublishers` is only 1 less than publisher count                              |
| W006 | Duplicate publisher in feed | Same `publisherId` appears more than once in a feed's list                       | E
| W007 | TEST publisher in STABLE    | STABLE feed references a publisher with `keyType: "TEST"`                        | E

### Scope

Rules E003, E004, E005, E008, W005, and W006 are checked at both the top-level `allowedPublisherIds` and within each `marketSchedules` session entry. INACTIVE feeds are skipped entirely. Futures symbols are excluded from W003 schedule deviation checks.

### Exempt Asset Types

E004 and W005 are skipped for single-source asset types: `funding-rate`, `custom`, `crypto-redemption-rate`, `nav`, `crypto-index`, `kalshi`.

## Output Formats

### Text (default)

```
ERRORS (2 found):
  E001  Feed 327 (Crypto.BTC/USD): feedId 327 is duplicated (feeds[0], feeds[5])
  E004  Feed 1163 (Equity.US.AAPL/USD): minPublishers (5) >= publisher count (5), no fault tolerance

WARNINGS (1 found):
  W005  Feed 340 (FX.EUR/USD): minPublishers (4) leaves only 1 headroom (5 publishers)

Summary: 2 errors, 1 warnings
```

Terminal output includes ANSI colors (red for errors, yellow for warnings). File output (`--output *.txt`) strips colors.

### JSON

```json
[
  {
    "rule_id": "E001",
    "severity": "ERROR",
    "message": "feedId 327 is duplicated (feeds[0], feeds[5])",
    "feed_id": 327,
    "symbol": "Crypto.BTC/USD"
  }
]
```

Each finding includes `rule_id`, `severity`, `message`, `feed_id` (nullable), and `symbol` (nullable).

## File Output (`--output`)

When `--output` is used, the format is auto-detected from the file extension:

- `.json` -> JSON array of findings
- Anything else (`.txt`, `.log`, etc.) -> plain text without ANSI colors

Stdout prints a summary instead of full findings:

```
Wrote 2 errors, 1 warnings to lint_results.json
```

Or if clean:

```
No issues found. Wrote results to lint_results.txt
```
