# stalePriceFilter support in edit_config.py

**Date:** 2026-07-27
**Status:** Approved, ready for implementation plan

## Goal

Add a systematic way to set, tune, and remove the session-level `stalePriceFilter`
object in a Lazer config, driven from a feed-ID list such as `jp_kr.csv`. The
capability lands as two new operations in `tools/edit-config/edit_config.py`,
available from both the CLI and the YAML `--from-spec` path.

## Background

`stalePriceFilter` lives inside a `marketSchedules` session entry and carries three
knobs:

```json
"stalePriceFilter": {
  "movedPriceThresholdBps": 0.5,
  "stalenessThresholdSecs": 10800,
  "windowSecs": 60
}
```

In `lazer_staleness.json` (3627 feeds) exactly three feeds carry it today — 2166
(`Equity.KR.000660/KRW`), 3337 (`Equity.JP.285A/JPY`), 3338 (`Equity.JP.4062/JPY`) —
all with the values above. Those same three are the only `STABLE` entries in
`jp_kr.csv`; the other 33 feeds in that file are `COMING_SOON` and carry no filter.
Every feed in the list has a single `REGULAR` session.

Config keys are serialized alphabetically, so `stalePriceFilter` is always the **last**
key in a session object (it sorts after `session`, which every session entry has).

## Operations

### `SetStaleFilter`

Session-scoped, with the same targeting and scoping rules as the publisher ops:
`--session` defaults to `REGULAR`, `ALL` fans out over every session on the feed, and
`NONE` is an error because the filter has no feed-level home. Targeting a session the
feed does not have raises `OpError`, matching `--add-publisher`.

**Create** (no filter present on the session): write all three keys, filling anything
not passed from the defaults `0.5 / 10800 / 60`, declared as module constants in
`config_ops.py`.

**Patch** (filter present): rewrite only the keys passed on the command line; leave the
rest untouched. A passed value that already equals the current one yields no change
record, so re-running any command is a clean no-op.

```
--set-stale-filter                       → {0.5, 10800, 60}    create, all defaults
--set-stale-filter --window-secs 120     → {0.5, 10800, 120}   create, one override
--set-stale-filter --window-secs 120     → {2.0, 3600, 120}    patch of {2.0, 3600, 60}
```

### `ClearStaleFilter`

Deletes the whole `stalePriceFilter` object from targeted sessions — the inverse of
the above, following the `--remove-ric` / `--remove-exchange-id` precedent. Sessions
with no filter are a no-op with a warning, mirroring how `ClearRic` reports "nothing
to clear".

### Validation

- **Errors** (block apply): any of the three values non-numeric or `<= 0`.
- **Warning**: `stalenessThresholdSecs < windowSecs` — a staleness horizon shorter
  than the observation window is almost certainly a typo, but not blocked.

## CLI surface

```bash
python3 tools/edit-config/edit_config.py --config lazer_staleness.json \
  --set-stale-filter \
  --moved-price-bps 0.5 --staleness-secs 10800 --window-secs 60 \
  --feed-ids-from jp_kr.csv --session REGULAR
```

Five new argparse flags: `--set-stale-filter` and `--clear-stale-filter` join the
mutually exclusive operation group; `--moved-price-bps` (float), `--staleness-secs`
(int) and `--window-secs` (int) are value flags, valid only alongside
`--set-stale-filter`.

Bare `--set-stale-filter` with no value flags is legal and is the bulk-onboarding path:
it applies all three defaults.

## YAML spec surface

```yaml
version: 1
operations:
  - op: set_stale_filter
    feed_id: "1990,2023,2043-2064"
    session: REGULAR
    window_secs: 120 # omitted keys keep patch semantics
  - op: clear_stale_filter
    feed_id: 3337
    session: REGULAR
```

Spec field names: `moved_price_threshold_bps`, `staleness_threshold_secs`,
`window_secs` — all optional, matching create/patch semantics. Both ops register in
`_OP_REQUIRED_FIELDS` with an empty required set.

## Targeting: CSV feed-ID files

`read_selector_file` gains one rule: **when the path ends in `.csv`, take only the text
before the first comma on each line**; every other path keeps today's strict `N` /
`A-B` grammar. A first row whose column 1 is not numeric is treated as a header and
skipped; a non-numeric column 1 on any later row is an error as before.

This is confined to `read_selector_file`, so inline `--feed-id "100-200"` and stdin
(`-`) are unaffected. It lands for every operation, not just the two added here, which
makes the repo's existing benchmark CSVs (`jp_kr.csv`, `kr.csv`, `hk_41.csv`, …)
directly usable as targeting files.

