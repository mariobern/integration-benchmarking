# Phase 2: Datascope DSS REST API Integration Plan

**Status**: BLOCKED — waiting for DSS API credentials
**Created**: 2026-02-08
**Context**: ISIN Resolver Phase 1 achieved 86.4% coverage (612/708 tickers). Phase 2 adds the DSS REST API to resolve the remaining 96 tickers and enable authoritative ISIN-to-RIC conversion.

---

## Prerequisites

- [ ] Confirm Datascope DSS REST API credentials (username/password)
- [ ] Add credentials to `config.yaml` under `datascope_dss` section

---

## What We're Building

### 1. `datascope_dss_client.py` (new file, ~450 lines)

Standalone DSS REST API client with:

- **Authentication**: POST to `https://selectapi.datascope.lseg.com/RestApi/v1/Authentication/RequestToken`
  - Token caching on disk (`.dss_cache/token.json`) with 23h TTL (1h safety margin vs 24h actual)
  - Rate limit awareness: 30 auth requests per 300 seconds
- **T&C Extraction**: POST to `/Extractions/ExtractWithNotes`
  - Bidirectional: ISIN→RIC and RIC→ISIN via `IdentifierType` parameter
  - Batch support (multiple identifiers per request, max 5000)
  - Async polling for 202 responses (Location header, 5s interval, 300s max)
- **Convenience methods**:
  - `isin_to_ric(isins)` — convert ISINs to primary RICs
  - `ric_to_isin(rics)` — convert RICs to ISINs
  - `ticker_to_isin(tickers)` — resolve tickers by trying RIC suffixes (.O, .N, .P, .Z, .A)
  - `validate_instruments(identifiers)` — validate via DSS validation endpoint
- **Standalone CLI** with subcommands: `isin-to-ric`, `ric-to-isin`, `ticker-to-isin`

**Data classes** (frozen dataclasses):

```python
@dataclass(frozen=True)
class DSSExtractionResult:
    identifier: str
    identifier_type: str  # "Isin" or "Ric"
    ric: Optional[str]
    isin: Optional[str]
    cusip: Optional[str]
    sedol: Optional[str]
    currency_code: Optional[str]
    exchange_code: Optional[str]
    company_name: Optional[str]
    error: Optional[str]

@dataclass(frozen=True)
class DSSValidationResult:
    identifier: str
    identifier_type: str
    status: str
    source: Optional[str]  # e.g., "NYS", "NAS"
    ric: Optional[str]
    description: Optional[str]

@dataclass(frozen=True)
class DSSTokenInfo:
    token: str
    obtained_at: float
    expires_at: float
```

### 2. `DatascopeDSSSource` class (in `isin_resolver.py`, ~50 lines)

Adapter class integrating DSS client into the ISINResolver tier pattern:

- `resolve(ticker)` and `resolve_batch(tickers)` methods
- Converts `DSSExtractionResult` → `ISINResult` with `source="datascope_dss"`, `confidence="high"`
- Catches `DSSAuthError`/`DSSAPIError` and returns empty results (graceful degradation)

### 3. ISINResolver modifications (~30 lines)

- New constructor params: `use_dss`, `dss_username`, `dss_password`
- Tier 3 logic in `resolve()` and `resolve_batch()` — after yfinance, before unresolved
- New CLI flags: `--no-dss`, `--dss-only`
- `close()` method for HTTP client cleanup

### 4. Config changes (`config.yaml.sample`)

```yaml
# Datascope DSS REST API credentials (optional)
# Needed for ISIN resolver Tier 3 (DSS) and ISIN-to-RIC conversion
datascope_dss:
  username: # fill in (Datascope DSS login email)
  password: # fill in
```

---

## DSS API Reference

### Authentication

```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Authentication/RequestToken
Body: {"Credentials": {"Username": "...", "Password": "..."}}
→ 200: {"value": "token-string"}
→ 401: Invalid credentials
Token valid 24 hours. Rate limit: 30 requests per 300 seconds.
```

### T&C Extraction (core endpoint)

```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Extractions/ExtractWithNotes
Headers: Authorization: Token {token}, Content-Type: application/json, Prefer: respond-async
```

**Request** (ISIN→RIC direction):

