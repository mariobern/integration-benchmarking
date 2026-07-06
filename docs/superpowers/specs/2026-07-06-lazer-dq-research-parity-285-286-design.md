# Design: Parity with research PRs #285 + #286 for `evaluate_feeds_bulk`

**Date:** 2026-07-06
**Author:** Mario Bernardi (with Claude)
**Status:** Approved — ready for implementation plan

## Goal

Bring the `lazer_dq` benchmarking engine (`evaluate_feed_standalone.py`) and its batch
driver (`evaluate_feeds_bulk.py`) to parity with two merged improvements in
`pyth-network/research`:

- **PR #285** — additional qualifier filter for futures.
- **PR #286** — RIC-based benchmark queries (resolved from `market_schedules`), UST price
  support, and a `us-equities-on` overnight alias.

Both PRs modify `pythresearch/data_quality/lazer/publisher_benchmark_eval.ipynb`, which is the
upstream notebook our engine was forked from.

## Scope

### In scope

| #     | Change                                                                                                                                    | Source  | Decision                                                  |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------- | --------------------------------------------------------- |
| **A** | Broaden the **futures** qualifier filter                                                                                                  | PR #285 | Port as-is                                                |
| **B** | Split `us-treasuries` → `us-treasuries-yield` + `us-treasuries-price`                                                                     | PR #286 | **Exact rename** (no back-compat alias)                   |
| **C** | Add `us-equities-on` as an alias for `us-equities-overnight`                                                                              | PR #286 | Port as-is                                                |
| **D** | Query benchmark tables by **`ric`** resolved from `market_schedules.benchmarkMapping.datascope_ric`, instead of `pyth_lazer_id = feed_id` | PR #286 | **Full parity — `ric` only**, no `pyth_lazer_id` fallback |

All edits are confined to the `lazer_dq/` subsystem plus its docs/tests.

### Out of scope

- **Crypto benchmarking against Coinpaprika.** Crypto feeds carry a `coinpaprika_symbol`
  identifier (e.g. `btc-bitcoin` for `Crypto.BTC/USD`), _not_ a `datascope_ric`, and there is
  no Datascope crypto table. The RIC resolver is written to make this a clean future
  extension (parameterized identifier key) but the crypto query path is **not** built here.
- **The other benchmarking scripts** (`quick_benchmark.py`, `feed_readiness.py`, etc.) and
  `lib/config.py` asset-class normalization — they use a separate mode/asset vocabulary and
  are not touched.
- **Two pre-existing issues** (see "Known pre-existing issues" below) — noted, not fixed.

## Decisions and rationale

### D — full RIC parity, no fallback

The engine currently joins Datascope tables by `pyth_lazer_id = feed_id` for every mode
except overnight (which uses a derived `'{ticker}.BLUE'`). PR #286 instead resolves the RIC
from the feed's `market_schedules` and queries by `ric`.

- **Chosen:** always query by the resolved `ric`, matching the notebook exactly.
- **Missing-RIC behavior:** if a feed's `market_schedules` has no `datascope_ric` for the
  relevant session, `ric` is `None`, and the feed is **soft-skipped** with `sys.exit(2)` —
  the same non-trading-day / un-ingested-feed path already contracted in `CLAUDE.md`
  (`evaluate_feeds_bulk` treats every non-zero engine exit as a soft failure and continues to
  the next row). No crash; the batch run proceeds.
- **Blast radius:** any feed that benchmarks today via `pyth_lazer_id` but lacks a
  `datascope_ric` mapping in `market_schedules` will flip from benchmarked to skipped. This is
  an accepted, understood consequence of full parity — a config-completeness question about
  the feed fleet, not a code question.

### B — exact rename

`us-treasuries` is replaced by `us-treasuries-yield` and `us-treasuries-price`. Any existing
CSV row or doc that still says `us-treasuries` will fail fast (unknown mode → `benchmark_query`
unassigned → error) until updated. This is the deliberate choice for byte-for-byte parity.

## Architecture

### Component 1 — RIC resolver (new, `lazer_dq/benchmark_identifiers.py`)

A pure-stdlib module (no pandas, no DB) so it is unit-testable in isolation.

