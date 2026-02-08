# ISIN Resolver v2

Enhanced ISIN resolver with enriched input, ADR detection, manual overrides, and currency validation.

## What's new in v2

| Feature | v1 | v2 |
|---------|----|----|
| Input format | Ticker only | Ticker + company name + denomination currency |
| ADR detection | None | OpenFIGI confirms ADRs; manual overrides correct ISINs |
| Manual overrides | None | CSV file for authoritative ISINs (Tier 0) |
| Currency validation | None | Flags suspicious ISIN prefixes for USD securities |
| Confidence scoring | Defined but unused | Populated: high/medium/low |
| Tiers | 2 (FinanceDatabase, yfinance) | 3 (Manual Override, FinanceDatabase, yfinance) |

## Resolution Strategy

Tiers are tried in order. The first tier that returns a valid ISIN wins.

| Tier | Source | Speed | Coverage |
|------|--------|-------|----------|
| **0. Manual Override** | `.isin_overrides/isin_overrides.csv` | Instant | Authoritative for listed tickers |
| **1. FinanceDatabase** | Local DB (158K+ equities) | Instant | ~55% of ric.csv tickers |
| **2. yfinance** | Yahoo Finance API | ~1-2s/ticker | ETFs + additional equities |
| **3. CUSIP computation** | python-stdnum | Instant | When CUSIP known but ISIN missing |

OpenFIGI is used for **ADR detection only** (the free tier does not return CUSIPs or ISINs).

## Running the Resolver

### Basic usage (backward compatible with v1)

```bash
# Comma-separated tickers
python isin_resolver_v2.py --tickers AAPL,MSFT,TSM,SPY

# From a file (one ticker per line)
python isin_resolver_v2.py --ticker-file tickers.txt

# From ric.csv (strips exchange suffixes)
python isin_resolver_v2.py --ric-csv ric.csv

# Output to CSV
python isin_resolver_v2.py --tickers AAPL,MSFT --output isins.csv
```

### Enriched input (new in v2)

Provide a CSV with `ticker`, `company_name`, and `denomination_currency` columns to enable ADR detection and currency validation:

```bash
python isin_resolver_v2.py --enriched-csv tickers_enriched.csv
```

Enriched CSV format:
```csv
ticker,company_name,denomination_currency
AAPL,Apple Inc.,USD
BIDU,Baidu Inc,USD
SAP,SAP SE,EUR
SPY,SPDR S&P 500 ETF,USD
```

When `denomination_currency` is `USD` and the resolved ISIN has a non-US prefix, the resolver:
1. Checks manual overrides for the correct US ADR ISIN
2. Queries OpenFIGI to confirm ADR status
3. Flags the result with a warning and downgrades confidence if no override exists

### Performance options

```bash
# Skip yfinance (faster, Tier 0 + Tier 1 only)
python isin_resolver_v2.py --tickers AAPL,MSFT --no-yfinance

# Skip OpenFIGI (no ADR detection confirmation)
python isin_resolver_v2.py --tickers AAPL,MSFT --no-openfigi

# Both (fastest — manual overrides + FinanceDatabase only)
python isin_resolver_v2.py --tickers AAPL,MSFT --no-yfinance --no-openfigi

# Force re-resolve (ignore cache)
python isin_resolver_v2.py --tickers AAPL --force-refresh

# Verbose logging
python isin_resolver_v2.py --tickers AAPL -v
```

## CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--tickers` | Comma-separated ticker list | - |
| `--ticker-file` | File with tickers (one per line or CSV) | - |
| `--ric-csv` | RIC CSV file (extracts tickers, strips suffix) | - |
| `--enriched-csv` | CSV with ticker, company_name, denomination_currency | - |
| `--output` | Output CSV path | Console only |
| `--no-yfinance` | Skip yfinance lookups | False |
| `--no-openfigi` | Skip OpenFIGI ADR detection | False |
| `--openfigi-api-key` | OpenFIGI API key (or set `OPENFIGI_API_KEY` env var) | None |
| `--force-refresh` | Ignore cache, re-resolve all | False |
| `--verbose`, `-v` | Enable verbose logging | False |

One of `--tickers`, `--ticker-file`, `--ric-csv`, or `--enriched-csv` is required.

## Output

### Console

Prints a resolution summary:
- Total/resolved/unresolved counts
- Breakdown by source (manual_override, financedatabase, yfinance, unresolved)
- ADR corrections applied
- Currency validation warnings
- ISIN country prefix breakdown

### CSV (`--output`)

| Column | Description |
|--------|-------------|
| `ticker` | Input ticker symbol |
| `isin` | Resolved ISIN (empty if unresolved) |
| `cusip` | CUSIP if available |
| `source` | Resolution source: `manual_override`, `financedatabase`, `yfinance`, `cusip_computed`, `unresolved` |
| `confidence` | `high` (Tier 0/1), `medium` (Tier 2), `low` (unresolved or flagged) |
| `company_name` | Company name from source |
| `exchange` | Exchange code from source |
| `warnings` | Semicolon-separated warnings |

## Manual Overrides

The override file at `.isin_overrides/isin_overrides.csv` provides authoritative ISINs that take priority over all other sources. This is Tier 0 — checked before cache or any API call.

### Format

