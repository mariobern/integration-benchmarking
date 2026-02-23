# Plan: Generate Source Upload CSV from Ticker Symbols

## Context

When onboarding new US equity instruments to Pyth Network, a `source_upload` CSV must be created that maps each ticker to its Reuters Instrument Code (RIC), Pyth identifiers, and metadata. Currently this is done manually. This script automates the process: given a list of tickers (e.g., `AAPL, NVDA, META`), it produces a CSV matching the `source_upload_15_Jan.csv` format by resolving RICs, company names, and Pyth feed IDs from multiple data sources.

**Key challenge**: The RIC exchange suffix (`.O` for NASDAQ, `.N` for NYSE, etc.) used by Datascope differs from the NASDAQ Trader listing exchange ~16% of the time. We address this with a Datascope-first lookup strategy.

## Output Format (target)

```csv
source_value, source_type, pyth_id, pythnet_id, pyth_lazer_id, valid_from, valid_to, ticker, asset_full_name, asset_class
AAPL.O,RIC,equity.aapl,Equity.US.AAPL/USD,922,,,AAPL,Apple Inc. Common Stock,Equity
TSM.Z,RIC,equity.tsm,Equity.US.TSM/USD,1436,,,TSM,Taiwan Semiconductor Manufacturing Company Ltd.,American Depositary Shares
```

## Implementation Steps

### Step 1: Create `generate_source_upload.py`

New file at root of repository.

**CLI interface**:

```
python generate_source_upload.py --tickers AAPL,NVDA,META
python generate_source_upload.py --ticker-file tickers.txt
python generate_source_upload.py --ticker-file tickers.txt --output source_upload.csv
python generate_source_upload.py --ticker-file tickers.txt --no-clickhouse   # offline mode
```

| Argument           | Description                                    | Default               |
| ------------------ | ---------------------------------------------- | --------------------- |
| `--tickers`        | Comma-separated ticker list                    | -                     |
| `--ticker-file`    | File with one ticker per line (or CSV)         | -                     |
| `--output`         | Output CSV path                                | `source_upload.csv`   |
| `--no-clickhouse`  | Skip ClickHouse lookups (offline mode)         | False                 |
| `--us-stocks-path` | Path to US-Stock-Symbols repo                  | `../US-Stock-Symbols` |
| `--force-refresh`  | Re-download NASDAQ Trader data (ignores cache) | False                 |

### Step 2: Data Sources & Resolution Strategy

**Three-tier RIC resolution** (ordered by reliability):

1. **Tier 1 - Datascope ClickHouse** (most accurate): Query `datascope_global_equities_benchmark_data` for existing RICs matching the ticker.

2. **Tier 2 - NASDAQ Trader** (offline fallback): Download and parse `nasdaqlisted.txt` (all NASDAQ -> `.O`) and `otherlisted.txt` (Exchange column: `N`->`.N`, `P`->`.P`, `Z`->`.Z`, `A`->`.A`).

3. **Tier 3 - Default `.N`**: For tickers not found in any source, default to NYSE suffix and flag for manual review.

**Name resolution**: NASDAQ Trader -> US-Stock-Symbols repo -> fallback placeholder.

**pyth_lazer_id**: Look up from ClickHouse `feeds_metadata_latest` (symbol pattern `Equity.US.<TICKER>/USD`). Leave empty if not found.

**Asset class**: "American Depositary Shares" if name contains ADR keywords or country != US; "Equity" for everything else.

### Step 3: Script Structure

```
Data classes:     TickerInfo, SourceUploadRow
Data sources:     NasdaqTraderSource, USStockSymbolsSource, ClickHouseLookup
Core functions:   resolve_ticker(), classify_asset(), write_csv()
CLI:              main() with argparse
```

### Step 4: Edge Cases

| Edge Case                               | Handling                                   |
| --------------------------------------- | ------------------------------------------ |
| Ticker not in any source                | Default `.N` suffix, warn user             |
| Multiple Datascope RICs for same ticker | Prefer one with non-zero `pyth_lazer_id`   |
| BRK.B style tickers                     | Handle both `BRK.B` and `BRKb` forms       |
| Duplicate tickers in input              | De-duplicate, preserve order               |
| ClickHouse unavailable                  | `--no-clickhouse` flag; degrade gracefully |

## Existing Code to Reuse

- `load_config()` pattern from `publisher_feeds.py` for `config.yaml` loading
- `get_analytics_client()` from `check_benchmark_availability.py:72-82` for Datascope ClickHouse
- ClickHouse client pattern from `publisher_feeds.py` for feeds_metadata

## Verification

1. Offline: `python generate_source_upload.py --tickers AAPL,NVDA,TSM --no-clickhouse`
2. With ClickHouse: `python generate_source_upload.py --tickers AAPL,NVDA,TSM`
3. Compare output against `source_upload_15_Jan.csv` format
4. Spot-check RICs against `benchmark_availability/instruments_2026-02-05.csv`

## Status

- [ ] Create `generate_source_upload.py`
- [ ] Test offline mode
- [ ] Test with ClickHouse
- [ ] Verify output format matches `source_upload_15_Jan.csv`