```python
SESSION_BY_MODE = {
    "us-equities":           "REGULAR",
    "us-equities-pre":       "PRE_MARKET",
    "us-equities-post":      "POST_MARKET",
    "us-equities-on":        "OVER_NIGHT",
    "us-equities-overnight": "OVER_NIGHT",
}
# Any mode not listed resolves to the REGULAR session.

def resolve_benchmark_identifier(
    market_schedules,                 # list[dict] | JSON str | None
    session_name: str,                # e.g. "REGULAR", "OVER_NIGHT"
    identifier_key: str = "datascope_ric",
) -> str | None:
    """Return the identifier string for the given session, or None.

    - Parses market_schedules if it is a JSON string.
    - Finds the session entry whose "session" == session_name.
    - Reads benchmarkMapping[identifier_key]["identifiers"].
    - Returns the identifier whose "validFrom" is the maximum (most recently
      valid); None if no session / mapping / identifiers are present.
    """
```

**Design intent:** `identifier_key` is a parameter so a later Coinpaprika path is a one-arg
reuse (`identifier_key="coinpaprika_symbol"`). For `datascope_ric`, crypto feeds return
`None` (they only have `coinpaprika_symbol`), so they soft-skip with no special-casing.

Mirrors the notebook's parsing: handle `market_schedules` arriving as either a JSON string or
an already-parsed list, and pick the identifier with the maximum `validFrom`.

### Component 2 — Engine (`lazer_dq/evaluate_feed_standalone.py`)

1. **Metadata query (~line 939):** add `market_schedules` to the `SELECT` from
   `feeds_metadata_latest`.
2. **RIC resolution (~line 955, right after `symbol`/`ticker` are set):**
   ```python
   session_name = SESSION_BY_MODE.get(mode, "REGULAR")
   ric = resolve_benchmark_identifier(
       df_feed_metadata["market_schedules"].iloc[0], session_name
   )
   print(f"Mode: {mode} -> session: {session_name}, RIC: {ric}")
   ```
3. **Benchmark query branches (lines 1113–1230)** — every branch rewritten to key on `ric`:
   - `SELECT` gains `ric, {feed_id} as feed_id` (replacing `pyth_lazer_id as feed_id`).
   - `WHERE ... AND pyth_lazer_id = '{feed_id}'` → `AND ric = '{ric}'`.
   - `ORDER BY benchmark_timestamp ASC, pyth_lazer_id` → `..., ric`.
   - Overnight branch: `AND ric = '{ticker}.BLUE'` → `AND ric = '{ric}'` (the OVER_NIGHT
     session's `datascope_ric` already resolves to `AAPL.BLUE` per the config).
4. **`ric is None` guard (new):** before running the benchmark query, if `ric is None`, print
   a clear message (`no datascope RIC configured for feed <id> / session <session_name>`) and
   `sys.exit(2)`. Same soft-skip outcome as the notebook, but avoids emitting a junk
   `ric = 'None'` query and produces a log line distinguishable from "RIC configured but
   market closed / holiday." _(This is the single refinement over the upstream notebook. If
   byte-for-byte parity is preferred, drop the guard and let the `ric = 'None'` query return
   zero rows into the existing empty-result `sys.exit(2)` at line 1273.)_
5. **A — futures filter:** in the `us-futures` branch, replace
   ```sql
   qualifiers NOT LIKE 'SBL[OFFBK_TYPE];K[BLKSALCOND]%'
   AND qualifiers NOT LIKE 'Spread Price|Spread Volume[USER]%'
   AND qualifiers NOT LIKE 'Block Trade[USER]%'
   ```
   with
   ```sql
   qualifiers NOT LIKE '%SBL[OFFBK_TYPE]%'
   AND qualifiers NOT LIKE '%SYS[OFFBK_TYPE]%'
   AND qualifiers NOT LIKE '%Spread Price|Spread Volume[USER]%'
   AND qualifiers NOT LIKE 'Block Trade[USER]%'
   ```
6. **B — treasuries:** rename `elif mode == "us-treasuries":` → `elif mode ==
"us-treasuries-yield":` (yield/bid_yield/ask_yield columns), and add
   `elif mode == "us-treasuries-price":` selecting `price`, `bid_price`, `ask_price`.
7. **C — overnight alias:** change both engine sites that match the overnight mode to
   `mode in ("us-equities-overnight", "us-equities-on")`:
   - the benchmark-query branch (line 1167),
   - the time-label / session-window block (line 126).
8. **Mode help text (line 846):** list `us-equities-on`, `us-treasuries-yield`,
   `us-treasuries-price`; remove bare `us-treasuries`.

### Component 3 — Bulk driver (`lazer_dq/evaluate_feeds_bulk.py`)

