# Equity Instrument Types (spot / future / perp) — Design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)
**Branch:** `feat/equity-instrument-types`, stacked on
`feat/publisher-asset-map-sessions` (PR #48) — will become PR #50.

## Problem

`categorize_asset_class` labels every equity feed `equity-<country>`, collapsing
distinct instrument types into one bucket:

- **Equity index futures** (`Equity.US.DMM6/USD` = Dow Mini, `Equity.HK.HKHF6/HKD`
  = Hang Seng, `Equity.KR.KQH6/KRW` = KOSDAQ) are labeled the same as spot stocks.
- **Equity perpetuals** (`Pyth.DC.AAPL/USDT`) have no `Equity.` prefix, so they
  fall through to the default and are mislabeled `equity-us`.

The taxonomy conflates two orthogonal dimensions: **market/country** and
**instrument type** (spot / future / perp / index).

## Key finding: the metadata already carries `instrument_type`

`feeds_metadata_latest.metadata` is a JSON blob whose `items` include an
`instrument_type` key. Across the 1,873 `asset_type='equity'` feeds:

| instrument_type | count | notes                                                           |
| --------------- | ----- | --------------------------------------------------------------- |
| `spot`          | 1692  | regular spot equities — including the German "collisions" below |
| `future`        | 26    | explicitly labeled futures                                      |
| `index`         | 22    | `Equity.Index.*` (already → `equity-index` via prefix parse)    |
| `perp`          | 33    | `Pyth.DC.*/USDT` equity perpetuals                              |
| missing (None)  | 83    | 43 real futures (US/HK/KR index futures) + 40 spot              |

Two consequences:

1. **Authoritative where present.** The German false positives the symbol
   heuristic trips on (`Equity.DE.MUV2/EUR` = Munich Re, `HEN3`, `PAH3`, `DN3`)
   all carry an explicit `instrument_type='spot'`. So they are handled correctly
   by metadata and never reach the heuristic.
2. **Incomplete.** 83 feeds lack the field; 43 of those are real index futures
   (`US500*`, `US100*`, `US30*`, some `DM*/EM*/NM*`, all HK `HKH*`, all KR
   `KQ*/KS*`). Metadata alone would mislabel these as non-future.

Within the missing bucket, `lib.symbol_utils.is_futures_symbol` is collision-free
(the 43 real futures test True; the 40 spot — `.EXT` variants, `Equity.GB.HL`,
`Equity.US.ANSS` — test False). So a metadata-primary + heuristic-fallback rule
is both authoritative and complete, with **no curve heuristic required**.

## Scope decisions (resolved during brainstorming)

| Decision             | Choice                                                                   |
| -------------------- | ------------------------------------------------------------------------ |
| Instrument types     | spot, future, perp (index already handled via prefix)                    |
| Futures label        | market-aware `equity-<cc>-futures`                                       |
| Perp label           | flat `equity-perp` (fixes `Pyth.DC.*` mislabel from `equity-us`)         |
| Detection            | metadata `instrument_type`, fallback `is_futures_symbol`                 |
| `categorize` default | `instrument_type=None` ⇒ today's behavior (publisher_feeds.py untouched) |
| Sessions / console   | unchanged; "by session" line stays spot-US (`equity-us`)                 |
| Other asset classes  | unchanged (equities only)                                                |

## Resolution & labels

Resolve each equity feed's instrument type, then map to a label:

| resolved instrument_type | label                                                   |
| ------------------------ | ------------------------------------------------------- |
| `spot`                   | `equity-<country>`                                      |
| `future`                 | `equity-<country>-futures`                              |
| `perp`                   | `equity-perp`                                           |
| `index`                  | `equity-index` (unchanged — via `Equity.Index.` prefix) |

**Resolution rule** (pure):

```
resolve_instrument_type(raw, symbol):
    if raw:                      # metadata value present (spot/future/index/perp)
        return raw
    return "future" if is_futures_symbol(symbol) else "spot"
```

`<country>` comes from the existing `get_equity_country` (the `Equity.<CC>.`
prefix parse). For `perp`, the symbol (`Pyth.DC.<TICKER>/USDT`) has no country
code, so the label is the flat `equity-perp`.

## Code structure

- **`lib/asset_class.py`** — `categorize_asset_class(asset_type, symbol, instrument_type=None)`:
  ```
  if asset_type != "equity": return asset_type
  if instrument_type == "perp": return "equity-perp"
  country = get_equity_country(symbol)
  if instrument_type == "future": return f"equity-{country}-futures"
  return f"equity-{country}"
  ```
  The optional `instrument_type` defaults to `None` ⇒ unchanged behavior, so
  `publisher_feeds.py` (which does not pass it) is untouched. The metadata/heuristic
  _resolution_ lives in the caller, so the heuristic's false-positive risk never
  affects opt-out callers.
- **`lib/asset_class.py`** — pure `resolve_instrument_type(raw, symbol)` (above),
  importing `is_futures_symbol` from `lib.symbol_utils`.
- **`lib/asset_class.py`** — pure `parse_instrument_type(metadata_json: str) -> Optional[str]`:
  parse the `metadata` JSON `items` and return the `instrument_type` `stringValue`,
  or `None` if absent/unparseable.
- **`publisher_asset_map`** (`lib/publisher_asset_map_core.py`) — add
  `fetch_equity_instrument_types(client) -> dict[int, str]`:
  query `SELECT pyth_lazer_id, symbol, metadata FROM feeds_metadata_latest WHERE
asset_type='equity'`, and for each feed store `resolve_instrument_type(parse_instrument_type(metadata), symbol)`.
  In `fetch_publisher_feeds`, build this map once and pass
  `instrument_type=instr_map.get(feed_id)` into `categorize_asset_class`.

## Sessions & console (unchanged)

Session attribution still keys on `symbol.startswith("Equity.US.")`, so
`equity-us-futures` remains session-split while `equity-perp` and
`equity-hk/kr-futures` get `session=all`. The console "US-equity feeds by session"
line keeps matching exactly `equity-us` (now spot US equities — futures appear as
their own `equity-us-futures` rows in the detail/summary CSVs).

## Docs

Update `docs/asset-classes.md`: add the `equity-<cc>-futures` and `equity-perp`
labels, document that instrument type comes from `metadata.instrument_type` with a
`is_futures_symbol` fallback, and **bump the stale `Last updated` date** (the doc
was last updated 2026-03-02).

## Testing

- `parse_instrument_type`: extracts `future`/`spot`/`perp`/`index` from real
  metadata JSON shape `{"items":[{"key":"instrument_type","value":{"stringValue":...}}]}`;
  returns `None` for absent key / malformed JSON.
- `resolve_instrument_type`: present value passes through; missing → `future` for
  `Equity.US.DMM6/USD`, `spot` for `Equity.US.ANSS/USD`.
- `categorize_asset_class` with `instrument_type`:
  - `("equity", "Equity.US.DMM6/USD", "future")` → `equity-us-futures`
  - `("equity", "Equity.HK.HKHF6/HKD", "future")` → `equity-hk-futures`
  - `("equity", "Pyth.DC.AAPL/USDT", "perp")` → `equity-perp`
  - `("equity", "Equity.DE.MUV2/EUR", "spot")` → `equity-de` (NOT futures)
  - `("equity", "Equity.US.AAPL/USD", None)` → `equity-us` (default preserved)
  - non-equity passthrough unaffected.
- `fetch_publisher_feeds` (fake client): the instrument-type map drives the
  futures/perp labels through to the output rows.
- Live smoke: confirm `equity-us-futures` / `equity-hk-futures` / `equity-kr-futures`
  and `equity-perp` appear, German spots stay `equity-de`, and runtime is unaffected.

## Non-goals (YAGNI)

- No `index` relabel (already `equity-index` via the prefix parse).
- No country on perps (`equity-perp` is flat; the symbol has no country code).
- No change to `publisher_feeds.py` (it opts out by not passing `instrument_type`).
- No instrument typing for non-equity asset classes (commodities, fx, etc.).
- No curve/contract-count heuristic (metadata makes it unnecessary).
