# edit_config.py

Surgical editor for session-only configs (`lazer_update.json` era). Adds/removes
publishers, sets/bumps `minPublishers`, sets `state` — for one feed, a list, a
range, or a filtered set.

## Config format (new format only)

The editor targets the session-level config format (`lazer_update.json` era)
and refuses to run against configs that still carry feed-level
`allowedPublisherIds` (old format).

- Publisher ops edit session lists only. Default scope is the REGULAR
  session; `--session ALL` covers every session entry on the feed;
  `--session NONE` is an error for publisher ops.
- If a targeted session entry has no `allowedPublisherIds` key (common on
  COMING_SOON feeds), `--add-publisher` inserts it. The dry-run diff shows
  inserts as `(absent) -> [ ... ]`.
- minPublishers ops still edit the feed-level value. Session-level
  minPublishers is us-equities-only: non-US feeds take feed-level only
  (default and `--session ALL` degrade to feed-level; an explicit
  `--session REGULAR` etc. on a non-US feed is an error).

## Installation

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python3 tools/edit-config/edit_config.py --config lazer_update.json [OPERATION] [TARGETING] [SCOPE] [EXECUTION]
```

### Operations (exactly one per CLI invocation)

| Flag                                        | Effect                                                                     |
| ------------------------------------------- | -------------------------------------------------------------------------- |
| `--add-publisher INT`                       | Add publisher to session `allowedPublisherIds` list                        |
| `--remove-publisher INT`                    | Remove publisher from session `allowedPublisherIds` list                   |
| `--set-min-publishers INT`                  | Set `minPublishers` to a value                                             |
| `--bump-min-publishers ±INT`                | Adjust `minPublishers` by signed delta (clamped at 1)                      |
| `--set-state STABLE\|COMING_SOON\|INACTIVE` | Change feed state                                                          |
| `--add-exchange-id N`                       | Assign exchange `N` and strip inherited `marketSchedule` strings           |
| `--remove-exchange-id`                      | Remove `exchangeId` and restore `marketSchedule` strings from the exchange |
| `--set-ric-mapping --from-csv PATH`         | Fill empty `datascope_ric.identifier` values                               |
| `--remove-ric`                              | Clear all `datascope_ric` identifier values to `""`                        |
| `--from-spec PATH`                          | Apply a batched YAML spec (multiple ops)                                   |

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

**Publisher ops** (`--add-publisher`, `--remove-publisher`):

| `--session` value                                       | Meaning                                               |
| ------------------------------------------------------- | ----------------------------------------------------- |
| _(omitted)_                                             | REGULAR session entry only                            |
| `REGULAR` / `PRE_MARKET` / `POST_MARKET` / `OVER_NIGHT` | that session entry; error if the feed doesn't have it |
| `ALL`                                                   | every session entry present on the feed               |
| `NONE`                                                  | error — no feed-level roster exists in the new format |

**min-publishers ops** (`--set-min-publishers`, `--bump-min-publishers`).
Session-level `minPublishers` is a us-equities-only concept, so session targets
apply only to feeds whose symbol starts with `Equity.US.`:

| `--session` value                                       | US-equity feed (`Equity.US.*`)                       | All other feeds                          |
| ------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------- |
| _(omitted)_                                             | feed-level + REGULAR session entry                   | feed-level only                          |
| `REGULAR` / `PRE_MARKET` / `POST_MARKET` / `OVER_NIGHT` | that session entry only; error if the feed lacks it  | error — session minPublishers is US-only |
| `ALL`                                                   | feed-level + every session entry present on the feed | feed-level only                          |
| `NONE`                                                  | feed-level only                                      | feed-level only                          |

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

### `--set-ric` — resolve and overwrite `datascope_ric` identifiers

Resolves each targeted feed's RIC via `generate_ric_mapping`'s `RICResolver` and
overwrites the `datascope_ric.identifier` slots in every existing session on that feed.

**RIC pattern (US equities)**

| Session slot                     | Written value                                                                                                         |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| REGULAR, PRE_MARKET, POST_MARKET | Day RIC: `TICKER.O` (NASDAQ), `TICKER.K` (IEX / 4+ char consolidated), bare `TICKER` (short consolidated, e.g. `XLF`) |
| OVER_NIGHT                       | `TICKER.BLUE`                                                                                                         |

**Per-slot behaviour**

- Slot already equals resolved value → NOOP (no diff entry).
- Slot differs (empty, bare ticker, or wrong exchange suffix) → overwritten. If the
  old value was non-empty a churn warning is printed so you can review it in the dry-run.
- **Only existing session slots are updated — missing PRE_MARKET / POST_MARKET /
  OVER_NIGHT sessions are never inserted.**

**Targeting** — requires `--feed-id` or `--feed-ids-from`. Symbol-pattern and
asset-class-only targeting are not accepted (resolution is by feed ID). Intended
for US-equity feeds: other asset classes either resolve no RIC (reported as
unresolved) or get a day-session RIC with an empty `OVER_NIGHT` value, so review
the dry-run before targeting non-US-equity feeds.

**Resolution summary footer** — after processing, a footer shows the number of
identifiers overwritten, feeds unresolved, and low-confidence RIC counts.
Low-confidence RICs are still written, but surfaced here so you can decide
whether to review before `--apply`.

**Extra flags**

| Flag              | Default         | Effect                                            |
| ----------------- | --------------- | ------------------------------------------------- |
| `--symbols PATH`  | `--config` file | Override the resolver's reference symbols file    |
| `--force-refresh` | off             | Bypass NASDAQ-Trader cache (forces a live lookup) |

```bash
# dry-run (default)
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --set-ric --feed-ids-from feed_ids.txt

