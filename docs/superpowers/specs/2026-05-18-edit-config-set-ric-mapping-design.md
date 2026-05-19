# edit-config: `--set-ric-mapping` operation

**Date:** 2026-05-18
**Status:** Approved, ready for implementation plan

## Problem

`after.promoted.2026-05-15.json` contains 96 Hong Kong equity feeds (`Equity.HK.NNNN-HK/HKD`, state `COMING_SOON`) where every feed's `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier` is an empty string. We have an LSEG export (`hk-syms.csv`) with the correct RICs (e.g. `0700.HK`) and want to surgically backfill those identifiers without touching anything else.

This is a recurring need (we've done analogous work for US equities before), so we want it as a reusable operation in `tools/edit-config/edit_config.py` rather than a one-off script.

## Solution

Add a new mutually-exclusive operation to `edit_config.py`:

```
python3 tools/edit-config/edit_config.py \
  --config after.promoted.2026-05-15.json \
  --set-ric-mapping \
  --from-csv hk-syms.csv \
  [--dry-run]
```

### Semantics

For each feed in the config:

1. Derive the feed's expected symbol prefix from each CSV `RIC` value (HK rule: `NNNN.HK → Equity.HK.NNNN-HK/`).
2. If `feed.symbol` starts with one of those prefixes:
   - Iterate every `marketSchedule.benchmarkMapping.datascope_ric.identifiers[]` entry.
   - If `identifier == ""`, set it to the matched RIC (a `Change`).
   - If `identifier` is non-empty, skip the slot (emit a `Warning`).
3. If no CSV row matches the feed symbol, the feed is left untouched. Feeds with non-HK symbols are silently ignored (the CSV defines scope).
4. CSV rows that match no feed are reported as `Warning`s.

The operation only writes the `identifier` string field. It uses the existing `config_text_surgery` path so byte-level diffs are minimal (just the `""` → `"0700.HK"` swap).

### Matching rule (v1: HK only)

| CSV `RIC` | Expected symbol prefix |
| --------- | ---------------------- |
| `0700.HK` | `Equity.HK.0700-HK/`   |

Non-HK rows in the CSV would fail to produce a prefix and be reported as unmatched. Other exchanges can be added later as additional rules; we are intentionally not generalising in v1.

### CLI shape

- `--set-ric-mapping` joins the existing mutually-exclusive op group alongside `--add-publisher`, `--set-state`, etc.
- `--from-csv PATH` is a new required argument for this op.
- No `--feed-id` / `--symbol-pattern` selector required — the CSV is the selector.
- Standard `--dry-run`, backup, and YAML-spec mechanisms work unchanged.

### Dry-run / summary output

The summary reports:

- N identifiers filled (grouped by feed)
- N slots skipped because already populated (list of feed IDs)
- N CSV rows unmatched (list of tickers/RICs)
- N feeds matched by symbol but with no empty-identifier slots (list)

## Edge cases

1. **Multiple `marketSchedules`** — iterate all schedules and all `identifiers[]` entries; skip-if-nonempty applies per slot.
2. **Missing `benchmarkMapping` / `datascope_ric` / `identifiers` structure** — skip with `Warning`; do NOT create the structure.
3. **Duplicate RICs in CSV** — fail loudly at load time (`OpError`).
4. **Ticker collisions on string form** (e.g. `700` vs `0700`) — non-issue: matching is by RIC, not raw ticker.
5. **Empty CSV** — `OpError` (caller almost certainly made a mistake).

## Out of scope

- Non-HK exchange rules (US, JP, KR, etc.) — add when needed.
- State promotion (COMING_SOON → STABLE) — separate operation already exists.
- Any change to publishers, schedules, exponent, minPublishers, etc.
- Changes to `tools/config-linter`.

## Tests

Following the existing pattern in `tools/edit-config/tests/`:

- **`test_config_ops.py`** — unit tests for `SetRicMapping`:
  - empty-slot fill (happy path)
  - skip when identifier non-empty
  - skip when no CSV match
  - multi-schedule feed (independent slot fills)
  - missing `benchmarkMapping` structure (skip + warning)
  - duplicate RIC in CSV (raises `OpError`)
  - empty CSV (raises `OpError`)
- **`test_edit_config_cli.py`** — CLI integration test with a small fixture JSON + CSV.
- **Fixtures:**
  - `tests/fixtures/hk_sample.json` — 4–5 feeds: one empty-identifier, one already-populated, one with no CSV match, one non-HK.
  - `tests/fixtures/hk-syms-sample.csv` — matching RIC rows plus one unmatched row.

## Acceptance criteria

- Running the op against `after.promoted.2026-05-15.json` with `hk-syms.csv` fills the identifiers for the 89 matched HK feeds and reports the ~7 unmatched feeds.
- A byte-level diff shows ONLY the `identifier: ""` → `identifier: "<RIC>"` changes; no other lines move.
- All new and existing tests pass.
- `pre-commit run --files <changed>` is clean.
