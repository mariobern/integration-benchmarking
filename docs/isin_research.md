# ISIN Research & Programmatic Generation Strategy

## Context

**Problem**: The current `generate_source_upload.py` uses a 3-tier RIC resolution strategy (Datascope ClickHouse → NASDAQ Trader → default `.N`) that has a ~16% discrepancy rate between NASDAQ Trader exchange suffixes and Datascope's actual RICs. ISINs can solve this by providing a **universal, unambiguous identifier** that Datascope can use to return the exact primary RIC for any security.

**Scope**: US equities, ETFs, ADRs, futures, FX, rates/treasuries, and commodities — as represented in `ric.csv` (752 RICs across 8 exchange suffixes: `.N`, `.O`, `.Z`, `.P`, `.K`, `.A`, `.PK`, `.TO`).

**Goal**: Build a standalone ISIN utility that maps ISINs to RICs, enabling us to identify the primary exchange for every Pyth-listed security.

---

## Part 1: What is an ISIN?

An **International Securities Identification Number (ISIN)** is a 12-character alphanumeric code defined by [ISO 6166](https://www.iso.org/news/ref2616.html) that uniquely identifies a financial security globally.

### Structure: `[CC][NSIN][C]`

| Component | Length | Description | Example (Apple) |
|-----------|--------|-------------|-----------------|
| Country Code | 2 chars | ISO 3166-1 alpha-2 | `US` |
| NSIN | 9 chars | National Securities ID (= CUSIP for US) | `037833100` |
| Check Digit | 1 digit | Luhn algorithm | `5` |
| **Full ISIN** | **12 chars** | | **`US0378331005`** |

### Key Properties

- **Globally unique**: One ISIN per security, regardless of exchange
- **Exchange-independent**: `TSM.N` and `TSM.Z` share the same ISIN (`US8740391003`)
- **Deterministic for US**: If you have CUSIP → ISIN is computed algorithmically (no API needed)
- **Datascope native**: DSS REST API accepts ISINs and returns the primary RIC

### Luhn Check Digit Algorithm

```python
# From python-stdnum (LGPL, pip install python-stdnum)
from stdnum.cusip import to_isin
to_isin('037833100')   # → 'US0378331005' (Apple)
to_isin('594918104')   # → 'US5949181045' (Microsoft)

# Or manually:
from stdnum.isin import from_natid
from_natid('US', '037833100')  # → 'US0378331005'
```

The algorithm: convert letters to numbers (A=10..Z=35), double alternating digits from right, sum all digits, check digit = `(10 - sum % 10) % 10`.

---

## Part 2: ISIN Applicability by Instrument Type

Analysis of `ric.csv` (752 RICs) and Pyth's broader asset coverage:

| Instrument Type | Has ISIN? | ISIN Source | Examples from ric.csv |
|----------------|-----------|-------------|----------------------|
| **US Equities** | Yes | US + CUSIP + check | `AAPL.O`, `MSFT.O`, `IBM.N` |
| **US ETFs** | Yes | US + CUSIP + check | `SPY.N`, `QQQ.O`, `IWM.N`, `GLD.N` |
| **ADRs** | Yes | US + CUSIP + check | `BABA.Z`, `TSM.N`, `NVO.N`, `SONY.N` |
| **Crypto ETFs** | Yes | US + CUSIP + check | `IBIT.N`, `GBTC.N`, `FBTC.N` |
| **US Treasuries** | Yes | US + CUSIP + check | (in benchmark data, not ric.csv) |
| **Futures** | Yes | Allocated per contract by ANNA DSB | `EMH6`, `NMH6` (not in ric.csv) |
| **FX Spot** | Partial | XC prefix (supranational) | EUR/USD → `XC` + code; complex |
| **Commodity Spot** | Partial | XC prefix | Gold: `XC0009655157` |
| **OTC/Pink Sheet** | Rare | Varies | `GLCNF.PK`, `GMBXF.PK` |
| **Canadian** | Yes | CA + CUSIP + check | `GLXY.TO` |

**Bottom line**: ISINs cover ~95% of `ric.csv` instruments (equities, ETFs, ADRs). FX pairs and commodity spot are edge cases with non-standard ISIN treatment.

### RIC Symbology by Instrument Type (from Refinitiv RIC Symbology Card)

The official LSEG/Refinitiv RIC Symbology Card (`20240205WorkspaceWAinstrumentCode.pdf`) confirms the naming conventions:

| Instrument | RIC Pattern | ISIN-Addressable? | Notes |
|------------|------------|-------------------|-------|
| US Equities | `AAPL.O`, `IBM.N` | **Yes** | Exchange suffix varies by listing exchange |
| US ETFs | `SPY.P`, `QQQ.O` | **Yes** | Same as equities; ETF valuations use `nv`, `iv` suffixes |
| ADRs | `BABA.Z`, `TSM.N` | **Yes** | US-listed → US CUSIP/ISIN |
| FX Spot | `EUR=`, `GBPJPY=` | **No** | Uses `=` suffix, no ISIN exists |
| Metal Spot | `XAU=`, `XAG=` | **No** | Uses `=` suffix, gold ISIN `XC0009655157` exists but not used in RIC |
| Index Futures | `ESc1`, `NQc1` | **Partial** | ISIN per contract but RIC uses continuation codes |
| Commodity Futures | `GCc1`, `CLc1` | **Partial** | Same as index futures |
| US Treasuries | `US10YT=RRPS` | **No** | Specialized RIC format with yield provider suffix |
| Indexes | `.SPX`, `.DJI` | **No** | Dot-prefixed, no ISIN |

**Key exchange suffixes** (definitive list from Symbology Card):

| Suffix | Exchange | Example |
|--------|----------|---------|
| `.N` | NYSE | `IBM.N` |
| `.O` | NASDAQ (consolidated) | `MSFT.O` |
| `.OQ` | NASDAQ (specific) | `MSFT.OQ` |
| `.P` | NYSE Arca | `SPY.P` |
| `.Z` | Cboe BZX | `BABA.Z` |
| `.A` | NYSE American | `MSFT.A` |
| `.K` | US Consolidated (4+ char root) | `TWTR.K` |
| `.PK` | OTC/Pink Sheets | `NSRGY.PK` |
| `.B` | NASDAQ BX | `BABA.B` |

**Implication**: ISIN-based resolution will work for equities/ETFs/ADRs (the bulk of our instruments). FX, metals spot, treasuries, and indexes need a different resolution approach (direct RIC mapping, not ISIN-based).

---

## Part 3: Datascope ISIN-to-RIC API

The LSEG Datascope Select (DSS) REST API provides authoritative ISIN-to-RIC conversion.

### Authentication
```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Authentication/RequestToken
Body: {"Credentials": {"Username": "...", "Password": "..."}}
Returns Bearer token for all subsequent requests
```

### ISIN to Primary RIC
```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Extractions/ExtractWithNotes
```

**Request**:
```json
{
  "ExtractionRequest": {
    "@odata.type": "#DataScope.Select.Api.Extractions.ExtractionRequests.TermsAndConditionsExtractionRequest",
    "ContentFieldNames": ["RIC", "ISIN", "CUSIP", "SEDOL", "Currency Code", "Exchange Code", "Company Name"],
    "IdentifierList": {
      "@odata.type": "#DataScope.Select.Api.Extractions.ExtractionRequests.InstrumentIdentifierList",
      "InstrumentIdentifiers": [
        { "Identifier": "US0378331005", "IdentifierType": "Isin" },
        { "Identifier": "US4592001014", "IdentifierType": "Isin" }
      ]
    }
  }
}
```

**Response**:
```json
{
  "Contents": [
    {
      "RIC": "AAPL.O", "ISIN": "US0378331005", "CUSIP": "037833100",
      "Currency Code": "USD", "Exchange Code": "NAS", "Company Name": "APPLE INC"
    },
    {
      "RIC": "IBM.N", "ISIN": "US4592001014", "CUSIP": "459200101",
      "Currency Code": "USD", "Exchange Code": "NYS", "Company Name": "INTERNATIONAL BUSINESS MACHINES"
    }
  ]
}
```

**Key capabilities**:
- Batch: multiple ISINs per request
- Bidirectional: also RIC-to-ISIN via same API
- Returns primary RIC (the exact one Datascope uses for benchmarking)
- Handles delisted instruments with `AllowHistoricalInstruments: true`

### Instrument Validation Endpoint

Alternatively, use validation to find the primary exchange for an ISIN:

```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Extractions/InstrumentListValidateIdentifiersWithOptions
```

```json
{
  "InputsForValidation": [
    { "Identifier": "US4592001014", "IdentifierType": "Isin" }
  ],
  "Options": {
    "AllowHistoricalInstruments": true,
    "AllowInactiveInstruments": true
  }
}
```

Response includes `Source` field (e.g., `"NYS"`) indicating the primary exchange.

### Equity Search (Multi-Exchange)

Find all exchanges where an ISIN trades:

```json
{
  "SearchRequest": {
    "AssetStatus": "Active",
    "CurrencyCodes": ["USD"],
    "ExchangeCodes": ["NAS", "NYS", "SWX"],
    "Identifier": "US4592001014",
    "IdentifierType": "Isin",
    "PreferredIdentifierType": "Ric"
  }
}
```

**References**:
- [ISIN to RIC Conversion](https://developers.lseg.com/en/article-catalog/article/isin-to-ric-conversion-with-dss-datascope-select-rest-api)
- [Symbology Conversion](https://developers.lseg.com/en/article-catalog/article/symbology--isin-cusip-sedol--conversion-to-ric-using-datascope)
- [Symbology Conversion Python](https://developers.lseg.com/en/article-catalog/article/symbology-conversion-using-the-dss-rest-api-in-python)
- [Python RIC Mapping (GitHub)](https://github.com/LSEG-API-Samples/Article.DSS.Python.REST.RicMapping)
- [Convert Symbology (GitHub)](https://github.com/LSEG-API-Samples/Article.DSS.Python.ConvertSymbology)
- [LSEG Community: ISIN+Exchange to RIC](https://community.developers.lseg.com/discussion/120133/retrieve-ric-codes-from-isin-and-exchange-in-instrument-search)

---

## Part 4: ISIN Data Sources (Ranked)

### Source 1: FinanceDatabase (Best for Bulk)

Open-source database with **158,429 equities** across 111 countries, including ISIN, CUSIP, and FIGI fields.

```python
pip install financedatabase
import financedatabase as fd

equities = fd.Equities()
us = equities.select(country="United States")
# DataFrame with columns: symbol, isin, cusip, figi, composite_figi, shareclass_figi, name, ...
```

| Metric | Value |
|--------|-------|
| Coverage | 158K+ equities, global |
| Fields | ISIN, CUSIP, FIGI, composite_figi, shareclass_figi |
| Cost | Free (MIT license) |
| Speed | Instant (local DataFrame) |
| Update frequency | Community-maintained |

**Limitations**: May have gaps for newer/smaller securities; ETF coverage unclear.

**References**: [GitHub](https://github.com/JerBouma/FinanceDatabase) | [PyPI](https://pypi.org/project/financedatabase/)

### Source 2: yfinance (Per-Ticker Fallback)

```python
pip install yfinance
import yfinance as yf

ticker = yf.Ticker("AAPL")
isin = ticker.isin  # "US0378331005" (experimental)
```

| Metric | Value |
|--------|-------|
| Coverage | Broad (anything on Yahoo Finance) |
| Cost | Free |
| Speed | ~1-2s per ticker (HTTP request) |
| Reliability | Marked "experimental" |

**References**: [yfinance docs](https://ranaroussi.github.io/yfinance/reference/yfinance.ticker_tickers.html) | [PyPI](https://pypi.org/project/yfinance/)

### Source 3: python-stdnum (CUSIP to ISIN Computation)

If you have the CUSIP, compute the ISIN deterministically with zero API calls.

```python
pip install python-stdnum
from stdnum.cusip import to_isin
from stdnum.isin import validate, from_natid

to_isin('037833100')              # 'US0378331005'
validate('US0378331005')          # 'US0378331005' (valid)
from_natid('CA', '135087311')     # 'CA1350873119' (Canadian)
```

| Metric | Value |
|--------|-------|
| Coverage | Any security with a known CUSIP |
| Cost | Free (LGPL) |
| Speed | Instant (pure computation) |
| Requirement | Must already have the CUSIP |

**References**: [GitHub](https://github.com/arthurdejong/python-stdnum) | [PyPI](https://pypi.org/project/python-stdnum/)

### Source 4: OpenFIGI API (Free, But No ISIN Output)

Maps tickers to FIGI identifiers. **Does NOT return ISINs** due to licensing restrictions, but returns ticker, name, exchange, security type.

```python
import requests
jobs = [{"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"}]
r = requests.post("https://api.openfigi.com/v3/mapping", json=jobs)
# Returns: figi, compositeFIGI, shareClassFIGI, name, ticker, exchCode
```

| Metric | Value |
|--------|-------|
| Rate limits | 25/min (unauth), 25/6s (API key), 100 jobs/request |
| ISIN in response? | **No** (can use ISIN as input via `ID_ISIN`) |
| Cost | Free |

**Use case**: Supplementary metadata (security type, exchange) but NOT for ISIN resolution.

**References**: [API Docs](https://www.openfigi.com/api/documentation) | [GitHub Examples](https://github.com/OpenFIGI/api-examples)

### Source 5: Datascope DSS REST API (Authoritative, Bidirectional)

Use Datascope credentials for RIC-to-ISIN and ISIN-to-RIC conversion. See Part 3 above.

| Metric | Value |
|--------|-------|
| Coverage | Everything Datascope has |
| Cost | Existing license (need DSS API access) |
| Speed | ~1-2s per batch |
| Authoritative? | **Yes** - this is the benchmark source |

### Source 6: FMP ISIN API (Paid, Simple)

```
GET https://financialmodelingprep.com/stable/search-isin?isin=US0378331005&apikey=KEY
```

| Metric | Value |
|--------|-------|
| Free tier | ~250 calls/day |
| Coverage | Global |

**References**: [FMP ISIN API](https://site.financialmodelingprep.com/developer/docs/stable/search-isin)

### Source 7: EODHD ID Mapping API

```
GET https://eodhd.com/api/query?api_token=KEY&filter[symbol]=AAPL&fmt=json
```

| Metric | Value |
|--------|-------|
| Free tier | 20 calls/day (too low for bulk) |
| Fields | ISIN, CUSIP, FIGI, LEI, CIK |

**References**: [EODHD ID Mapping](https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol)

### Source 8: SEC 13F Securities List (Free, CUSIP-Based)

The SEC publishes quarterly 13F lists with CUSIPs. Starting Q4 2025, available in `.txt` format (previously PDF-only).

| Metric | Value |
|--------|-------|
| Coverage | ~9,000 institutional securities |
| Cost | Free |
| Format | PDF (historical), .txt (Q4 2025+) |
| URL | [SEC 13F Data](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets) |

### Source 9: ANNA Free ISIN Lookup

ANNA (Association of National Numbering Agencies) offers a free international ISIN lookup service matching against the global ISIN database. Requires registration.

**References**: [ANNA ISIN Lookup](https://anna-web.org/anna-launches-free-international-isin-lookup-service/)

---

## Part 5: Recommended Approach - Tiered ISIN Resolution

Build a standalone `isin_resolver.py` utility with this tiered strategy:

```
Input: Ticker (e.g., AAPL, TSM, BRK.B, SPY)
                |
                v
  +------------------------------+
  |  Tier 1: FinanceDatabase     |  Bulk lookup from 158K equity DB
  |  (local, instant, free)      |  Get ISIN + CUSIP for all at once
  +--------------+---------------+
                 | Found? -> Cache & continue
                 | Not found?
                 v
  +------------------------------+
  |  Tier 2: yfinance            |  Per-ticker Yahoo Finance lookup
  |  (API, ~1s each, free)       |  ticker.isin property
  +--------------+---------------+
                 | Found? -> Cache & continue
                 | Not found?
                 v
  +------------------------------+
  |  Tier 3: Datascope DSS API   |  RIC->ISIN via T&C extraction
  |  (authoritative, batched)    |  (once we have DSS API access)
  +--------------+---------------+
                 | Found? -> Cache & continue
                 | Not found? -> Flag for manual review
                 v
  +------------------------------+
  |  Output: ISIN Cache File     |  JSON/CSV mapping:
  |  (.isin_cache/)              |  ticker -> ISIN -> RIC -> exchange
  +------------------------------+
```

### Then: ISIN to Primary RIC Resolution

Once we have ISINs, the final step uses Datascope to resolve to the exact primary RIC:

```
ISIN (US0378331005) -> Datascope DSS API -> RIC (AAPL.O) + Exchange (NAS) + Currency (USD)
```

This eliminates the 16% exchange suffix mismatch entirely.

---

## Part 6: Coverage Gaps & Edge Cases

| Instrument | ISIN Strategy | Notes |
|------------|---------------|-------|
| US Equities | `US` + CUSIP + check | Standard, well-supported |
| US ETFs | `US` + CUSIP + check | Same as equities |
| ADRs (US-listed) | `US` + CUSIP + check | ADRs get US CUSIPs |
| Canadian equities | `CA` + CUSIP + check | `GLXY.TO` -> Canadian ISIN |
| OTC/Pink Sheets | May not have CUSIP | `GLCNF.PK` - needs manual check |
| Futures contracts | New ISIN per contract/expiry | Complex; ANNA DSB allocates |
| FX spot (EUR/USD) | `XC` prefix (supranational) | Gold spot: `XC0009655157` |
| Commodities spot | `XC` prefix | Not all have ISINs |
| US Treasuries | `US` + CUSIP + check | Standard |

**Practical recommendation**: Start with equities/ETFs/ADRs (covers ~95% of ric.csv), then add futures/FX/treasuries support incrementally.

---

## Summary of All Sources

| Source | Coverage | ISIN? | CUSIP? | Cost | Bulk? | Speed |
|--------|----------|-------|--------|------|-------|-------|
| [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) | 158K equities | Yes | Yes | Free | Yes | Instant |
| [yfinance](https://pypi.org/project/yfinance/) | Broad | Yes | No | Free | Slow | 1-2s/ticker |
| [python-stdnum](https://github.com/arthurdejong/python-stdnum) | Needs CUSIP | Computes | Input | Free | Yes | Instant |
| [OpenFIGI](https://www.openfigi.com/api) | Broad | **No** | **No** | Free | Yes | Fast |
| [Datascope DSS](https://developers.lseg.com/en/api-catalog/datascope-select/datascope-select-rest-api) | Authoritative | Yes | Yes | License | Batched | 1-2s |
| [FMP](https://site.financialmodelingprep.com/developer/docs/stable/search-isin) | Global | Yes | Yes | Freemium | Limited | Fast |
| [EODHD](https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol) | Global | Yes | Yes | 20/day free | No | Fast |
| [SEC 13F](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets) | ~9K securities | Via CUSIP | Yes | Free | Quarterly | N/A |
| [ANNA Lookup](https://anna-web.org/anna-launches-free-international-isin-lookup-service/) | Global | Yes | No | Free (reg) | Manual | Manual |

---

## Part 7: Implementation Plan - `isin_resolver.py`

### Phase 1: Core ISIN Resolution (Equities/ETFs/ADRs)

**File**: `isin_resolver.py` (new standalone utility)

**Dependencies** (add to `requirements.txt`):
```
financedatabase
python-stdnum
yfinance
```

**Module structure**:
```python
class ISINResolver:
    """Tiered ISIN resolution for US equities, ETFs, and ADRs."""

    def resolve(ticker: str) -> ISINResult:
        """Resolve ticker -> ISIN using tiered strategy."""

    def resolve_batch(tickers: list[str]) -> dict[str, ISINResult]:
        """Bulk resolve tickers -> ISINs."""

    def isin_to_ric(isin: str) -> RICResult:
        """Convert ISIN -> primary RIC via Datascope DSS API."""
        # (Phase 2 - when DSS API access obtained)
```

**Data class**:
```python
@dataclass
class ISINResult:
    ticker: str
    isin: Optional[str]
    cusip: Optional[str]
    source: str  # "financedatabase", "yfinance", "datascope", "manual"
    company_name: Optional[str]
    exchange: Optional[str]
    warnings: list[str]
```

**Cache**: JSON file at `.isin_cache/isin_map.json` with TTL (similar to `.nasdaq_cache/`)

### Phase 2: Datascope DSS Integration (When Access Available)

- Add `datascope_dss_client.py` with authentication + ISIN-to-RIC batch conversion
- Integrate as Tier 0 (most authoritative) in ISINResolver
- Use `TermsAndConditionsExtractionRequest` with `ContentFieldNames: ["RIC", "ISIN", "CUSIP", "Exchange Code", "Company Name"]`

### Phase 3: Non-Equity Instruments

- FX/Metals: Direct RIC mapping (no ISIN needed - use the Symbology Card conventions)
- Futures: Per-contract ISIN lookup via ANNA DSB or FinanceDatabase
- Treasuries: CUSIP-based ISINs (standard US format)

### Verification

1. Run against all 752 RICs in `ric.csv` - measure ISIN resolution rate
2. Cross-reference ISINs against Datascope ClickHouse benchmark data
3. Compare resolved RICs to existing `ric.csv` - flag any mismatches
4. Validate check digits using `python-stdnum` for every resolved ISIN
