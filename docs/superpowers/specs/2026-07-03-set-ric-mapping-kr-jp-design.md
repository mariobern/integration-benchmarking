# Design: KR/JP support for `edit_config.py --set-ric-mapping`

**Date:** 2026-07-03
**Status:** Approved (design); pending implementation plan
**Author:** Mario (mario@pyth.network) with Claude

## Problem

`prune.txt` contains 27 `RIC,Feed ID` rows for Korean (`.KS`) and Japanese (`.T`) equity
feeds in `lazer_new.json`. 25 of those feeds have an empty
`marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier` slot; the other 2
already carry the correct RIC. We want to backfill the 25 empty slots from `prune.txt`
without hand-editing JSON.

`tools/edit-config/edit_config.py` already has a RIC-mapping operation
(`--set-ric-mapping --from-csv PATH`, backed by `SetRicMapping` in
`edit_config_lib/config_ops.py`), but `edit_config_lib/ric_csv.py`'s
`derive_symbol_prefixes()` only maps RICs ending in `.HK` to a feed-symbol prefix — `.KS` and
`.T` RICs currently derive no prefix at all, so every `prune.txt` row would be reported
unmatched.

Separately, `load_ric_csv()` requires `Ticker`, `RIC`, and `Exchange Code` columns
(LSEG-style export shape). `prune.txt` only has `RIC` and `Feed ID`; `Ticker`/`Exchange Code`
are validated as present but are never actually read by the matching logic
(`derive_symbol_prefixes` takes only a RIC string).

## Decisions (locked during brainstorming)

| #                     | Decision                                                                                                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Matching strategy     | Symbol-prefix derivation (same mechanism as HK), **not** a new feed-id-keyed op. `Feed ID` in `prune.txt` is not consulted — it was cross-checked during design (see Verification) but plays no functional role in the shipped tool. |
| Prefix shape          | `.KS` → `Equity.KR.`; `.T` → `Equity.JP.`. Each RIC yields two candidate prefixes, mirroring HK: bare (`Equity.KR.<code>/`) and legacy-suffixed (`Equity.KR.<code>-KR/`). Ticker portion must be all-digits (same guard as HK). |
| CSV required columns  | Relax `_REQUIRED_COLUMNS` in `ric_csv.py` to just `("RIC",)`. `Ticker` and `Exchange Code` become optional, defaulting to `""` when the column is absent or the cell is empty. `prune.txt` loads unmodified. |
| Scope of `SetRicMapping` / CLI | No changes. Existing fill-empty / skip-non-empty / skip-unmatched-symbol / warn-no-slots semantics apply as-is. |
| Docs                  | Update `docs/edit_config.md`: drop "v1 supports HK equities only" language for `--set-ric-mapping`; state KR/JP are also supported and that `Ticker`/`Exchange Code` are optional. |

## Verification done during design (informs test cases, not shipped logic)

All 27 `prune.txt` rows were checked against `lazer_new.json` two ways, to confirm the
prefix-derivation approach produces identical results to a hypothetical feed-id-direct
approach before committing to it:

- **Direct feed-id lookup:** 27/27 feed IDs exist; 25 have an empty `datascope_ric` identifier
  slot, 2 (`2166`, `2080`) already hold the exact `prune.txt` RIC (no-op), 0 conflicts, 0
  feeds with a missing `datascope_ric` slot, all single-session (`REGULAR`).
- **Simulated prefix derivation:** for every row, deriving `Equity.KR.<code>/` /
  `Equity.JP.<code>/` (+ `-KR`/`-JP` legacy form) and matching against every feed in
  `lazer_new.json` resolves to exactly the same 27 feed IDs, with no prefix matching more than
  one feed (no collisions).
- One existing legacy-suffixed JP feed was found in the config (`Equity.JP.1321-JP/JPY`),
  confirming the `-JP` suffix form is real and worth deriving, not speculative.

## Implementation surface

1. **`tools/edit-config/edit_config_lib/ric_csv.py`**
   - `derive_symbol_prefixes()`: generalize the single `.HK` branch into a small table of
     `(suffix, exchange_code)` pairs — `(".HK", "HK")`, `(".KS", "KR")`, `(".T", "JP")` — each
     producing `[f"Equity.{exchange_code}.{head}-{exchange_code}/", f"Equity.{exchange_code}.{head}/"]`
     when `head.isdigit()`.
   - `load_ric_csv()`: change `_REQUIRED_COLUMNS` to `("RIC",)`; read `Ticker` / `Exchange Code`
     with `.get(..., "")` fallback (already uses `row.get(...) or ""`, so only the required-columns
     check needs to change).
2. **`tools/edit-config/tests/test_ric_csv.py`**: add cases for `.KS`/`.T` prefix derivation
   (bare + suffixed, non-digit-ticker rejection), a mixed HK/KR/JP CSV, and a `RIC`-only CSV
   (no `Ticker`/`Exchange Code` columns) loading successfully.
3. **`tools/edit-config/tests/test_config_ops.py`** / **`test_edit_config_cli.py`**: check for
   any test names/comments asserting HK-only behavior and update if they'd now be misleading;
   no logic changes expected here since `SetRicMapping` itself is untouched.
4. **`docs/edit_config.md`**: update the `--set-ric-mapping` section (the "v1 supports HK
   equities only" line and the CSV-column requirement note).

## Non-goals

- No new CLI flag or op — this extends the existing `--set-ric-mapping` code path only.
- No change to `--set-ric` / `SetRicFromResolver` (the auto-resolving op) or `--remove-ric`.
- No handling of non-numeric KR/JP tickers, multi-session KR/JP feeds and their overnight
  slots, or asset classes beyond equities — out of scope for this backfill.

## Rollout

Once implemented and tested:

```bash
python3 tools/edit-config/edit_config.py --config lazer_new.json \
    --set-ric-mapping --from-csv prune.txt --dry-run

python3 tools/edit-config/edit_config.py --config lazer_new.json \
    --set-ric-mapping --from-csv prune.txt --apply
```

Expected outcome: 25 changes (empty → filled), 0 warnings (the 2 already-correct feeds are
silent NOOPs, not warnings, per existing `SetRicMapping` semantics).
