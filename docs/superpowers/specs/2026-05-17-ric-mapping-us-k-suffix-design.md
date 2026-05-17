# US-equity RIC suffix rule: consolidated `.K` / bare

**Status:** Design approved 2026-05-17
**Scope:** `generate_ric_mapping.py`, `check_benchmark_availability.py` (categorizer), and their tests
**Author:** mario@pyth.network

## Problem

`generate_ric_mapping.py` currently emits per-venue RIC suffixes for US-consolidated equities: `.N` (NYSE), `.P` (NYSE Arca), `.A` (NYSE American), `.Z` (Cboe BZX). LSEG's actual consolidated-tape convention does not use those venue codes — it uses a single rule across all four venues:

- **root length ≥ 4 chars** → append `.K`
- **root length ≤ 3 chars** → no suffix at all (bare RIC)

Examples from the LSEG reference table: `IBM`, `TWTR.K`, `BRKa`, `SPY`, `CBOE.K`.

Our current output (`JPM.N`, `SPY.P`, `CBOE.Z`) does not match what Datascope expects for the consolidated tape, and the per-venue suffixes are a source of confusion when reading mappings.

## Goal

Replace the per-venue suffix logic with the consolidated-tape rule for the four US-consolidated venues. NASDAQ (`.O`) and IEX (`.K`) keep their current suffixes.

## Non-goals

- No CLI flag to opt into legacy `.N`/`.P`/`.A`/`.Z` output. We flip the default.
- No changes to non-equity asset classes (FX, metals, rates, futures).
- No re-issuing of historical RIC mappings already loaded into Datascope. This change affects future generation only.

## Design

### Suffix policy

| Exchange code (NASDAQ Trader) | Venue           | New suffix                                                          |
| ----------------------------- | --------------- | ------------------------------------------------------------------- |
| (matched in `_nasdaq` dict)   | NASDAQ Listings | `.O` (unchanged)                                                    |
| `N`                           | NYSE            | `.K` if root ≥ 4, else bare                                         |
| `P`                           | NYSE Arca       | `.K` if root ≥ 4, else bare                                         |
| `A`                           | NYSE American   | `.K` if root ≥ 4, else bare                                         |
| `Z`                           | Cboe BZX        | `.K` if root ≥ 4, else bare                                         |
| `V`                           | IEX             | `.K` (unchanged)                                                    |
| any other / unknown code      | —               | `.K` if root ≥ 4, else bare (with low-confidence warning, as today) |

"Bare" means the RIC base with no trailing `.X` suffix at all — e.g. `IBM`, `SPY`, `BRKa`.

### Root-length definition

Root length is the length of the **base ticker before the class-letter transform**:

| Input ticker | Root   | Length | RIC base | Final RIC |
| ------------ | ------ | ------ | -------- | --------- |
| `IBM`        | `IBM`  | 3      | `IBM`    | `IBM`     |
| `TWTR`       | `TWTR` | 4      | `TWTR`   | `TWTR.K`  |
| `SPY`        | `SPY`  | 3      | `SPY`    | `SPY`     |
| `CBOE`       | `CBOE` | 4      | `CBOE`   | `CBOE.K`  |
| `BABA`       | `BABA` | 4      | `BABA`   | `BABA.K`  |
| `BRK.B`      | `BRK`  | 3      | `BRKb`   | `BRKb`    |
| `BRK.A`      | `BRK`  | 3      | `BRKa`   | `BRKa`    |
| `BRK-B`      | `BRK`  | 3      | `BRKb`   | `BRKb`    |

Rule: if the input ticker ends with `.X` or `-X` where X is a single alphabetic character, strip that class suffix to get the root; otherwise the root is the full ticker.

### Code changes (`generate_ric_mapping.py`)

1. **Add helper** `_root_length(ticker: str) -> int`:

   ```python
   def _root_length(ticker: str) -> int:
       """Length of the base ticker before any class-letter suffix.

       BRK.B -> 3 (root = "BRK"); BRK-B -> 3; IBM -> 3; TWTR -> 4.
       """
       upper = ticker.upper()
       if len(upper) >= 2 and upper[-2] in ".-" and upper[-1].isalpha():
           return len(upper) - 2
       return len(upper)
   ```

2. **Add helper** `_us_consolidated_suffix(root_len: int) -> str`:

   ```python
   def _us_consolidated_suffix(root_len: int) -> str:
       """LSEG consolidated-tape suffix rule for NYSE/Arca/American/Cboe BZX."""
       return ".K" if root_len >= 4 else ""
   ```

3. **Remove** `OTHER_EXCHANGE_SUFFIX_MAP` entirely. The new code branches on `exchange == "V"` for IEX and falls through to the consolidated rule for everything else, so the map is no longer needed.

4. **Update `EquityResolver.resolve`** (`generate_ric_mapping.py:310-323`):

   ```python
   def resolve(self, ticker: str) -> Optional[str]:
       self._ensure_loaded()
       upper = ticker.upper()
       ric_base = ticker_to_ric_base(upper)
       root_len = _root_length(upper)

       for form in [upper, ric_base]:
           if form in self._nasdaq:
               return f"{ric_base}.O"
           if form in self._other:
               exchange, _ = self._other[form]
               if exchange == "V":
                   return f"{ric_base}.K"
               return f"{ric_base}{_us_consolidated_suffix(root_len)}"
       return None
   ```

5. **Update the low-confidence fallback** (`generate_ric_mapping.py:594-601`) to use the same rule:

   ```python
   ric_base = ticker_to_ric_base(equity_ticker)
   suffix = _us_consolidated_suffix(_root_length(equity_ticker))
   result.ric = f"{ric_base}{suffix}"
   result.confidence = "low"
   result.warnings.append(
       f"Defaulting to {result.ric} — verify exchange suffix"
   )
   ```

