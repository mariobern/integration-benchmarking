# edit_config.py

Surgical editor for `after.json`. Adds/removes publishers, sets/bumps `minPublishers`, sets `state` — for one feed, a list, a range, or a filtered set.

## Installation

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python3 tools/edit-config/edit_config.py --config after.json [OPERATION] [TARGETING] [SCOPE] [EXECUTION]
```

### Operations (exactly one per CLI invocation)

| Flag                                        | Effect                                                |
| ------------------------------------------- | ----------------------------------------------------- |
| `--add-publisher INT`                       | Add publisher to `allowedPublisherIds`                |
| `--remove-publisher INT`                    | Remove publisher from `allowedPublisherIds`           |
| `--set-min-publishers INT`                  | Set `minPublishers` to a value                        |
| `--bump-min-publishers ±INT`                | Adjust `minPublishers` by signed delta (clamped at 1) |
| `--set-state STABLE\|COMING_SOON\|INACTIVE` | Change feed state                                     |
| `--set-ric-mapping --from-csv PATH`         | Fill empty `datascope_ric.identifier` values          |
| `--from-spec PATH`                          | Apply a batched YAML spec (multiple ops)              |

### Targeting (≥1 required when not using `--from-spec`)

| Flag               | Form                                       |
| ------------------ | ------------------------------------------ |
| `--feed-id`        | `922` or `100-200,205,208,3530-3540`       |
| `--feed-ids-from`  | path to a text file (or `-` for stdin)     |
| `--symbol-pattern` | fnmatch glob, e.g. `Equity.US.*`           |
| `--asset-class`    | matches `metadata.asset_type`              |
| `--state`          | filter for STABLE / COMING_SOON / INACTIVE |

### Scope (publisher / minPublishers ops)

`--session {REGULAR,PRE_MARKET,POST_MARKET,OVER_NIGHT,ALL,NONE}`

Default (no `--session`): top-level + REGULAR for equity feeds with per-session rosters; top-level only for feeds without per-session rosters (crypto, fx, commodity, metals, rates, single-session equities, etc.).

- `NONE` = top-level only.
- `ALL` = top-level + every per-session roster. Symmetric for add and remove. Errors if the feed has no per-session rosters.
- Explicit `REGULAR`/`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT` = that session roster only (no top-level). Errors if the named session has no roster on this feed — on non-per-session feeds, drop `--session` entirely and use the default scope to edit top-level.

`remove_publisher` default differs: removes from EVERYWHERE in this feed (top-level + every per-session roster present).

### Execution

| Flag               | Default | Effect                              |
| ------------------ | ------- | ----------------------------------- |
| `--dry-run`        | yes     | Show plan + diff; do not write      |
| `--apply`          | no      | Required to write                   |
| `--show-full-diff` | no      | Don't truncate the diff at 40 hunks |
| `--no-backup`      | no      | Skip `.bak` write                   |

`edit_config.py` does not run the config-linter. Run it separately when you
want a post-edit sanity check:

```bash
python3 tools/config-linter/config_linter.py --config after.json
```

### Exit codes

- `0` — success (warnings allowed)
- `1` — validation or runtime error (no write happens)

### `--set-ric-mapping` — fill empty `datascope_ric` identifiers

Backfills `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier`
values from an LSEG-style CSV. Useful when feeds are bootstrapped with empty
identifier strings and the RICs are delivered separately.

```bash
python3 tools/edit-config/edit_config.py \
    --config after.json \
    --set-ric-mapping \
    --from-csv hk-syms.csv
```

(Default is dry-run; add `--apply` to write changes.)

The CSV must have `Ticker`, `RIC`, and `Exchange Code` columns. v1 supports HK
equities only — rows whose RIC does not map to a known feed-symbol prefix are
reported as unmatched in the summary.

Per-slot rules:

- Empty `identifier` → filled with the CSV RIC.
- Non-empty `identifier` → skipped (warning emitted, never overwritten).
- Feed symbol with no CSV match → feed left untouched (no warning).
- CSV row that matched no feed → reported in summary.

YAML spec form:

```yaml
version: 1
operations:
  - op: set_ric_mapping
    from_csv: hk-syms.csv
```

## YAML spec format

```yaml
version: 1
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: "1000-1050"

  - op: remove_publisher
    publisher_id: 22
    feed_id: 922
    session: PRE_MARKET

  - op: set_min_publishers
    value: 3
    asset_class: equity
    state: [STABLE, COMING_SOON]
    session: REGULAR
```

Range strings in YAML must be quoted (`"1000-1050"`) — unquoted YAML parses `1000-1050` as `-50`.

## `--feed-ids-from` file format

Plain text, UTF-8. Tokens are `N` (single ID) or `A-B` (inclusive range). Tokens may be separated by commas, whitespace, or newlines. `#` to end-of-line is stripped. Blank lines ignored. Examples:

```text
# canonical one per line
100-200
205
3530
```

```text
# inline pasted from a slack message
100-200, 205, 208, 3530
```