# write
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --set-ric --feed-ids-from feed_ids.txt --apply
```

**Contrast with `--set-ric-mapping`** — `--set-ric-mapping` is HK-only, matches
feeds by symbol prefix from a CSV, writes one RIC to every slot, and only fills
_empty_ slots. `--set-ric` resolves RICs automatically by feed ID, differentiates
day vs overnight slots, and overwrites non-empty values that differ.

### `--set-ric-mapping` — fill empty `datascope_ric` identifiers

Backfills `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier`
values from an LSEG-style CSV. Useful when feeds are bootstrapped with empty
identifier strings and the RICs are delivered separately.

```bash
python3 tools/edit-config/edit_config.py \
    --config lazer_update.json \
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

### `--remove-ric` — clear `datascope_ric` identifiers

The structural inverse of `--set-ric-mapping`: clears **every**
`datascope_ric.identifiers[].identifier` value on each targeted feed back to the
empty string (`""`), leaving the `datascope_ric` / `identifiers[]` scaffold in
place. Use it when a feed was onboarded with a wrong RIC, or an asset is delisted
and its mapping should be removed.

```bash
# dry-run (default)
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --remove-ric --feed-id 885

# write
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --remove-ric --feed-id 885 --apply
```

Per-slot rules:

- Non-empty `identifier` → cleared to `""`, with a warning naming the wiped value.
- Already-empty `identifier` → NOOP (no change, no warning).
- Feed with no `datascope_ric` identifier slots → "nothing to clear" warning.

Safety:

- **Dry-run is the default** — review the diff and the RIC removal summary before
  re-running with `--apply`.
- A targeted **STABLE** feed with a populated RIC triggers an extra warning
  (clearing it breaks a live benchmark).
- INACTIVE feeds are skipped (reactivate via `--set-state` first).

Targeting uses the full filter set (`--feed-id`, `--feed-ids-from`,
`--symbol-pattern`, `--asset-class`, `--state`) — the same model as the
publisher/min-publisher ops. A broad `--symbol-pattern` / `--asset-class` can
match many feeds, so the matched-feed count, full diff, and per-value warnings
in the dry-run are your blast-radius check.

YAML spec form:

```yaml
version: 1
operations:
  - op: remove_ric
    feed_id: "884,885"
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

## Exchange inheritance

A feed may carry a top-level `exchangeId` that points into the config's
top-level `exchanges[]` array. When it does, the feed **inherits** that
exchange's trading calendar: its session entries omit their own
`marketSchedule` string.

- `--add-exchange-id N` sets the feed's `exchangeId` to `N` and removes the
  now-redundant `marketSchedule` string from every session entry. If the feed
  already has a different `exchangeId`, the op reassigns it and warns.
- `--remove-exchange-id` clears the `exchangeId` and restores each session's
  `marketSchedule` string by copying it from the exchange definition.

Validation:

- Adding an `exchangeId` not present in `exchanges[]` is an error. The array is
  sparse; ids the team has not yet defined simply error until they are added.
- If the feed has a session the exchange does not define (e.g. an `OVER_NIGHT`
  session against an exchange that only defines `REGULAR`), both add and remove
  error — there would be no schedule to inherit or restore for that session.
- An exchange whose `assetClass` does not match the feed's `metadata.asset_type`
  produces a warning, not an error.

These ops target whole feeds (use `--feed-id`, `--symbol-pattern`, etc.). Like
the other edit ops, they skip `INACTIVE` feeds — reactivate with `--set-state`
first. They are also available in YAML specs as `add_exchange_id`
(`exchange_id:` required) and `remove_exchange_id`.
