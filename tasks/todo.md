# ISIN Resolver Implementation

## Phase 1: Core ISIN Resolution (DONE)

- [x] Explore existing codebase patterns (generate_source_upload.py, ric.csv)
- [x] Create `isin_resolver.py` with tiered resolution strategy
  - [x] Tier 1: FinanceDatabase (158K+ equities, instant, local)
  - [x] Tier 2: yfinance (per-ticker, ~1-2s each, network)
  - [x] CUSIP→ISIN computation via python-stdnum
  - [x] JSON file cache with 7-day TTL
  - [x] CLI with --tickers, --ticker-file, --ric-csv inputs
- [x] Update requirements.txt (financedatabase, python-stdnum, yfinance)
- [x] Write tests (49 tests, all passing)
- [x] Address code review findings (H1-H4, M2, M3, M6, M7)
- [x] Verify against ric.csv (708 unique tickers)

## Verification Results

- **86.4% coverage** (612/708 tickers resolved)
- Tier 1 (FinanceDatabase): 391 tickers (55.2%)
- Tier 2 (yfinance): 221 tickers (31.2%)
- Unresolved: 96 tickers (13.6%) — mostly well-known stocks where yfinance returns "-"
- ISIN country breakdown: US (541), CA (15), IE (10), KY (8), AU (7), BM (6), ...

## Phase 2: Datascope DSS Integration (BLOCKED — waiting for credentials)

**Full plan**: `tasks/phase2_dss_integration_plan.md`

- [ ] Confirm DSS API credentials are available
- [ ] Add `datascope_dss_client.py` with authentication + token caching
- [ ] T&C extraction: bidirectional ISIN↔RIC batch conversion
- [ ] `DatascopeDSSSource` adapter class + Tier 3 integration in ISINResolver
- [ ] CLI: `--no-dss`, `--dss-only` flags + standalone DSS client CLI
- [ ] Tests: ~35-40 new tests (mock HTTP, no credentials needed)
- [ ] Resolve remaining 96 tickers (target: 80%+ resolution)
- [ ] Documentation updates (CLAUDE.md, docstrings)

## Phase 3: Non-Equity Instruments (Future)

- [ ] FX/Metals: Direct RIC mapping (no ISIN needed)
- [ ] Futures: Per-contract ISIN lookup
- [ ] Treasuries: CUSIP-based ISINs