```csv
ticker,isin,cusip,company_name
BIDU,US0567521085,056752108,Baidu Inc ADR
TCOM,US89677Q1076,89677Q107,Trip.com Group Ltd ADR
SE,US81141R1005,81141R100,Sea Limited ADR
SPXL,US25459W8626,25459W862,Direxion Daily S&P 500 Bull 3X Shares
SATS,US2787681061,278768106,EchoStar Corporation
```

### When to add overrides

- **ADR corrections**: Foreign ISIN assigned instead of US ADR ISIN (e.g., BIDU got KYG070341048 instead of US0567521085)
- **Wrong data in sources**: FinanceDatabase or yfinance returned an ISIN for a different security (e.g., SPXL got an Argentine ISIN)
- **Missing tickers**: Tickers not found in any automated source

### Current overrides (5 entries)

| Ticker | Issue | Corrected ISIN |
|--------|-------|----------------|
| BIDU | ADR: was KYG070341048 (Cayman) | US0567521085 |
| TCOM | ADR: was KYG9066F1019 (Cayman) | US89677Q1076 |
| SE | ADR: was CA87039X2086 (Canadian) | US81141R1005 |
| SPXL | Wrong data: was AR0748859532 (Argentina) | US25459W8626 |
| SATS | Wrong data: was NO0010863285 (Norway) | US2787681061 |

ISINs are validated against python-stdnum's check-digit algorithm on load. Invalid ISINs in the override file are silently rejected.

## ADR Detection

When enriched input includes `denomination_currency=USD` and a resolved ISIN has a non-US prefix:

1. **Manual override exists** → Replaces the foreign ISIN with the US ADR ISIN (confidence: high)
2. **No override, OpenFIGI confirms ADR** → Keeps foreign ISIN but adds warning: "ADR detected — add US ADR ISIN to manual overrides" (confidence: low)
3. **No override, OpenFIGI not available or not ADR** → Keeps foreign ISIN as-is

Note: Some non-US ISINs are correct for USD-denominated securities. For example:
- **CRDO** (KY prefix) — Cayman-incorporated, lists ordinary shares directly on NASDAQ
- **GRAB** (KY prefix) — Same as CRDO, not an ADR
- **AZN** (GB prefix), **SAP** (DE prefix) — Genuine foreign companies with US cross-listings

## Currency Validation

When `denomination_currency=USD`, the resolver flags ISINs with suspicious prefixes:

| Prefix | Expected? | Example |
|--------|-----------|---------|
| US | Yes | Domestic US securities |
| KY, CA, BM, JE, LU, GB, DE, IE, IL, NO, PL | Yes | Common for ADRs and cross-listings |
| IN (India), AR (Argentina), BR (Brazil), etc. | No — flagged | Likely wrong security |

Flagged results get `confidence: low` and a warning in the output.

## OpenFIGI API Key

Optional. The free tier works without a key but has lower rate limits:

| | Without key | With key |
|-|-------------|----------|
| Rate limit | 25 req/min | 250 req/min |
| Batch size | Up to 100 tickers/request | Up to 100 tickers/request |

To provide a key:
```bash
# Via CLI flag
python isin_resolver_v2.py --tickers AAPL --openfigi-api-key YOUR_KEY

# Via environment variable
export OPENFIGI_API_KEY=YOUR_KEY
python isin_resolver_v2.py --tickers AAPL
```

## Caching

Results are cached in `.isin_cache/isin_map_v2.json` with a 7-day TTL (separate from v1's `isin_map.json`).

- Cache is checked after Tier 0 (manual overrides always win)
- Invalid ISINs (bad check digits) are evicted from cache on read
- Use `--force-refresh` to clear and re-resolve all tickers

## Programmatic Usage

```python
from isin_resolver_v2 import ISINResolver, TickerInput

# Basic usage (backward compatible with v1)
resolver = ISINResolver(use_yfinance=True)
result = resolver.resolve("AAPL")
print(result.isin)        # US0378331005
print(result.source)      # financedatabase
print(result.confidence)  # high

# Enriched input for ADR detection
inp = TickerInput(ticker="BIDU", company_name="Baidu Inc", denomination_currency="USD")
result = resolver.resolve(inp)
print(result.isin)        # US0567521085 (from manual override)
print(result.source)      # manual_override

# Batch resolve
results = resolver.resolve_batch(["AAPL", "MSFT", "SPY"])

# Batch with enriched input
inputs = [
    TickerInput(ticker="AAPL", denomination_currency="USD"),
    TickerInput(ticker="BIDU", denomination_currency="USD"),
    TickerInput(ticker="SAP", denomination_currency="EUR"),
]
results = resolver.resolve_batch(inputs)

# Save cache when done
resolver.save_cache()
```

### Constructor options

```python
resolver = ISINResolver(
    use_yfinance=True,           # Enable Tier 2 (yfinance)
    use_openfigi=True,           # Enable OpenFIGI ADR detection
    openfigi_api_key="...",      # Optional API key
    cache_dir=Path(".isin_cache"),
    cache_ttl=7 * 24 * 3600,    # 7 days
    override_file=Path(".isin_overrides/isin_overrides.csv"),
)
```

## Running Tests

```bash
# v2 tests only (97 tests)
pytest tests/test_isin_resolver_v2.py -v

# Both v1 and v2 (164 tests total)
pytest tests/test_isin_resolver.py tests/test_isin_resolver_v2.py -v
```
