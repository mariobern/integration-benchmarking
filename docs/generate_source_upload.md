# Source Upload CSV Generator

Generates `source_upload` CSV files for Datascope US equity instrument onboarding. Given a list of ticker symbols, resolves each to its Reuters Instrument Code (RIC), company name, Pyth identifiers, and asset classification.

## Usage

```bash
# From comma-separated tickers
python generate_source_upload.py --tickers AAPL,NVDA,META

# From a file (one ticker per line or CSV first column)
python generate_source_upload.py --ticker-file tickers.txt

# Custom output path
python generate_source_upload.py --tickers AAPL,NVDA --output my_upload.csv

# Offline mode (skip ClickHouse, use NASDAQ Trader only)
python generate_source_upload.py --tickers AAPL,NVDA --no-clickhouse

# Force re-download NASDAQ Trader data (ignore 24h cache)
python generate_source_upload.py --tickers AAPL --force-refresh
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--tickers` | Comma-separated ticker list (e.g., `AAPL,NVDA,META`) | - |
| `--ticker-file` | File with one ticker per line (or CSV) | - |
| `--output` | Output CSV path | `source_upload.csv` |
| `--no-clickhouse` | Skip ClickHouse lookups (offline mode) | False |
| `--us-stocks-path` | Path to US-Stock-Symbols repo | `../US-Stock-Symbols` |
| `--force-refresh` | Re-download NASDAQ Trader data (ignores cache) | False |

> `--tickers` and `--ticker-file` are mutually exclusive; one is required.

## RIC Resolution Strategy

The script uses a three-tier strategy to resolve each ticker to its RIC, ordered by reliability:

### Tier 1: Datascope ClickHouse (most accurate)

Queries `datascope_global_equities_benchmark_data` for existing RICs matching the ticker. This returns the exact RIC that Datascope uses for benchmarking, so benchmark comparisons will be consistent.

If multiple RICs exist for the same ticker (e.g., `TSM.N` and `TSM.Z`), the one with the most data rows is preferred. A warning is emitted.

### Tier 2: NASDAQ Trader (offline fallback)

Downloads and parses two files from `nasdaqtrader.com`:
- `nasdaqlisted.txt` — All NASDAQ-listed securities (assigned `.O` suffix)
- `otherlisted.txt` — NYSE, ARCA, BATS, AMEX securities (exchange column maps to `.N`, `.P`, `.Z`, `.A` suffixes)

Files are cached locally in `.nasdaq_cache/` with a 24-hour TTL. Use `--force-refresh` to bypass the cache.

This tier is correct for ~84% of tickers. The ~16% discrepancy is because Datascope sometimes uses a different exchange suffix than what NASDAQ Trader reports.

### Tier 3: Default `.N` (last resort)

Tickers not found in any source default to NYSE suffix (`.N`) and are flagged for manual review in the warnings output.

## Name Resolution

Company names are resolved from:
1. **NASDAQ Trader** listings (primary)
2. **US-Stock-Symbols** repo JSON files (fallback, also provides country for ADR detection)
3. **Ticker symbol itself** (final fallback, with warning)

## Asset Classification

Each ticker is classified as either:
- **Equity** — Default for US-domiciled companies, ETFs, and common stock
- **American Depositary Shares** — If the security name contains ADR-related keywords (`"american depositary"`, `"depositary shares"`, etc.) or if the company's country (from US-Stock-Symbols) is not "United States"

## Dotted Ticker Handling

Tickers with share class notation (e.g., `BRK.B`, `BF.B`) are converted to Datascope's RIC format:
- `BRK.B` → `BRKb.N` (lowercase class letter, no dot)
- `BRK.A` → `BRKa.N`
- `BF.B` → `BFb.N`

This matches Datascope's convention where dotted share classes are represented with a lowercase letter appended to the base symbol.

## Output Format

The output CSV matches the `source_upload_15_Jan.csv` format:

```csv
source_value, source_type, pyth_id, pythnet_id, pyth_lazer_id, valid_from, valid_to, ticker, asset_full_name, asset_class
AAPL.O,RIC,equity.aapl,Equity.US.AAPL/USD,922,,,AAPL,Apple Inc. - Common Stock,Equity
TSM.N,RIC,equity.tsm,Equity.US.TSM/USD,1436,,,TSM,Taiwan Semiconductor Manufacturing Company Ltd.,American Depositary Shares
BRKb.N,RIC,equity.brk.b,Equity.US.BRK.B/USD,,,,BRK.B,Berkshire Hathaway Inc. New Common Stock,Equity
```

| Column | Description |
|--------|-------------|
| `source_value` | RIC (e.g., `AAPL.O`) |
| `source_type` | Always `RIC` |
| `pyth_id` | `equity.<ticker_lower>` |
| `pythnet_id` | `Equity.US.<TICKER>/USD` |
| `pyth_lazer_id` | Numeric feed ID from `feeds_metadata_latest`, or empty |
| `valid_from` | Empty (for manual entry) |
| `valid_to` | Empty (for manual entry) |
| `ticker` | Original ticker symbol |
| `asset_full_name` | Company/security name |
| `asset_class` | `Equity` or `American Depositary Shares` |

> **Note:** The header uses spaces after commas but data rows do not. This matches the existing `source_upload_15_Jan.csv` convention.

## Input Formats

### Comma-separated (`--tickers`)

```
AAPL,NVDA,META,TSM,BRK.B
```

### File (`--ticker-file`)

One ticker per line:
```
AAPL
NVDA
META
# comments are skipped
TSM
```

Or CSV (first column is used, header rows like `ticker` or `symbol` are auto-detected and skipped):
```
ticker,other_column
AAPL,whatever
NVDA,whatever
```

Duplicates are automatically removed while preserving input order.

## Console Summary

After processing, the script prints a resolution summary:

```
============================================================
RESOLUTION SUMMARY
============================================================
Total tickers: 5

RIC resolution source:
  Datascope ClickHouse: 3
  NASDAQ Trader:        2
  Default (.N):         0

With pyth_lazer_id: 4/5
Without pyth_lazer_id: 1/5

Warnings (1):
  TSM: Multiple Datascope RICs: TSM.N, TSM.Z; using TSM.N
```

## Data Sources

| Source | What It Provides | Requires |
|--------|-----------------|----------|
| Datascope ClickHouse (`analytics_clickhouse`) | RICs, `pyth_lazer_id` | `config.yaml` credentials |
| Lazer ClickHouse (`lazer_clickhouse_prod`) | `pyth_lazer_id` via `feeds_metadata_latest` | `config.yaml` credentials |
| NASDAQ Trader (`nasdaqtrader.com`) | Exchange listing, security names | Internet (cached 24h) |
| US-Stock-Symbols repo (`../US-Stock-Symbols`) | Company names, country | Local clone |

## Troubleshooting

### ClickHouse connection fails
The script gracefully falls back to offline mode (NASDAQ Trader only). You can also use `--no-clickhouse` explicitly.

### NASDAQ Trader download fails
If a cached version exists, it uses the stale cache with a warning. If no cache exists, the script errors out.

### Ticker format validation fails
Only tickers matching `[A-Z]{1,5}(\.[A-Z])?` are accepted. Invalid formats are skipped with a warning.