```json
{
  "ExtractionRequest": {
    "@odata.type": "#DataScope.Select.Api.Extractions.ExtractionRequests.TermsAndConditionsExtractionRequest",
    "ContentFieldNames": [
      "RIC",
      "ISIN",
      "CUSIP",
      "SEDOL",
      "Currency Code",
      "Exchange Code",
      "Company Name"
    ],
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

**Response** (200 or 202+polling):

```json
{
  "Contents": [
    {
      "RIC": "AAPL.O",
      "ISIN": "US0378331005",
      "CUSIP": "037833100",
      "Currency Code": "USD",
      "Exchange Code": "NAS",
      "Company Name": "APPLE INC"
    },
    {
      "RIC": "IBM.N",
      "ISIN": "US4592001014",
      "CUSIP": "459200101",
      "Currency Code": "USD",
      "Exchange Code": "NYS",
      "Company Name": "INTERNATIONAL BUSINESS MACHINES"
    }
  ]
}
```

### Instrument Validation

```
POST https://selectapi.datascope.lseg.com/RestApi/v1/Extractions/InstrumentListValidateIdentifiersWithOptions
```

### LSEG Documentation References

- [ISIN to RIC Conversion](https://developers.lseg.com/en/article-catalog/article/isin-to-ric-conversion-with-dss-datascope-select-rest-api)
- [Symbology Conversion Python](https://developers.lseg.com/en/article-catalog/article/symbology-conversion-using-the-dss-rest-api-in-python)
- [Python RIC Mapping (GitHub)](https://github.com/LSEG-API-Samples/Article.DSS.Python.REST.RicMapping)

---

## Implementation Order

1. Config + data classes (foundation)
2. Auth + token cache (core infrastructure)
3. Write auth tests (TDD)
4. T&C extraction + polling logic
5. Write extraction tests (TDD)
6. Convenience methods (isin_to_ric, ric_to_isin, ticker_to_isin)
7. Standalone CLI
8. DatascopeDSSSource adapter in isin_resolver.py
9. ISINResolver tier integration + CLI flags
10. Integration tests in test_isin_resolver.py
11. Documentation updates (CLAUDE.md, docstrings)

---

## Test Plan

### New tests (~35-40 total)

**`tests/test_datascope_dss_client.py`** (~25 tests):

- `TestDSSTokenCache`: put/get, TTL expiration, clear, missing file, corrupted file
- `TestDatascopeDSSClientAuth`: success, invalid creds (401), cached token reuse, expired refresh, server error, missing value field
- `TestDatascopeDSSClientExtraction`: isin_to_ric single/batch, ric_to_isin single/batch, 202 polling, polling timeout, API errors, empty input, ticker_to_isin found/not-found
- `TestDatascopeDSSClientValidation`: success, invalid instrument, empty list
- `TestBatchChunking`: >5000 identifiers split into chunks

**`tests/test_isin_resolver.py`** (~12 new tests):

- `TestDatascopeDSSSource`: resolve found/not-found, batch, auth/API error handling
- `TestISINResolverWithDSS`: tier 3 integration, tier ordering, caching, graceful degradation, batch with all 3 tiers

### Mocking strategy

- Mock `httpx.Client` at class level using `@patch("datascope_dss_client.httpx.Client")`
- Provide realistic JSON responses from docs/isin_research.md examples
- Test both sync (200) and async (202+polling) paths

---

## The 96 Unresolved Tickers

These tickers from `missing_ric_tickers.txt` couldn't be resolved by Tier 1 (FinanceDatabase) or Tier 2 (yfinance):

**By category**:

- **ETFs** (largest group): ARKF, ARKQ, ARKW, ARKX, BSV, CALF, COWZ, DFAC, DGRO, EFG, EFV, EMB, EWJ, EWY, EWZ, FLOT, GDX, GDXJ, GOVT, GOVZ, GVI, HYD, IAGG, IDV, IEFA, IEO, IFRA, IGE, IGV, IJH, IJR, INDA, ITB, IYR, IYT, IYW, IYZ, KWEB, MOAT, MTUM, NOBL, OMFL, PAVE, QUAL, REM, SGOV, SIVR, SLV, SPLG, URTH, USMV, VEA, VGK, VGT, VLUE, VNM, VO, VUG, VTEB, VUSB, XLB, XLC, XLI, XLP, XLU, XLY, XOP
- **Crypto ETFs/products**: BITX, BTCI, BTCL, ETHA, ETHU, ETHV, YBTC, YETH, DEFI, QETH, TETH
- **Leveraged/Inverse**: SOXL, SOXS, SPXL, TNA, UVIX, UVXY, VIXY, SVIX, SVXY
- **Well-known equities**: AFRM, AZN, BIDU, BRK.A, BRK.B, CELH, CRDO, DUOL, EXPD, FERG, FUTU, GRAB, IONQ, K, LYFT, NET, ROKU, SAP, SE, SFM, SNOW, SOFI, SOUN, SPOT, TCOM, VRT, WBA, WIX
- **Thematic/specialty**: BBAX, BBCA, BBEU, BBJP, BBUS, BOXX, BUFR, DIHP, EEMV, EFAV, etc.

**Expected DSS resolution**: High — DSS is the authoritative source for all Datascope-listed instruments. Most of these should resolve (80%+ of the 96).

---

## Error Handling Summary

| Scenario                                    | Behavior                                                |
| ------------------------------------------- | ------------------------------------------------------- |
| No DSS credentials configured               | Tier 3 silently disabled, log info message              |
| Invalid credentials (401)                   | Log error, return empty results, continue with Tier 1/2 |
| API error (400/500)                         | Log error, return empty results, continue               |
| 202 polling timeout (>300s)                 | Log error, return empty results                         |
| Network error (connection refused, timeout) | Log error, return empty results                         |
| DSS returns invalid ISIN                    | Validation warning, ISIN not used                       |
| Partial results (some tickers not found)    | Unfound tickers remain unresolved                       |

---

## Files to Create/Modify

| File                                 | Action  | Est. Lines |
| ------------------------------------ | ------- | ---------- |
| `datascope_dss_client.py`            | **New** | ~450       |
| `tests/test_datascope_dss_client.py` | **New** | ~400       |
| `isin_resolver.py`                   | Modify  | ~80        |
| `tests/test_isin_resolver.py`        | Modify  | ~120       |
| `config.yaml.sample`                 | Modify  | ~5         |
| `CLAUDE.md`                          | Modify  | ~30        |

---

## To Resume

When credentials are available:

1. Add credentials to `config.yaml` under `datascope_dss` section
2. Tell Claude: "Continue with Phase 2 DSS integration — see `tasks/phase2_dss_integration_plan.md`"
3. Implementation starts at Step 1 above