## Implementation

### Text surgery (`config_text_surgery.py`)

This is the first operation that writes a nested object and the first that writes a
float, so four new helpers are needed:

| Helper                                      | Why                                                                                                                                                                             |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `find_stale_filter_block(sblock)`           | Span of the `{…}` after `"stalePriceFilter":`, scoping patch lookups inside the object                                                                                          |
| `find_number_field_span(block, key)`        | `find_int_field_span` matches `-?\d+`; pointed at `0.5` it grabs the `0` and corrupts the value. Matches int and decimal literals                                               |
| `insert_field_before_close_brace(block, …)` | `stalePriceFilter` is always the last key, so it takes no trailing comma and the _previous_ line needs one added. Both existing inserters emit a comma-terminated field instead |
| `delete_object_field(block, key)`           | Object-valued sibling of `delete_scalar_field`, removing the **preceding** comma rather than a trailing one                                                                     |

Value formatting: `repr(float)` for `movedPriceThresholdBps` (`0.5` → `0.5`, `2` →
`2.0`); plain ints for the two second-counts.

### Change records and diff

| Case   | Change records                                             | Diff hunk                            |
| ------ | ---------------------------------------------------------- | ------------------------------------ |
| Create | one, `field="stalePriceFilter"`, `before=None`             | `(absent)` → compact one-line object |
| Patch  | one per changed key, `field="stalePriceFilter.windowSecs"` | `60,` → `120,`                       |
| Clear  | one, `field="stalePriceFilter"`, `after=None`              | compact object → `(removed)`         |

Per-key records on patch keep the diff readable: across 36 feeds it shows exactly which
knob moved rather than 36 identical object dumps. Whole-object hunks render compact on
a single line because `render_diff` prefixes only a value's first line with `-`/`+`, so
a multi-line render would emit unprefixed lines.

### Files touched

| File                     | Change                                                                                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config_ops.py`          | `SetStaleFilter`, `ClearStaleFilter`, the three default constants; generalize `_resolve_publisher_sessions`' `NONE` error text (it names publisher ops)                               |
| `config_text_surgery.py` | the four helpers above                                                                                                                                                                |
| `config_editor.py`       | register both ops in `_OP_FLAGS`, `build_op_from_args`, `_OP_REQUIRED_FIELDS`, `_build_op_from_yaml_entry`; add both `store_true` flags to `_BOOL_OP_FLAGS`; two new applier branches |
| `config_selector.py`     | `read_selector_file`: `.csv` → column 1, header row skipped                                                                                                                           |
| `config_diff.py`         | rendering branch for the three cases                                                                                                                                                  |
| `edit_config.py`         | five argparse flags                                                                                                                                                                   |
| `docs/edit_config.md`    | usage section for both ops and the CSV targeting rule                                                                                                                                 |
| `CLAUDE.md`              | scripts-table line for `edit_config.py`                                                                                                                                               |

## Testing

New fixture `tests/fixtures/stale_sample.json`: feed 2166 with a filter plus two
JP/KR feeds without one. A separate fixture rather than an extension of
`after_sample.json`, which existing count assertions depend on.

Tests mirror the existing per-module layout:

- `test_config_text_surgery.py` — insert-as-last-key (comma added to the previous
  line), float span located without truncation, delete removes the preceding comma,
  each leaving parseable JSON.
- `test_config_ops.py` — create with defaults; create with partial overrides; partial
  patch leaves untouched keys alone; re-run of an identical command produces zero
  changes; clear; clear on a session with no filter warns; non-positive and
  non-numeric values error; `staleness < window` warns.
- `test_config_selector.py` — `.csv` path reads column 1; header row skipped;
  non-CSV path still strict; stdin still strict.
- `test_edit_config_cli.py` — one round-trip applying to the fixture and re-parsing
  with `json.load` to prove the output is valid JSON, plus a `--from-spec` case.

## Definition of done

- [ ] `--set-stale-filter` and `--clear-stale-filter` work from CLI and `--from-spec`
- [ ] `--feed-ids-from jp_kr.csv` parses without preprocessing
- [ ] Dry run against `lazer_staleness.json` reports 33 changes, 0 errors
- [ ] After `--apply`: `json.load` succeeds, `tools/config-linter/config_linter.py`
      passes, and feeds 2166 / 3337 / 3338 are byte-identical to before
- [ ] Full `pytest tools/edit-config/tests/` green
- [ ] `pre-commit run --files <changed files>` clean
