# Universal RIC Mapping Generator

## Overview

`generate_ric_mapping.py` generates `pyth_mappings_export`-format CSV files for onboarding new tickers into Datascope benchmarking. Given ticker(s) or feed ID(s), looks them up in the reference file (`after.json` by default; `lazer_symbols.json` also supported), derives the Reuters Instrument Code (RIC) using asset-class-specific rules, and outputs a CSV ready for Datascope instrument onboarding. Supports all benchmarkable asset classes.

## Running RIC Mapping Generator

```bash
# Single ticker
python generate_ric_mapping.py --ticker AAPL

# Multiple tickers (all asset classes)
python generate_ric_mapping.py --ticker AAPL EURUSD AUDCAD XAUUSD CCH6 US10Y EMH6

# From a file (one ticker per line or CSV)
python generate_ric_mapping.py --ticker-file new_tickers.txt

# By feed ID (feedId in after.json / pyth_lazer_id in lazer_symbols.json)
python generate_ric_mapping.py --feed-id 922 327 346

# Custom output path
python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv

# Append to existing pyth_mappings file
python generate_ric_mapping.py --ticker AAPL --append-to pyth_mappings_export.csv

# Use lazer_symbols.json instead of the default after.json
python generate_ric_mapping.py --ticker AAPL --symbols lazer_symbols.json

# Force re-download NASDAQ Trader data
python generate_ric_mapping.py --ticker AAPL --force-refresh
```

## Arguments

One of `--ticker`, `--ticker-file`, or `--feed-id` is required (mutually exclusive).

| Argument          | Description                                                                 | Default            |
| ----------------- | --------------------------------------------------------------------------- | ------------------ |
| `--ticker`        | Ticker(s) to resolve (space-separated)                                      | -                  |
| `--ticker-file`   | File with tickers (one per line or CSV)                                     | -                  |
| `--feed-id`       | Feed ID(s) to resolve (`feedId` in after.json / `pyth_lazer_id` in symbols) | -                  |
| `--output`        | Output CSV path                                                             | `ric_mappings.csv` |
| `--symbols`       | Reference file path; `after.json` or `lazer_symbols.json` (auto-detected)   | `after.json`       |
| `--force-refresh` | Re-download NASDAQ Trader data                                              | False              |
| `--append-to`     | Append to existing CSV instead of creating new                              | -                  |

## RIC Resolution Rules

Rule-based resolution engine -- no ClickHouse or API dependencies (except NASDAQ Trader for equity exchange suffixes):

| Asset Class                 | RIC Pattern                           | Example                         |
| --------------------------- | ------------------------------------- | ------------------------------- |
| US Equities/ETFs            | `TICKER.{EXCHANGE}` via NASDAQ Trader | `AAPL.O`, `JPM.N`, `SPY.P`      |
| FX (USD pairs)              | Non-USD currency + `=`                | `EUR=`, `JPY=`, `AUD=`          |
| FX (cross, EUR/GBP)         | `BASECCY+QUOTECCY+=`                  | `EURGBP=`, `GBPJPY=`            |
| FX (cross, AUD/NZD/CAD/CHF) | `BASECCY+QUOTECCY+=R`                 | `AUDCAD=R`, `NZDCHF=R`          |
| FX (Dollar Index)           | `.DXY`                                | `.DXY`                          |
| Metals                      | Fixed lookup                          | `XAU=`, `XAG=`, `XPT=`, `XPD=`  |
| Rates                       | `US{TENOR}T=RRPS`                     | `US10YT=RRPS`, `US3MT=RRPS`     |
| Commodity Futures           | Pyth->RIC root mapping                | `HGH26` (copper), `CLJ26` (WTI) |
| Equity Index Futures        | EM->ES, NM->NQ, DM->YM                | `ESH26`, `NQH26`, `YMH26`       |

## Output Format

```csv
source_value,source_type,pyth_id,pythnet_id,pyth_lazer_id,valid_from,valid_to,ticker,asset_full_name,asset_class
AAPL.O,RIC,equity.aapl,Equity.US.AAPL/USD,922,1970-01-01 00:00:00,,AAPL,APPLE INC / US DOLLAR,Common Stock
EUR=,RIC,fx.eurusd,FX.EUR/USD,327,1970-01-01 00:00:00,,EURUSD,EURO / US DOLLAR,Forex
HGH26,RIC,future.cch6,Commodities.CCH6/USD,2931,1970-01-01 00:00:00,,CCH6,COPPER 27 MARCH 2026 / US DOLLAR,Commodity Future
```

## Edge Cases

- **Dotted tickers** (BRK.B) -- RIC uses `BRKb.N` format (lowercase class, no dot)
- **Duplicate names** in the reference file (e.g., AAPL with `.EXT` suffix, AAL as GB and US equity) -- prefers US, non-EXT, benchmarkable entries
- **Non-benchmarkable assets** (crypto, funding-rate, nav, etc.) -- skipped with warning
- **Non-US equities** (Equity.GB.\_, Equity.FR.\_) -- out of scope, skipped with warning
- **Unknown tickers** -- warning with fuzzy match suggestion
- **NASDAQ Trader caching** -- files cached in `.nasdaq_cache/` with 24h TTL; `--force-refresh` bypasses
- **Network failures** -- gracefully falls back to cached NASDAQ Trader data if available

## Confidence Levels

| Level    | Meaning                                                             |
| -------- | ------------------------------------------------------------------- |
| `high`   | Rule-based derivation (FX, metals, rates, futures) -- deterministic |
| `medium` | NASDAQ Trader lookup (US equities) -- correct ~84% of the time      |
| `low`    | Fallback to `.N` suffix -- needs manual verification                |

## Running Tests

```bash
pytest tests/test_generate_ric_mapping.py -v
```

## Programmatic Usage

```python
from generate_ric_mapping import RICResolver

resolver = RICResolver()
result = resolver.resolve("AAPL")
print(result.ric)          # AAPL.O
print(result.asset_class)  # Common Stock
print(result.confidence)   # medium

# Batch resolve
results = resolver.resolve_batch(["AAPL", "EURUSD", "CCH6", "US10Y"])

# Resolve by feed ID
result = resolver.resolve_by_id(922)
results = resolver.resolve_ids_batch([922, 327, 346])
```
