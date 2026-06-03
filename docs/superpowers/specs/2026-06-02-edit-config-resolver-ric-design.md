# edit-config: resolver-driven RIC fix (`--set-ric`)

**Date:** 2026-06-02
**Status:** Approved (design)

## Problem

`evaluate_feeds_bulk.py` skips a feed-day (engine exit 2, "no benchmark data")
when no Datascope benchmark rows exist for that feed. For US equities the
benchmark engine queries `datascope_global_equities_benchmark_data` by
`pyth_lazer_id`; the rows themselves are populated by an **upstream Datascope
ingestion** that subscribes by RIC. That RIC comes from each feed's
`marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier`
field in the Lazer config (`after.json`). A missing or wrong RIC there means
ingestion subscribes to nothing (or the wrong instrument), no rows land, and
the feed is skipped.

`feed_ids.txt` lists 101 US-equity feeds that are skipped. Audited against
`before.json` (identical in `after.json`):

| Category               | Count | Current state                                                                 | vs. reference (feed 922)                                                |
| ---------------------- | ----- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Bare day-session RIC   | 79    | REGULAR/PRE/POST = bare ticker (`BITS`, `VYM`…); OVER_NIGHT = `TICKER.BLUE` ✓ | day sessions missing exchange suffix → **wrong**                        |
| Empty RIC              | 1     | 1703 (IWDA) = `""`                                                            | **missing**                                                             |
| Suffixed, REGULAR-only | 20    | valid `.O`/`.N` (e.g. `CPAY.O`, `CTRA.N`) but only a REGULAR session          | correct-looking RIC; 1367 `Equity.US.REG` → `REGN.O` is a wrong mapping |
| Already correct        | 2     | 2300 (SSK), 2352 (BLSH) — all four sessions, proper suffixes                  | fine (skipped for a non-config reason)                                  |

**Reference pattern (feed 922 / AAPL):** REGULAR / PRE_MARKET / POST_MARKET →
`TICKER.<exchange>`; OVER_NIGHT → `TICKER.BLUE`.

## Existing tooling

`edit_config.py` already has a `--set-ric-mapping` operation, but it is built
for HK equities only: it matches feeds by symbol prefix
(`ric_csv.derive_symbol_prefixes` handles only `.HK`), writes the **same** RIC
to every identifier slot, and only fills **empty** slots (it would skip all 79
bare feeds). This work adds a **new, parallel** operation rather than changing
that path.

`generate_ric_mapping.py` already resolves a feed id to its correctly-suffixed
Datascope RIC via `RICResolver(symbols_path).resolve_by_id(feed_id) ->
RICResult`. The US-equity convention it implements:

- NASDAQ-listed → `{base}.O`
- IEX (exchange code `V`) → `{base}.K`
- Other US-consolidated venues (NYSE `N`, Arca `P`, American `A`, Cboe `Z`,
  unknown) → `{base}.K` when the ticker root is **≥ 4 chars**, otherwise
  **bare** (no suffix). Examples: `CTRA` → `CTRA.K`; `XLF` → `XLF`; `RIO` →
  `RIO`; `O` → `O`.

This is the single source of truth for the RIC. The 20 already-`.N` feeds will
be rewritten to this convention (e.g. `CTRA.N` → `CTRA.K`); that is the
intended fix, per the scope decision below.

## Decisions

- **Integration:** inline — `edit_config` imports `RICResolver` and calls
  `resolve_by_id()` directly. One command, single source of truth.
- **Scope / overwrite policy:** overwrite **any** existing identifier slot whose
  value differs from the resolved RIC, across all targeted feeds (including the
  20 `.N` feeds). Slots already equal to the resolved value are NOOPs.
- **Cannot insert:** the text-surgery engine only _replaces_ existing identifier
  slots. It will not add PRE/POST/OVERNIGHT sessions to the 20 REGULAR-only
  feeds; their single existing slot is rewritten and nothing more.

## Design

### 1. CLI surface

New operation flag on `tools/edit-config/edit_config.py`, mutually exclusive
with the other operation flags:

```
python3 tools/edit-config/edit_config.py --config after.json \
    --set-ric --feed-ids-from feed_ids.txt [--apply]
```

- Targets via the existing `--feed-id` / `--feed-ids-from` selectors, so
  `feed_ids.txt` (one feed id per line) works directly.
