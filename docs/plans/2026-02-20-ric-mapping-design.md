# Design: Universal RIC Mapping Generator

**Date:** 2026-02-20
**Script:** `generate_ric_mapping.py`

## Purpose

Generate `pyth_mappings_export`-format CSV files for onboarding new tickers into Datascope benchmarking. Given ticker(s), the script looks them up in `lazer_symbols.json`, derives the Reuters Instrument Code (RIC) using asset-class-specific rules, and outputs a CSV ready for Datascope instrument onboarding.

## Approach: Rule-Based Engine with Embedded Mapping Tables

RICs are proprietary to LSEG/Refinitiv — no free public API returns them. However, RIC patterns are deterministic for ~90% of asset classes. Only US equities require an external lookup (NASDAQ Trader) for exchange suffix determination.

| Asset Class | RIC Derivation | External Source |
|---|---|---|
| FX | `CCY=`, `CCYCCY=R`, `.DXY` | None — rule-based |
| Metals | `XAU=`, `XAG=`, `XPT=`, `XPD=` | None — fixed table |
| Rates | `US{TENOR}T=RRPS` | None — rule-based |
| Commodity Futures | `{RIC_ROOT}{MONTH}{YEAR2}` | None — mapping table |
| Equity Index Futures | `ESc1`, `NQc2`, `YMH26` | None — mapping table |
| US Equities/ETFs | `TICKER.{EXCHANGE}` | NASDAQ Trader |

## Architecture

```
User Input                    lazer_symbols.json
  (ticker)                      (2,989 entries)
     |                               |
     v                               v
  +-------------------------------------+
  |       Ticker -> Symbol Lookup       |
  |  "AAPL" -> Equity.US.AAPL/USD      |
  |  "AUDCAD" -> FX.AUD/CAD            |
  |  "CCH6" -> Commodities.CCH6/USD    |
  +----------------+--------------------+
                   |
                   v
  +-------------------------------------+
  |     Asset-Class RIC Resolver        |
  |                                     |
  |  equity   -> NASDAQ Trader + rules  |
  |  fx       -> FX RIC rules          |
  |  metal    -> Metal lookup table     |
  |  commodity-> Futures root mapping   |
  |  rates    -> Treasury RIC pattern   |
  +----------------+--------------------+
                   |
                   v
  +-------------------------------------+
  |      CSV Output Generator           |
  |  (pyth_mappings_export format)      |
  +-------------------------------------+
```

## Component 1: Ticker Lookup in lazer_symbols.json

Load `lazer_symbols.json` and build multiple indexes:
- **By `name`** (short ticker): `AAPL`, `AUDCAD`, `CCH6`
- **By Pyth ticker extracted from `symbol`**: `AAPL` from `Equity.US.AAPL/USD`
- **By `pyth_lazer_id`**: numeric feed ID

When user provides `AAPL`, the script finds the matching entry and extracts all metadata needed for CSV output.

## Component 2: Asset-Class RIC Rules

### FX

Parse `symbol` field, apply Reuters FX convention:
- `FX.EUR/USD` -> `EUR=` (major pair, base currency)
- `FX.USD/JPY` -> `JPY=` (USD-quoted, counter currency)
- `FX.AUD/CAD` -> `AUDCAD=R` (cross pair, concat + `=R`)
- `FX.USDXY` -> `.DXY` (special case, US Dollar Index)

Determining `=` vs `=R`:
- Pairs involving USD where USD is base/counter: `CCY=`
- Cross pairs (no USD): `CCYCCY=` or `CCYCCY=R`
- Some EUR/GBP crosses use `=` without `R` — derived from existing mappings

### Metals

Fixed lookup table:
```python
METAL_RIC_MAP = {"XAU": "XAU=", "XAG": "XAG=", "XPT": "XPT=", "XPD": "XPD="}
```

New metals (XCU, XTI, XAL, etc.) need manual RIC additions.

### Rates

Pattern: extract tenor from symbol, construct `US{TENOR}T=RRPS`:
- `Rates.US10Y` -> `US10YT=RRPS`
- `Rates.US3M` -> `US3MT=RRPS`

### Commodity Futures

Two-part mapping:

1. **Pyth code -> RIC root** (hardcoded table):
```python
FUTURES_PYTH_TO_RIC = {
    "CC": "HG",    # Copper (COMEX)
    "WTI": "CL",   # WTI Crude Oil
    "NGD": "NG",    # Natural Gas
    "AL": "ALI",   # Aluminum (LME) - note: RIC uses ALI not AL
    "PL": "PA",     # Palladium (Pyth PL = RIC PA)
    "PT": "PL",     # Platinum (Pyth PT = RIC PL)
    "UR": "UX",     # Uranium
    "CO": "C",      # Corn (CBOT)
    "BRENT": "LCO", # Brent Crude (ICE)
    "NID": "NK",    # Nikkei Index
}
```

2. **Construct RIC**: `{RIC_ROOT}{MONTH_CODE}{YEAR_2DIGIT}` (e.g., `HGH26`)

3. **Continuous contracts**: `ESc1`, `NQc2`, `LCOc1` — special handling for equity index and oil futures.

### Equity Index Futures

```python
INDEX_FUTURES_PYTH_TO_RIC = {
    "EM": "ES",   # E-Mini S&P 500
    "NM": "NQ",   # Nasdaq Mini
    "DM": "YM",   # Dow Mini
}
```

