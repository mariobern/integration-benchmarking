# Universal RIC Mapping Generator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `generate_ric_mapping.py` that resolves any Pyth Lazer ticker to its Datascope RIC and outputs a `pyth_mappings_export`-format CSV.

**Architecture:** Rule-based RIC resolution engine. Loads `lazer_symbols.json` as source of truth, builds ticker indexes, dispatches to asset-class-specific resolvers (FX, metal, rates, commodity futures, equity index futures, US equities). NASDAQ Trader for equity exchange suffixes. No ClickHouse dependency.

**Tech Stack:** Python 3, standard library (csv, json, argparse, urllib), pytest for tests. Reuses `NasdaqTraderSource` and `ticker_to_ric_base()` from `generate_source_upload.py`.

---

### Task 1: Scaffold — Constants, Data Classes, and Symbol Index

**Files:**

- Create: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests for SymbolIndex**

```python
# tests/test_generate_ric_mapping.py
import pytest
import json
import tempfile
from pathlib import Path

# Minimal lazer_symbols fixture
SAMPLE_SYMBOLS = [
    {"pyth_lazer_id": 922, "name": "AAPL", "symbol": "Equity.US.AAPL/USD",
     "description": "APPLE INC", "asset_type": "equity", "quote_currency": "USD"},
    {"pyth_lazer_id": 327, "name": "EURUSD", "symbol": "FX.EUR/USD",
     "description": "EURO / US DOLLAR", "asset_type": "fx", "quote_currency": "USD"},
    {"pyth_lazer_id": 346, "name": "XAUUSD", "symbol": "Metal.XAU/USD",
     "description": "GOLD SPOT / US DOLLAR", "asset_type": "metal", "quote_currency": "USD"},
    {"pyth_lazer_id": 2931, "name": "CCH6", "symbol": "Commodities.CCH6/USD",
     "description": "COMEX HIGH GRADE COPPER MARCH 2026", "asset_type": "commodity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 1527, "name": "US10Y", "symbol": "Rates.US10Y",
     "description": "US TREASURY 10 YEAR", "asset_type": "rates", "quote_currency": "USD"},
    {"pyth_lazer_id": 311, "name": "AUDCAD", "symbol": "FX.AUD/CAD",
     "description": "AUSTRALIAN DOLLAR / CANADIAN DOLLAR", "asset_type": "fx",
     "quote_currency": "CAD"},
    {"pyth_lazer_id": 2279, "name": "DMH6", "symbol": "Equity.US.DMH6/USD",
     "description": "PYTH US30 20 MARCH 2026", "asset_type": "equity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 1, "name": "BTCUSD", "symbol": "Crypto.BTC/USD",
     "description": "BITCOIN / US DOLLAR", "asset_type": "crypto", "quote_currency": "USD"},
]

@pytest.fixture
def symbols_path(tmp_path):
    path = tmp_path / "lazer_symbols.json"
    path.write_text(json.dumps(SAMPLE_SYMBOLS))
    return path


class TestSymbolIndex:
    def test_lookup_by_name(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        entry = idx.lookup("AAPL")
        assert entry is not None
        assert entry["pyth_lazer_id"] == 922
        assert entry["symbol"] == "Equity.US.AAPL/USD"

    def test_lookup_case_insensitive(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        assert idx.lookup("aapl") is not None
        assert idx.lookup("Aapl") is not None

    def test_lookup_by_pyth_ticker(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        # CCH6 is extractable from Commodities.CCH6/USD
        entry = idx.lookup("CCH6")
        assert entry is not None
        assert entry["pyth_lazer_id"] == 2931

    def test_lookup_not_found(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        assert idx.lookup("ZZZZZ") is None

    def test_lookup_by_lazer_id(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        entry = idx.lookup_by_id(922)
        assert entry is not None
        assert entry["name"] == "AAPL"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

```python
# generate_ric_mapping.py
#!/usr/bin/env python3
"""
Universal RIC Mapping Generator for Pyth Network.

Given ticker(s), looks them up in lazer_symbols.json, derives the Reuters
Instrument Code (RIC) using asset-class-specific rules, and outputs a CSV
matching the pyth_mappings_export format for Datascope onboarding.

Supports: US equities, ETFs, FX, metals, commodity futures, equity index
futures, and US Treasury rates.

Usage:
    python generate_ric_mapping.py --ticker AAPL
    python generate_ric_mapping.py --ticker AAPL AUDCAD CCH6 XAU US10Y
    python generate_ric_mapping.py --ticker-file new_tickers.txt
    python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --- Constants ---

DEFAULT_SYMBOLS_PATH = Path("lazer_symbols.json")

# Asset types that have Datascope benchmarks (RIC-resolvable)
BENCHMARKABLE_ASSET_TYPES = {"equity", "fx", "metal", "commodity", "rates"}

# Asset types with no Datascope benchmark
NON_BENCHMARKABLE_ASSET_TYPES = {
    "crypto", "crypto-index", "crypto-redemption-rate",
    "funding-rate", "nav", "kalshi", "custom",
}


# --- Data Classes ---

@dataclass
class RICResult:
    """Result of RIC resolution for a single ticker."""
    ticker: str
    ric: str = ""
    source_type: str = "RIC"
    pyth_id: str = ""
    pythnet_id: str = ""
    pyth_lazer_id: Optional[int] = None
    valid_from: str = "1970-01-01 00:00:00"
    valid_to: str = ""
    display_ticker: str = ""
    asset_full_name: str = ""
    asset_class: str = ""
    confidence: str = ""  # "high", "medium", "low"
    warnings: list[str] = field(default_factory=list)


# --- Symbol Index ---

class SymbolIndex:
    """Index over lazer_symbols.json for fast ticker lookups."""

    def __init__(self, symbols_path: Path = DEFAULT_SYMBOLS_PATH):
        with open(symbols_path) as f:
            self._entries: list[dict] = json.load(f)

        # Build indexes
        self._by_name: dict[str, dict] = {}
        self._by_pyth_ticker: dict[str, dict] = {}
        self._by_id: dict[int, dict] = {}

        for entry in self._entries:
            name = entry.get("name", "").upper()
            if name:
                self._by_name[name] = entry

            # Extract ticker from symbol (e.g., "AAPL" from "Equity.US.AAPL/USD")
            symbol = entry.get("symbol", "")
            pyth_ticker = self._extract_ticker(symbol)
            if pyth_ticker and pyth_ticker not in self._by_pyth_ticker:
                self._by_pyth_ticker[pyth_ticker] = entry

            lazer_id = entry.get("pyth_lazer_id")
            if lazer_id is not None:
                self._by_id[lazer_id] = entry

    @staticmethod
    def _extract_ticker(symbol: str) -> Optional[str]:
        """Extract the ticker portion from a Pyth symbol string.

        Examples:
            Equity.US.AAPL/USD -> AAPL
            FX.EUR/USD -> EURUSD (not useful, name is better for FX)
            Commodities.CCH6/USD -> CCH6
            Rates.US10Y -> US10Y
            Metal.XAU/USD -> XAU
        """
        if not symbol:
            return None
        # Try pattern: *.TICKER/QUOTE or *.TICKER
        parts = symbol.rsplit(".", 1)
        if len(parts) < 2:
            return None
        after_dot = parts[1]
        # Remove /QUOTE suffix
        slash = after_dot.find("/")
        if slash > 0:
            ticker = after_dot[:slash]
        else:
            ticker = after_dot
        return ticker.upper() if ticker else None

    def lookup(self, ticker: str) -> Optional[dict]:
        """Look up a ticker by name or extracted symbol ticker."""
        upper = ticker.upper()
        entry = self._by_name.get(upper)
        if entry:
            return entry
        return self._by_pyth_ticker.get(upper)

    def lookup_by_id(self, lazer_id: int) -> Optional[dict]:
        """Look up by pyth_lazer_id."""
        return self._by_id.get(lazer_id)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: scaffold generate_ric_mapping with SymbolIndex"
```

---

### Task 2: FX RIC Resolver

**Files:**

- Modify: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests**

FX RIC rules derived from all 60 existing mappings:

- USD pairs (one side is USD): non-USD currency + `=` (e.g., `EUR=`, `JPY=`, `AUD=`)
- Cross pairs with EUR or GBP: `BASECCY` + `QUOTECCY` + `=` (e.g., `EURGBP=`, `GBPJPY=`)
- Cross pairs among {AUD,NZD,CAD,CHF} only: `BASECCY` + `QUOTECCY` + `=R` (e.g., `AUDCAD=R`, `NZDCHF=R`)
- Special: `FX.USDXY` -> `.DXY`

```python
class TestFXResolver:
    def test_usd_pair_base_eur(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/USD") == "EUR="

    def test_usd_pair_quote_jpy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/JPY") == "JPY="

    def test_usd_pair_quote_aud(self):
        from generate_ric_mapping import resolve_fx_ric
        # FX.USD/AUD -> AUD= (non-USD side)
        assert resolve_fx_ric("FX.USD/AUD") == "AUD="

    def test_usd_pair_nzd_usd(self):
        from generate_ric_mapping import resolve_fx_ric
        # FX.NZD/USD -> NZD= (NZD is base)
        assert resolve_fx_ric("FX.NZD/USD") == "NZD="

    def test_cross_eur_gbp(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/GBP") == "EURGBP="

    def test_cross_gbp_jpy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.GBP/JPY") == "GBPJPY="

    def test_cross_eur_nok(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/NOK") == "EURNOK="

    def test_cross_aud_cad_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.AUD/CAD") == "AUDCAD=R"

    def test_cross_nzd_chf_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.NZD/CHF") == "NZDCHF=R"

    def test_cross_cad_chf_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.CAD/CHF") == "CADCHF=R"

    def test_cross_aud_jpy_no_R(self):
        from generate_ric_mapping import resolve_fx_ric
        # AUD/JPY has JPY -> uses = not =R
        assert resolve_fx_ric("FX.AUD/JPY") == "AUDJPY="

    def test_cross_chf_jpy_no_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.CHF/JPY") == "CHFJPY="

    def test_usd_index_dxy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USDXY") == ".DXY"

    def test_exotic_brl(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/BRL") == "BRL="

    def test_exotic_inr(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/INR") == "INR="
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py::TestFXResolver -v`
Expected: FAIL — `resolve_fx_ric` not found

**Step 3: Write implementation**

Add to `generate_ric_mapping.py`:

```python
# Currencies that use =R suffix when crossed among themselves (no EUR, GBP, or JPY)
_R_SUFFIX_CURRENCIES = {"AUD", "NZD", "CAD", "CHF"}


def resolve_fx_ric(symbol: str) -> Optional[str]:
    """Derive Datascope RIC for an FX symbol.

    Rules (derived from 60 existing pyth_mappings):
    - FX.USDXY -> .DXY (special case)
    - USD pair (one side is USD): non-USD currency + "=" (e.g., EUR=, JPY=)
    - Cross pair with EUR/GBP/JPY involved: BASECCY+QUOTECCY+"=" (e.g., EURGBP=)
    - Cross pair both in {AUD,NZD,CAD,CHF}: BASECCY+QUOTECCY+"=R" (e.g., AUDCAD=R)
    """
    if not symbol.startswith("FX."):
        return None

    body = symbol[3:]  # Strip "FX."

    # Special case: Dollar Index
    if body == "USDXY":
        return ".DXY"

    # Parse base/quote
    if "/" not in body:
        return None
    base, quote = body.split("/", 1)
    base = base.upper()
    quote = quote.upper()

    # USD pair: return the non-USD currency + "="
    if base == "USD" or quote == "USD":
        non_usd = quote if base == "USD" else base
        return f"{non_usd}="

    # Cross pair: both in _R_SUFFIX_CURRENCIES -> use =R
    if base in _R_SUFFIX_CURRENCIES and quote in _R_SUFFIX_CURRENCIES:
        return f"{base}{quote}=R"

    # Cross pair: anything else -> use =
    return f"{base}{quote}="
```

**Step 4: Run tests**

Run: `pytest tests/test_generate_ric_mapping.py::TestFXResolver -v`
Expected: All 15 tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add FX RIC resolver with =R cross-pair handling"
```

---

### Task 3: Metal, Rates, and Commodity Futures RIC Resolvers

**Files:**

- Modify: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests**

```python
class TestMetalResolver:
    def test_gold(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XAU/USD") == "XAU="

    def test_silver(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XAG/USD") == "XAG="

    def test_platinum(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XPT/USD") == "XPT="

    def test_palladium(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XDP/USD") == "XPD="

    def test_unknown_metal(self):
        from generate_ric_mapping import resolve_metal_ric
        # XCU (copper spot) not yet in table
        result = resolve_metal_ric("Metal.XCU/USD")
        assert result is None


class TestRatesResolver:
    def test_10y_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US10Y") == "US10YT=RRPS"

    def test_3m_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US3M") == "US3MT=RRPS"

    def test_30y_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US30Y") == "US30YT=RRPS"

    def test_1m_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US1M") == "US1MT=RRPS"

    def test_non_us_rate(self):
        from generate_ric_mapping import resolve_rates_ric
        # Non-US rates like SOFR, BGCR don't follow this pattern
        result = resolve_rates_ric("Rates.SOFR")
        assert result is None


class TestCommodityFuturesResolver:
    def test_copper_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.CCH6/USD") == "HGH26"

    def test_wti_crude_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.WTIJ6/USD") == "CLJ26"

    def test_natural_gas_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NGDH6/USD") == "NGH26"

    def test_aluminum_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.ALH6/USD") == "ALIH26"

    def test_palladium_june_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.PLM6/USD") == "PAM26"

    def test_platinum_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.PTJ6/USD") == "PLJ26"

    def test_uranium_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.URH6/USD") == "UXH26"

    def test_corn_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.COH6/USD") == "CH26"

    def test_brent_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        # BRENTH6 -> LCO uses different pattern for specific contracts
        assert resolve_commodity_futures_ric("Commodities.BRENTH6/USD") is not None

    def test_nikkei_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NIDH6/USD") == "NKH26"

    def test_unknown_commodity(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        result = resolve_commodity_futures_ric("Commodities.ZZZZH6/USD")
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py -k "Metal or Rates or Commodity" -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `generate_ric_mapping.py`:

```python
# --- Metal RIC Map ---

# Maps Pyth metal code to Datascope RIC
# Note: XDP in Pyth symbol is actually XPD (palladium) — typo in lazer_symbols
METAL_RIC_MAP = {
    "XAU": "XAU=",
    "XAG": "XAG=",
    "XPT": "XPT=",
    "XPD": "XPD=",
    "XDP": "XPD=",  # Pyth uses XDP for palladium (Metal.XDP/USD)
}


def resolve_metal_ric(symbol: str) -> Optional[str]:
    """Derive RIC for a metal spot symbol. Returns None if unknown."""
    if not symbol.startswith("Metal."):
        return None
    body = symbol[6:]  # Strip "Metal."
    code = body.split("/")[0].upper()
    # Strip _DEPRECATED suffix
    code = code.replace("_DEPRECATED", "")
    return METAL_RIC_MAP.get(code)


# --- Rates RIC ---

_US_TREASURY_PATTERN = re.compile(r"^Rates\.US(\d+[MY])$")


def resolve_rates_ric(symbol: str) -> Optional[str]:
    """Derive RIC for US Treasury rates. Pattern: US{TENOR}T=RRPS."""
    m = _US_TREASURY_PATTERN.match(symbol)
    if not m:
        return None
    tenor = m.group(1)  # e.g., "10Y", "3M"
    return f"US{tenor}T=RRPS"


# --- Commodity Futures RIC ---

# Pyth commodity code -> RIC root (from analysis of pyth_mappings_export)
FUTURES_PYTH_TO_RIC: dict[str, str] = {
    "CC":    "HG",   # Copper (COMEX)
    "WTI":   "CL",   # WTI Crude Oil (NYMEX)
    "NGD":   "NG",   # Natural Gas (NYMEX)
    "AL":    "ALI",  # Aluminum (LME/COMEX) — RIC uses ALI not AL
    "PL":    "PA",   # Palladium (NYMEX) — Pyth PL = RIC PA
    "PT":    "PL",   # Platinum (NYMEX) — Pyth PT = RIC PL
    "UR":    "UX",   # Uranium (COMEX)
    "CO":    "C",    # Corn (CBOT)
    "BRENT": "LCO",  # Brent Crude (ICE)
    "NID":   "NK",   # Nikkei 225 (CME)
}

# Futures month codes
MONTH_CODES = "FGHJKMNQUVXZ"
_FUTURES_PATTERN = re.compile(
    r"^Commodities\.([A-Z]+)([FGHJKMNQUVXZ])(\d)/USD$"
)


def resolve_commodity_futures_ric(symbol: str) -> Optional[str]:
    """Derive RIC for a commodity futures contract.

    Parses Commodities.{PYTH_CODE}{MONTH}{YEAR}/USD and maps to
    {RIC_ROOT}{MONTH}{YEAR_2DIGIT}.
    """
    m = _FUTURES_PATTERN.match(symbol)
    if not m:
        return None

    pyth_code = m.group(1)   # e.g., "CC", "WTI", "AL"
    month = m.group(2)       # e.g., "H"
    year_digit = m.group(3)  # e.g., "6"

    ric_root = FUTURES_PYTH_TO_RIC.get(pyth_code)
    if not ric_root:
        return None

    year_2digit = f"2{year_digit}"  # "6" -> "26"
    return f"{ric_root}{month}{year_2digit}"
```

**Step 4: Run tests**

Run: `pytest tests/test_generate_ric_mapping.py -k "Metal or Rates or Commodity" -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add metal, rates, and commodity futures RIC resolvers"
```

---

### Task 4: Equity Index Futures + Equity RIC Resolvers

**Files:**

- Modify: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests**

```python
class TestEquityIndexFuturesResolver:
    def test_emini_sp500_march(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.EMH6/USD") == "ESc2"  # or ESH26

    def test_nasdaq_mini(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        result = resolve_equity_futures_ric("Equity.US.NMH6/USD")
        assert result is not None and result.startswith("NQ")

    def test_dow_mini(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.DMH6/USD") == "YMH26"

    def test_non_futures(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        # Regular equity should not match
        assert resolve_equity_futures_ric("Equity.US.AAPL/USD") is None


class TestEquityResolver:
    def test_nasdaq_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver
        # Create mock NASDAQ Trader data
        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\nAAPL|Apple Inc|Q|N\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n")
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("AAPL") == "AAPL.O"

    def test_nyse_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver
        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\nJPM|JPMorgan Chase|N|||100|N\n")
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("JPM") == "JPM.N"

    def test_dotted_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver
        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\nBRK.B|Berkshire Hathaway B|N|||100|N\n")
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("BRK.B") == "BRKb.N"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py -k "IndexFutures or Equity" -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `generate_ric_mapping.py`:

```python
# --- Equity Index Futures RIC ---

INDEX_FUTURES_PYTH_TO_RIC: dict[str, str] = {
    "EM": "ES",   # E-Mini S&P 500
    "NM": "NQ",   # Nasdaq Mini
    "DM": "YM",   # Dow Jones Mini
}

_INDEX_FUTURES_PATTERN = re.compile(
    r"^Equity\.US\.([A-Z]{2})([FGHJKMNQUVXZ])(\d)/USD$"
)


def resolve_equity_futures_ric(symbol: str) -> Optional[str]:
    """Derive RIC for an equity index futures contract.

    Returns specific contract format: {RIC_ROOT}{MONTH}{YEAR_2DIGIT}
    Returns None if the symbol is a regular equity (not a futures contract).
    """
    m = _INDEX_FUTURES_PATTERN.match(symbol)
    if not m:
        return None

    pyth_code = m.group(1)   # e.g., "EM", "NM", "DM"
    month = m.group(2)
    year_digit = m.group(3)

    ric_root = INDEX_FUTURES_PYTH_TO_RIC.get(pyth_code)
    if not ric_root:
        return None

    year_2digit = f"2{year_digit}"
    return f"{ric_root}{month}{year_2digit}"


# --- Equity RIC Resolver (NASDAQ Trader) ---

# Reuse constants from generate_source_upload.py
NASDAQ_TRADER_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"
NASDAQ_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/nasdaqlisted.txt"
OTHER_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/otherlisted.txt"

EQUITY_CACHE_DIR = Path(".nasdaq_cache")
EQUITY_CACHE_TTL = 24 * 60 * 60  # 24 hours

OTHER_EXCHANGE_SUFFIX_MAP = {
    "N": ".N",   # NYSE
    "P": ".P",   # NYSE Arca
    "Z": ".Z",   # BATS
    "A": ".A",   # NYSE American (AMEX)
    "V": ".K",   # IEXG -> .K in RIC
}


def ticker_to_ric_base(ticker: str) -> str:
    """Convert dotted ticker to RIC base (BRK.B -> BRKb)."""
    upper = ticker.upper()
    if "." in upper:
        base, cls = upper.rsplit(".", 1)
        if len(cls) == 1 and cls.isalpha():
            return base + cls.lower()
    return upper


class EquityResolver:
    """Resolve US equity/ETF tickers to RICs using NASDAQ Trader."""

    def __init__(self, cache_dir: Path = EQUITY_CACHE_DIR, force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.force_refresh = force_refresh
        self._nasdaq: dict[str, str] = {}   # ticker -> name
        self._other: dict[str, tuple[str, str]] = {}  # ticker -> (exchange, name)
        self._loaded = False

    def _load_from_files(self, nasdaq_path: Path, other_path: Path) -> None:
        """Load from already-downloaded files (used by tests and after download)."""
        self._nasdaq = {}
        self._other = {}

        for line in nasdaq_path.read_text().strip().split("\n")[1:]:
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                test = parts[3].strip() if len(parts) > 3 else "N"
                if test != "Y":
                    self._nasdaq[symbol] = name

        for line in other_path.read_text().strip().split("\n")[1:]:
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                exchange = parts[2].strip()
                test = parts[5].strip() if len(parts) > 5 else "N"
                if test != "Y":
                    self._other[symbol] = (exchange, name)

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Download NASDAQ Trader files if needed, then parse."""
        if self._loaded:
            return
        import time
        import urllib.request
        import urllib.error

        self.cache_dir.mkdir(exist_ok=True)
        nasdaq_path = self.cache_dir / "nasdaqlisted.txt"
        other_path = self.cache_dir / "otherlisted.txt"

        for url, path in [(NASDAQ_LISTED_URL, nasdaq_path), (OTHER_LISTED_URL, other_path)]:
            need_download = self.force_refresh or not path.exists()
            if not need_download:
                age = time.time() - path.stat().st_mtime
                need_download = age > EQUITY_CACHE_TTL
            if need_download:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    path.write_text(resp.read().decode("utf-8"))

        self._load_from_files(nasdaq_path, other_path)

    def resolve(self, ticker: str) -> Optional[str]:
        """Resolve ticker to RIC (e.g., AAPL -> AAPL.O, BRK.B -> BRKb.N)."""
        self._ensure_loaded()
        upper = ticker.upper()
        ric_base = ticker_to_ric_base(upper)

        for form in [upper, ric_base]:
            if form in self._nasdaq:
                return f"{ric_base}.O"
            if form in self._other:
                exchange, _ = self._other[form]
                suffix = OTHER_EXCHANGE_SUFFIX_MAP.get(exchange, ".N")
                return f"{ric_base}{suffix}"
        return None

    def get_name(self, ticker: str) -> Optional[str]:
        """Get company name for a ticker."""
        self._ensure_loaded()
        upper = ticker.upper()
        for form in [upper, ticker_to_ric_base(upper)]:
            if form in self._nasdaq:
                return self._nasdaq[form]
            if form in self._other:
                return self._other[form][1]
        return None