- `--set-ric-mapping --from-csv` (HK path) is unchanged.
- Inherited from the existing framework: dry-run by default, `--apply` to write,
  `.bak` backup, INACTIVE feeds silently skipped, plan/diff/summary output.

Optional knobs (default off): `--symbols PATH` to point the resolver at a
reference file other than `--config`; `--force-refresh` to bypass the
NASDAQ-Trader cache.

### 2. Resolution (in `build_op_from_args`, mirroring the CSV path)

At plan-build time — analogous to how the HK path loads its CSV — resolve every
targeted feed id:

- Instantiate `RICResolver(symbols_path=args.config)` (the same file being
  edited, so symbols match the feeds being changed).
- For each feed id, `result = resolver.resolve_by_id(fid)` and build
  `feed_id -> {day_ric, overnight_ric, confidence, warnings}`:
  - `day_ric = result.ric`
  - `overnight_ric = f"{ticker_to_ric_base(result.display_ticker)}.BLUE"`
    (`ticker_to_ric_base` imported from `generate_ric_mapping`)
- Feeds the resolver cannot resolve (empty `result.ric`) are carried with an
  empty `day_ric` so the op can warn rather than silently drop them.

The NASDAQ-Trader fetch happens here, once per run.

### 3. New op `SetRicFromResolver` (in `config_ops.py`)

Constructed with the plain `feed_id -> rics` map. The op holds **no** resolver
or network dependency — keeping `config_ops` pure and unit-testable, exactly
like the existing `SetRicMapping`.

`apply(feed)`:

1. Look up `feed["feedId"]` in the map. If absent, or `day_ric` is empty →
   `Warning` (unresolved), no change.
2. Walk `feed["marketSchedules"]` in document order. For each
   `benchmarkMapping.datascope_ric.identifiers[]` slot, compute the target:
   `overnight_ric` if `session == "OVER_NIGHT"`, else `day_ric`.
3. For each slot:
   - value **==** target → NOOP (no Change).
   - value **!=** target (empty, bare, or wrong) → emit
     `Change(location="datascope_ric_identifier", field="identifier",
index=i, before=<current>, after=<target>)`, reusing the existing
     text-surgery application path unchanged.
   - additionally, when overwriting a **non-empty** value, emit a `Warning` so
     the diff/dry-run surfaces churn (e.g. `CTRA.N → CTRA.K`,
     `REGN.O → REG`).
4. Feed has no identifier slots → `Warning` (cannot insert via text surgery).

Slot/session correspondence is reliable because both the op (iterating
`marketSchedules`) and `find_ric_identifier_spans` (scanning raw text) walk the
identifiers in document order; the `Change.index` ties them together, the same
mechanism `SetRicMapping` already uses.

### 4. Output

Extend the per-op summary (the `_set_ric_mapping_summary_lines` style block in
`edit_config.py`) with:

- identifiers overwritten
- identifiers already correct (NOOP)
- feeds unresolved (with their ids)
- low-confidence / defaulted RICs (resolver `confidence` and `warnings` printed
  inline, so a reviewer can eyeball guessed RICs before `--apply`)

Low-confidence RICs are **written**, not skipped — the dry-run diff plus the
confidence callout is the review gate.

### 5. Tests

Pure unit tests for `SetRicFromResolver.apply` (no network, since the op takes a
plain map), using fixtures covering:

- bare 4-slot feed → day slots rewritten with suffix, OVER_NIGHT `.BLUE` NOOP
- empty 1-slot feed (IWDA-style) → filled
- already-`.N` feed → rewritten to resolver convention + churn warning
- already-correct feed → all NOOP, zero changes
- feed with no identifier slots → warning
- OVER_NIGHT `.BLUE` derivation from `display_ticker`
- unresolved feed id → warning

One CLI test with a monkeypatched/faked resolver to exercise
`build_op_from_args` → simulate → diff without hitting the network.

### 6. Docs

- Update `docs/edit_config.md` with the `--set-ric` operation and an example
  using `feed_ids.txt`.
- Add the operation to the `CLAUDE.md` scripts-table note for `edit_config.py`.

## Non-goals

- Does not add missing market sessions to feeds (text-surgery cannot insert).
- Does not modify the benchmark engine or the Datascope ingestion pipeline.
- Does not change the existing `--set-ric-mapping` (HK) behaviour.