`compute_times_from_mode` (line 48): the `us-equities-overnight` branch also matches
`us-equities-on` (same 20:00–21:00 window). The two treasuries modes need no special case —
they fall through to the default REGULAR (09:30–10:30) window. Confirm no mode validation
rejects the new modes.

### Component 4 — Tests & docs

- **New** `lazer_dq/tests/test_benchmark_identifiers.py`:
  - `SESSION_BY_MODE` maps each mode to the expected session (default REGULAR).
  - most-recent-`validFrom` selection among multiple identifiers.
  - missing session, missing `benchmarkMapping`, missing `identifiers` → `None`.
  - crypto feed with only `coinpaprika_symbol` → `None` under `datascope_ric`, and the
    identifier is returned when queried with `identifier_key="coinpaprika_symbol"`.
  - `market_schedules` passed as a JSON string is parsed.
- **Extend** engine/bulk tests: each mode builds a query string containing `ric =`;
  `us-equities-on` maps to the overnight window; `us-treasuries-price` selects `price`,
  `us-treasuries-yield` selects `yield`.
- **Docs:** update `docs/evaluate_feeds_bulk.md`, the engine `--mode` list, and the relevant
  `CLAUDE.md` gotchas (futures qualifier note; treasuries modes now `-yield` / `-price`).

## Data flow (per feed, mode-dependent)

```
feed_id, date, mode
    │
    ▼
feeds_metadata_latest ──► symbol, exponent, market_schedules
    │
    ▼
SESSION_BY_MODE[mode] ──► session_name
resolve_benchmark_identifier(market_schedules, session_name) ──► ric
    │
    ├── ric is None ─────► print + sys.exit(2)  (soft-skip; batch continues)
    │
    ▼
benchmark query  WHERE ric = '{ric}'  (per-mode table + columns + qualifier filter)
    │
    ├── empty ───────────► sys.exit(2)  (existing behavior)
    ▼
merge with publisher data ──► metrics ──► plots / stats / readiness
```

## Error handling

- **No RIC configured** → explicit `sys.exit(2)` with a distinguishable log message.
- **RIC configured but no benchmark rows** (holiday, market closed, un-ingested) → existing
  empty-result `sys.exit(2)` at line 1273.
- **Unknown/stale mode** (e.g. a stale `us-treasuries` CSV row after the rename) → `benchmark_query`
  is left unassigned; the resulting `UnboundLocalError` is caught by the engine's broad benchmark
  `except`, yielding an empty result and a soft `sys.exit(2)` (skip), same as any no-data case.
- `evaluate_feeds_bulk` treats every non-zero engine exit as a soft failure and proceeds to
  the next row.

## Verification

The engine cannot be run end-to-end here (requires ClickHouse credentials), so verification
rests on:

1. Unit tests for the resolver (`test_benchmark_identifiers.py`).
2. Query-string construction tests (each mode emits a `ric =` query with the right table and
   columns).
3. `pre-commit run --files <changed files>` (black, prettier, whitespace, EOF).

**Runtime assumption to confirm on first real run:** `feeds_metadata_latest` exposes a
`market_schedules` column. Confidence is high — the research notebook queries the same
`lazer_clickhouse_prod` cluster for exactly this column.

## Known pre-existing issues (noted, not fixed here)

1. **Overnight qualifier filter uses `OR` instead of `AND`** (engine lines ~1184–1189). An
   OR-chain of `NOT LIKE`s filters almost nothing. The PRs do not touch it, so it stays out of
   scope for this parity work.
2. **UST yield branch filters `AND price IS NOT NULL`** while selecting `yield`. Carried in
   both this codebase and the upstream notebook; parity preserves it.

## Definition of done

- [ ] `resolve_benchmark_identifier` + `SESSION_BY_MODE` implemented in
      `lazer_dq/benchmark_identifiers.py`.
- [ ] Engine metadata query selects `market_schedules`; RIC resolved per mode/session.
- [ ] All benchmark branches query by `ric`; overnight uses resolved RIC.
- [ ] `ric is None` guard → `sys.exit(2)`.
- [ ] Futures qualifier filter (A) broadened.
- [ ] `us-treasuries` renamed to `-yield`; `-price` added (B).
- [ ] `us-equities-on` alias wired in engine (both sites) + bulk driver (C).
- [ ] `--mode` help + docs + CLAUDE.md updated.
- [ ] New resolver tests + extended engine/bulk tests, all green.
- [ ] `pre-commit run` clean on changed files.