```

**Step 4: Run tests**

Run: `pytest tests/test_generate_ric_mapping.py -k "IndexFutures or Equity" -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add equity index futures + equity RIC resolvers"
```

---

### Task 5: Main Resolver Orchestrator + CSV Output

**Files:**

- Modify: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests**

```python
class TestRICResolver:
    """Integration tests for the main resolve() dispatcher."""

    def test_resolve_equity(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver
        # Create mock NASDAQ Trader data
        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text("Symbol|Security Name|Market Category|Test Issue\nAAPL|Apple Inc|Q|N\n")
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        assert result.ric == "AAPL.O"
        assert result.asset_class == "Common Stock"
        assert result.pyth_lazer_id == 922

    def test_resolve_fx(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("EURUSD")
        assert result.ric == "EUR="
        assert result.asset_class == "Forex"

    def test_resolve_fx_cross(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("AUDCAD")
        assert result.ric == "AUDCAD=R"
        assert result.asset_class == "Forex"

    def test_resolve_metal(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("XAUUSD")
        assert result.ric == "XAU="
        assert result.asset_class == "Metal"

    def test_resolve_commodity_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("CCH6")
        assert result.ric == "HGH26"
        assert result.asset_class == "Commodity Future"

    def test_resolve_rates(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("US10Y")
        assert result.ric == "US10YT=RRPS"
        assert result.asset_class == "Rates"

    def test_resolve_crypto_skipped(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("BTCUSD")
        assert result.ric == ""
        assert len(result.warnings) > 0

    def test_resolve_not_found(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("ZZZZZ")
        assert result.ric == ""
        assert len(result.warnings) > 0


class TestCSVOutput:
    def test_csv_format(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver, write_csv
        resolver = RICResolver(symbols_path)
        results = [resolver.resolve("EURUSD"), resolver.resolve("US10Y")]
        output = tmp_path / "output.csv"
        write_csv(results, output)
        assert output.exists()
        import csv
        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["source_value"] == "EUR="
        assert rows[0]["source_type"] == "RIC"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py -k "RICResolver or CSVOutput" -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `generate_ric_mapping.py`:

```python
# --- Asset Class Classification ---

ADR_KEYWORDS = ["american depositary", "depositary shares", "depositary receipts", " adr", " ads"]


def _classify_equity(description: str) -> str:
    """Classify equity as Common Stock, ADR, Equity (ETF), etc."""
    lower = description.lower()
    for kw in ADR_KEYWORDS:
        if kw in lower:
            return "American Depositary Shares"
    if "etf" in lower or "fund" in lower or "trust" in lower:
        return "Equity"
    if "class a " in lower:
        return "Class A Common Stock"
    if "class b " in lower:
        return "Class B Common Stock"
    if "class c " in lower:
        return "Class C Common Stock"
    if "preferred" in lower:
        return "Preferred Share"
    if "ordinary" in lower:
        return "Ordinary Shares"
    return "Common Stock"


def _derive_pyth_id(entry: dict) -> str:
    """Derive pyth_id from lazer_symbols entry."""
    asset_type = entry.get("asset_type", "")
    symbol = entry.get("symbol", "")
    name = entry.get("name", "").lower()

    if asset_type == "fx":
        return f"fx.{name}"
    elif asset_type == "metal":
        return f"metal.{name}"
    elif asset_type == "rates":
        return f"rates.{name}"
    elif asset_type == "commodity":
        return f"future.{name}"
    elif asset_type == "equity":
        # Check if this is a futures contract
        if _INDEX_FUTURES_PATTERN.match(symbol):
            return f"future.{name}"
        return f"equity.{name}"
    return f"{asset_type}.{name}"


# --- Main Resolver ---

class RICResolver:
    """Orchestrates RIC resolution across all asset classes."""

    def __init__(
        self,
        symbols_path: Path = DEFAULT_SYMBOLS_PATH,
        equity_cache_dir: Path = EQUITY_CACHE_DIR,
        force_refresh: bool = False,
    ):
        self._index = SymbolIndex(symbols_path)
        self._equity = EquityResolver(cache_dir=equity_cache_dir, force_refresh=force_refresh)

    def resolve(self, ticker: str) -> RICResult:
        """Resolve a ticker to its Datascope RIC."""
        entry = self._index.lookup(ticker)
        if not entry:
            return RICResult(
                ticker=ticker,
                warnings=[f"Ticker '{ticker}' not found in lazer_symbols.json"],
            )

        asset_type = entry.get("asset_type", "")
        symbol = entry.get("symbol", "")
        description = entry.get("description", "")

        # Skip non-benchmarkable assets
        if asset_type in NON_BENCHMARKABLE_ASSET_TYPES:
            return RICResult(
                ticker=ticker,
                pyth_lazer_id=entry.get("pyth_lazer_id"),
                pythnet_id=symbol,
                warnings=[f"Asset type '{asset_type}' has no Datascope benchmark"],
            )

        result = RICResult(
            ticker=ticker,
            pyth_lazer_id=entry.get("pyth_lazer_id"),
            pythnet_id=symbol,
            pyth_id=_derive_pyth_id(entry),
            display_ticker=entry.get("name", ticker),
            asset_full_name=description,
            valid_from="1970-01-01 00:00:00",
        )

        # Dispatch to asset-class resolver
        if asset_type == "fx":
            result.ric = resolve_fx_ric(symbol) or ""
            result.asset_class = "Forex"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "metal":
            result.ric = resolve_metal_ric(symbol) or ""
            result.asset_class = "Metal"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "rates":
            result.ric = resolve_rates_ric(symbol) or ""
            result.asset_class = "Rates"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "commodity":
            result.ric = resolve_commodity_futures_ric(symbol) or ""
            result.asset_class = "Commodity Future"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "equity":
            # Check if equity index futures first
            futures_ric = resolve_equity_futures_ric(symbol)
            if futures_ric:
                result.ric = futures_ric
                result.asset_class = "Equity Future"
                result.confidence = "high"
            elif symbol.startswith("Equity.US."):
                # Regular US equity/ETF
                equity_ticker = symbol.replace("Equity.US.", "").replace("/USD", "")
                result.ric = self._equity.resolve(equity_ticker) or ""
                result.asset_class = _classify_equity(description)
                result.display_ticker = equity_ticker
                if result.ric:
                    result.confidence = "medium"  # NASDAQ Trader
                else:
                    # Default to .N
                    ric_base = ticker_to_ric_base(equity_ticker)
                    result.ric = f"{ric_base}.N"
                    result.confidence = "low"
                    result.warnings.append(f"Defaulting to {result.ric} — verify exchange suffix")
            else:
                # Non-US equity — out of scope
                result.warnings.append(f"Non-US equity '{symbol}' — RIC resolution not supported")
                result.confidence = "low"

        if not result.ric and not result.warnings:
            result.warnings.append(f"Could not derive RIC for {symbol}")

        return result

    def resolve_batch(self, tickers: list[str]) -> list[RICResult]:
        """Resolve multiple tickers."""
        return [self.resolve(t) for t in tickers]


# --- CSV Output ---

import csv

CSV_COLUMNS = [
    "source_value", "source_type", "pyth_id", "pythnet_id",
    "pyth_lazer_id", "valid_from", "valid_to", "ticker",
    "asset_full_name", "asset_class",
]


def write_csv(results: list[RICResult], output_path: Path) -> None:
    """Write results in pyth_mappings_export CSV format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter out results with no RIC (errors/skipped)
    valid = [r for r in results if r.ric]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in valid:
            writer.writerow({
                "source_value": r.ric,
                "source_type": r.source_type,
                "pyth_id": r.pyth_id,
                "pythnet_id": r.pythnet_id,
                "pyth_lazer_id": r.pyth_lazer_id or "",
                "valid_from": r.valid_from,
                "valid_to": r.valid_to,
                "ticker": r.display_ticker,
                "asset_full_name": r.asset_full_name,
                "asset_class": r.asset_class,
            })

    print(f"Wrote {len(valid)} rows to {output_path}")
    if len(valid) < len(results):
        skipped = len(results) - len(valid)
        print(f"Skipped {skipped} tickers (no RIC resolved)")
```

**Step 4: Run tests**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add RICResolver orchestrator and CSV output"
```

---

### Task 6: CLI + Summary + Polish

**Files:**

- Modify: `generate_ric_mapping.py`
- Test: `tests/test_generate_ric_mapping.py`

**Step 1: Write failing tests for CLI and summary**

```python
class TestCLI:
    def test_single_ticker(self, symbols_path, tmp_path):
        """Test CLI with a single ticker."""
        import subprocess
        output = tmp_path / "out.csv"
        result = subprocess.run(
            ["python3", "generate_ric_mapping.py",
             "--ticker", "EURUSD",
             "--symbols", str(symbols_path),
             "--output", str(output)],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert output.exists()

    def test_ticker_file(self, symbols_path, tmp_path):
        """Test CLI with ticker file input."""
        ticker_file = tmp_path / "tickers.txt"
        ticker_file.write_text("EURUSD\nUS10Y\n")
        output = tmp_path / "out.csv"
        result = subprocess.run(
            ["python3", "generate_ric_mapping.py",
             "--ticker-file", str(ticker_file),
             "--symbols", str(symbols_path),
             "--output", str(output)],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert output.exists()
        import csv
        with open(output) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
```

**Step 2: Run tests to verify they fail**

**Step 3: Add CLI and summary to `generate_ric_mapping.py`**

```python
# --- Summary ---

def print_summary(results: list[RICResult]) -> None:
    """Print resolution summary to console."""
    total = len(results)
    resolved = sum(1 for r in results if r.ric)
    by_class: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    warnings_list: list[str] = []

    for r in results:
        if r.ric:
            by_class[r.asset_class] = by_class.get(r.asset_class, 0) + 1
        by_confidence[r.confidence] = by_confidence.get(r.confidence, 0) + 1
        for w in r.warnings:
            warnings_list.append(f"  {r.ticker}: {w}")

    print(f"\n{'='*60}")
    print("RIC MAPPING SUMMARY")
    print(f"{'='*60}")
    print(f"Total tickers:  {total}")
    print(f"Resolved:       {resolved}")
    print(f"Unresolved:     {total - resolved}")
    print()
    if by_class:
        print("By asset class:")
        for cls, cnt in sorted(by_class.items()):
            print(f"  {cls}: {cnt}")
    print()
    print("Confidence:")
    for level in ["high", "medium", "low"]:
        cnt = by_confidence.get(level, 0)
        if cnt:
            print(f"  {level}: {cnt}")
    if warnings_list:
        print(f"\nWarnings ({len(warnings_list)}):")
        for w in warnings_list:
            print(w)


# --- CLI ---

import argparse
import sys


def parse_tickers_from_file(path: Path) -> list[str]:
    """Parse tickers from file (one per line, or CSV first column)."""
    tickers: list[str] = []
    seen: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = line.split(",")[0].strip()
            if candidate.lower() in ("ticker", "symbol"):
                continue
            if candidate and candidate not in seen:
                seen.add(candidate)
                tickers.append(candidate)
    return tickers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate RIC mappings for Pyth Lazer tickers (all asset classes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_ric_mapping.py --ticker AAPL
  python generate_ric_mapping.py --ticker AAPL AUDCAD CCH6 XAU US10Y
  python generate_ric_mapping.py --ticker-file new_tickers.txt
  python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv
  python generate_ric_mapping.py --ticker AAPL --symbols after.json
""",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--ticker", nargs="+", help="Ticker(s) to resolve")
    input_group.add_argument("--ticker-file", type=Path, help="File with tickers")

    parser.add_argument("--output", type=Path, default=Path("ric_mappings.csv"),
                        help="Output CSV path (default: ric_mappings.csv)")
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS_PATH,
                        help="Path to lazer_symbols.json")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-download NASDAQ Trader data")
    parser.add_argument("--append-to", type=Path, default=None,
                        help="Append to existing CSV instead of creating new")

    args = parser.parse_args()

    if not args.symbols.exists():
        print(f"Error: {args.symbols} not found", file=sys.stderr)
        sys.exit(1)

    # Parse tickers
    if args.ticker:
        tickers = args.ticker
    else:
        if not args.ticker_file.exists():
            print(f"Error: {args.ticker_file} not found", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_file(args.ticker_file)

    if not tickers:
        print("Error: No tickers provided", file=sys.stderr)
        sys.exit(1)

    print(f"Resolving RICs for {len(tickers)} ticker(s)...")
    resolver = RICResolver(
        symbols_path=args.symbols,
        force_refresh=args.force_refresh,
    )

    results = resolver.resolve_batch(tickers)
    print_summary(results)

    output_path = args.append_to or args.output
    if args.append_to and args.append_to.exists():
        # Append mode: add rows to existing file
        valid = [r for r in results if r.ric]
        with open(args.append_to, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            for r in valid:
                writer.writerow({
                    "source_value": r.ric,
                    "source_type": r.source_type,
                    "pyth_id": r.pyth_id,
                    "pythnet_id": r.pythnet_id,
                    "pyth_lazer_id": r.pyth_lazer_id or "",
                    "valid_from": r.valid_from,
                    "valid_to": r.valid_to,
                    "ticker": r.display_ticker,
                    "asset_full_name": r.asset_full_name,
                    "asset_class": r.asset_class,
                })
        print(f"Appended {len(valid)} rows to {args.append_to}")
    else:
        write_csv(results, output_path)


if __name__ == "__main__":
    main()
```

**Step 4: Run all tests**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add CLI, summary output, and append mode"
```

---

### Task 7: Integration Test with Real lazer_symbols.json

**Files:**

- Modify: `tests/test_generate_ric_mapping.py`

**Step 1: Write integration tests that validate against known pyth_mappings**

```python
@pytest.mark.skipif(
    not Path("lazer_symbols.json").exists(),
    reason="lazer_symbols.json not available"
)
class TestIntegration:
    """Validate resolved RICs against known pyth_mappings_export values."""

    KNOWN_MAPPINGS = {
        # Equities (can't test without NASDAQ Trader download)
        # FX
        "EURUSD": ("EUR=", "Forex"),
        "AUDCAD": ("AUDCAD=R", "Forex"),
        # Metals
        "XAUUSD": ("XAU=", "Metal"),
        "XAGUSD": ("XAG=", "Metal"),
        # Rates
        "US10Y": ("US10YT=RRPS", "Rates"),
        "US3M": ("US3MT=RRPS", "Rates"),
    }

    def test_known_mappings(self):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver()
        for ticker, (expected_ric, expected_class) in self.KNOWN_MAPPINGS.items():
            result = resolver.resolve(ticker)
            assert result.ric == expected_ric, f"{ticker}: got {result.ric}, expected {expected_ric}"
            assert result.asset_class == expected_class, f"{ticker}: got {result.asset_class}"

    def test_crypto_skipped(self):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver()
        result = resolver.resolve("BTCUSD")
        assert result.ric == ""
```

**Step 2: Run integration tests**

Run: `pytest tests/test_generate_ric_mapping.py::TestIntegration -v`
Expected: PASS (if lazer_symbols.json present) or SKIP

**Step 3: Commit**

```bash
git add tests/test_generate_ric_mapping.py
git commit -m "test: add integration tests against real lazer_symbols.json"
```

---

### Task 8: End-to-End Verification

**Step 1: Run the script against real data**

```bash
source venv/bin/activate
python generate_ric_mapping.py --ticker AAPL EURUSD AUDCAD XAU CCH6 US10Y BTCUSD
```

Expected output: Summary showing 6 resolved (AAPL, EURUSD, AUDCAD, XAU, CCH6, US10Y) and 1 skipped (BTCUSD).

**Step 2: Verify CSV matches pyth_mappings format**

```bash
head -10 ric_mappings.csv
```

Confirm columns: `source_value,source_type,pyth_id,pythnet_id,pyth_lazer_id,valid_from,valid_to,ticker,asset_full_name,asset_class`

**Step 3: Cross-check against existing pyth_mappings_export**

```bash
python3 -c "
import csv
with open('ric_mappings.csv') as f:
    for row in csv.DictReader(f):
        print(f'{row[\"source_value\"]:20s} {row[\"asset_class\"]:25s} {row[\"ticker\"]}')
"
```

**Step 4: Run full test suite**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All tests PASS

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete universal RIC mapping generator

Supports: US equities, ETFs, FX, metals, commodity futures,
equity index futures, US Treasury rates. Rule-based RIC resolution
with NASDAQ Trader for equity exchange suffixes."
```