### Code changes (`check_benchmark_availability.py`)

Update `categorize_equities` (line 123-138) so it doesn't silently file every new US-equity RIC under "Other":

- `.O` / `.OQ` → NASDAQ (unchanged)
- `.K` or bare ticker shape (no dot extension) → "US Consolidated"
- Legacy `.N` / `.NY` / `.A` / `.Z` → keep recognizing them as historical NYSE / NYSE Arca / BATS so old data still categorizes (read-only diagnostic; doesn't have to be perfect).

The categorizer is diagnostic output; venue granularity beyond NASDAQ vs. consolidated is acceptable to lose.

### Tests (`tests/test_generate_ric_mapping.py`)

Existing tests to update:

- `test_nyse_ticker` (line 446): expected RIC changes from `JPM.N` → `JPM` (root = 3).
- `test_dotted_ticker` (line 459): expected RIC changes from `BRKb.N` → `BRKb` (root = 3).

New tests to add (in `TestEquityResolver`):

- `test_consolidated_short_root_nyse_is_bare`: `IBM` on `N` → `IBM`
- `test_consolidated_long_root_nyse_gets_dot_k`: `TWTR` on `N` → `TWTR.K`
- `test_consolidated_short_root_arca_is_bare`: `SPY` on `P` → `SPY`
- `test_consolidated_long_root_cboe_bzx_gets_dot_k`: `CBOE` on `Z` → `CBOE.K`
- `test_consolidated_nyse_american_long_root_gets_dot_k`: pick a 4+-char American-listed ticker → `.K`
- `test_consolidated_iex_unchanged`: a ticker on `V` → still `.K`
- `test_consolidated_nasdaq_unchanged`: a ticker in `_nasdaq` → still `.O` (already covered by `test_nasdaq_ticker`, leave as-is)
- `test_consolidated_dotted_long_root` (constructed): hypothetical `LONG.B` on `N` → `LONGb.K` (root = 4)

New tests for `_root_length` directly:

- `IBM` → 3, `TWTR` → 4, `BRK.B` → 3, `BRK-B` → 3, `BRK` → 3, `BABA` → 4, `A` → 1, `AB` → 2.

New test for the fallback path (`TestRICResolver` or similar): a ticker not found in either NASDAQ Trader file should still return `<ric_base>.K` (if root ≥ 4) or bare (if root ≤ 3), with a low-confidence warning.

### Downstream impact

Anything that parses RIC strings looking for `.N` / `.P` / `.A` / `.Z` to infer the venue will be affected. Quick grep within this repo:

- `generate_source_upload.py` and the Datascope onboarding flow use the generated CSV as input; they pass the RIC through to Datascope, not parse it. Safe.
- `isin_resolver.py` / `isin_resolver_v2.py`: ticker resolution, not RIC parsing. Safe.
- `check_benchmark_availability.py:123-138` (`categorize_equities`): **affected.** Categorizes equities by RIC suffix (`.N` → NYSE, `.A` → NYSE Arca, `.Z` → BATS). With the new rule, all four consolidated venues collapse into `.K` or bare, and this categorizer can no longer tell them apart from the RIC alone. Update to recognize `.K` (group as "US consolidated") and bare US-equity-shaped RICs (also "US consolidated"); keep `.O` for NASDAQ. Venue granularity beyond NASDAQ vs. consolidated is no longer recoverable from the RIC and would need to come from `lazer_symbols.json` if needed. This is acceptable for the categorizer's diagnostic purpose.

Datascope itself accepts both the venue-coded RICs and the consolidated form for the same underlying security. The bare/`.K` form is the consolidated tape, which is what we want for benchmark queries.

### Migration notes

- Existing `ric_mappings.csv` files written by past runs are not rewritten by this change. Re-run `generate_ric_mapping.py` for any ticker list where you want the new RIC.
- The `lazer_symbols.json` `benchmarkMapping.datascope_ric.identifiers` entries already in `after.json` are not touched by this script. Manual / scripted updates needed if you want existing mappings re-keyed.

## Risks

1. **Datascope downstream behavior**: if a particular Datascope query path _requires_ venue-suffixed RICs for certain securities, the bare/`.K` form may return different data or fail to resolve. Mitigation: spot-check a handful of resulting RICs against Datascope before merging.
2. **Test fixture coverage gaps**: the existing fixtures don't have NYSE American tickers; we'll add one.
3. **Unknown class-letter conventions**: `_root_length` strips `.X` or `-X` where X is a single letter. A ticker like `FOO.WS` (warrants) wouldn't strip and would be treated as length 6. That's probably correct — those aren't class shares — but worth flagging in code review.

## Out of scope

- A CLI flag to retain legacy suffixes.
- Rewriting historical mappings.
- Changes to non-equity resolvers.
- Updating `after.json` `datascope_ric` identifiers automatically.

## Acceptance criteria

- `EquityResolver.resolve("IBM")` returns `"IBM"` (on `N`).
- `EquityResolver.resolve("TWTR")` returns `"TWTR.K"` (on `N`).
- `EquityResolver.resolve("SPY")` returns `"SPY"` (on `P`).
- `EquityResolver.resolve("BRK.B")` returns `"BRKb"` (on `N`).
- `EquityResolver.resolve("CBOE")` returns `"CBOE.K"` (on `Z`).
- NASDAQ-listed and IEX-listed RICs unchanged.
- Updated and new tests pass; `pytest tests/test_generate_ric_mapping.py` green.