### US Equities / ETFs

NASDAQ Trader resolution (reuse logic from `generate_source_upload.py`):
- Download `nasdaqlisted.txt` / `otherlisted.txt` (cached 24h in `.nasdaq_cache/`)
- NASDAQ -> `.O`, NYSE -> `.N`, Arca -> `.P`, BATS -> `.Z`, IEX -> `.K`
- Dotted tickers: `BRK.B` -> `BRKb.N` (lowercase class, remove dot)

## Component 3: CSV Output

Produces exact `pyth_mappings_export` format:

| Column | Source |
|---|---|
| `source_value` | **RIC** (the resolved value) |
| `source_type` | Always `"RIC"` |
| `pyth_id` | Derived: `{asset_prefix}.{name_lower}` |
| `pythnet_id` | `lazer_symbols.json` -> `symbol` field |
| `pyth_lazer_id` | `lazer_symbols.json` -> `pyth_lazer_id` |
| `valid_from` | `1970-01-01 00:00:00` (default) |
| `valid_to` | Futures expiry if applicable |
| `ticker` | `lazer_symbols.json` -> `name` or extracted |
| `asset_full_name` | `lazer_symbols.json` -> `description` |
| `asset_class` | Derived from `asset_type` + metadata |

### Asset Class Derivation

| asset_type | asset_class in CSV |
|---|---|
| equity (US) | `Common Stock`, `American Depositary Shares`, `Equity`, etc. |
| fx | `Forex` |
| metal | `Metal` |
| commodity (futures) | `Commodity Future` |
| equity (futures) | `Equity Future` |
| rates | `Rates` |

For equities, classification uses ADR keywords in description and `nasdaq_symbol` field.

## Component 4: CLI Interface

```bash
# Single ticker
python generate_ric_mapping.py --ticker AAPL

# Multiple tickers
python generate_ric_mapping.py --ticker AAPL AUDCAD CCH6 XAU US10Y

# From file (one ticker per line)
python generate_ric_mapping.py --ticker-file new_tickers.txt

# Custom output path
python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv

# Append to existing mappings file
python generate_ric_mapping.py --ticker AAPL --append-to pyth_mappings_export.csv

# Custom lazer_symbols.json path
python generate_ric_mapping.py --ticker AAPL --symbols after.json
```

## Edge Cases

1. **Ticker not in lazer_symbols.json** -> Error with fuzzy match suggestion
2. **Non-benchmarkable asset types** (crypto, funding-rate, nav, kalshi, custom) -> Skip with warning
3. **New commodity code not in mapping table** -> Flag for manual RIC entry
4. **Dotted equity tickers** -> `ticker_to_ric_base()` conversion
5. **Continuous vs specific futures** -> Handle `c1`/`c2` patterns
6. **Non-US equities** (e.g., `Equity.FR.C3M/EUR`) -> Out of scope, skip with warning

## FX RIC Pattern Reference

### USD pairs: `CCY=`
The counter currency (or non-USD currency) becomes the RIC:
- `EUR=`, `GBP=`, `JPY=`, `CHF=`, `CAD=`, `AUD=`, `NZD=`
- `MXN=`, `BRL=`, `ZAR=`, `INR=`, `CNH=`, `CNY=`, `KRW=`, etc.

### Cross pairs: `CCYCCY=` or `CCYCCY=R`
Concatenation of base+quote currency codes:
- With `=R`: `AUDCAD=R`, `AUDCHF=R`, `CADCHF=R`, `NZDCAD=R`, `NZDCHF=R`
- Without `R`: `EURGBP=`, `EURJPY=`, `EURCAD=`, `GBPJPY=`, `GBPCAD=`, `AUDJPY=`

Rule: Pairs where both currencies are "majors" (EUR, GBP, JPY, AUD, NZD, CAD, CHF) and one is EUR or GBP tend to use `=`. Pairs among AUD/NZD/CAD/CHF crosses use `=R`.

### Special: `.DXY` (US Dollar Index)

## Futures RIC Mapping Tables

### Pyth Code -> RIC Root (Commodities)

| Pyth Code | RIC Root | Commodity | Exchange |
|---|---|---|---|
| CC | HG | Copper | COMEX |
| WTI | CL | WTI Crude Oil | NYMEX |
| NGD | NG | Natural Gas | NYMEX |
| AL | ALI | Aluminum | LME/COMEX |
| PL | PA | Palladium | NYMEX |
| PT | PL | Platinum | NYMEX |
| UR | UX | Uranium | COMEX |
| CO | C | Corn | CBOT |
| BRENT | LCO | Brent Crude | ICE |
| NID | NK | Nikkei 225 | CME |

### Pyth Code -> RIC Root (Equity Index Futures)

| Pyth Code | RIC Root | Index |
|---|---|---|
| EM | ES | E-Mini S&P 500 |
| NM | NQ | Nasdaq Mini |
| DM | YM | Dow Jones Mini |

### Month Codes (Universal)

F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec

### RIC Construction

- **Specific contract**: `{RIC_ROOT}{MONTH_CODE}{YEAR_2DIGIT}` (e.g., `HGH26`)
- **Continuous (front month)**: `{RIC_ROOT}c1` (e.g., `ESc1`, `CLc1`)
- **Continuous (2nd month)**: `{RIC_ROOT}c2` (e.g., `ESc2`, `CLc2`)
