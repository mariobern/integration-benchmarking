# Extend Futures Mappings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 5 new commodity futures RIC mappings (NL, LE, TI, RS, GO), 3 equity index futures aliases (US500, US100, US30), and fix the equity index regex to support variable-length codes.

**Architecture:** Dictionary additions to `FUTURES_PYTH_TO_RIC` and `INDEX_FUTURES_PYTH_TO_RIC`, one regex change to `_INDEX_FUTURES_PATTERN`, and matching tests. No new files, no structural changes.

**Tech Stack:** Python, pytest

---

### Task 1: Add commodity futures test cases

**Files:**

- Modify: `tests/test_generate_ric_mapping.py:218` (add after `test_nikkei_march_2026`)

**Step 1: Write the failing tests**

Add these test methods inside the existing `TestCommodityFuturesResolver` class (after line 218, before `test_unknown_commodity`):

```python
    def test_nickel_february_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NLG6/USD") == "MNIG26"

    def test_nickel_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NLH6/USD") == "MNIH26"

    def test_lead_june_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.LEM6/USD") == "MPBM26"

    def test_lead_september_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.LEU6/USD") == "MPBU26"

    def test_tin_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.TIH6/USD") == "MSNH26"

    def test_raw_sugar_february_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.RSH6/USD") == "SBH26"

    def test_raw_sugar_may_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.RSK6/USD") == "SBK26"

    def test_gasoil_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.GOH6/USD") == "LGOH26"

    def test_gasoil_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.GOJ6/USD") == "LGOJ26"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_generate_ric_mapping.py::TestCommodityFuturesResolver -v`
Expected: 9 new tests FAIL with `AssertionError` (returns `None` because roots not in dict)

---

### Task 2: Add commodity futures mappings

**Files:**

- Modify: `generate_ric_mapping.py:124-135` (add entries to `FUTURES_PYTH_TO_RIC`)

**Step 1: Add the 5 new entries to the dictionary**

Add after line 134 (`"NID":   "NK",`), before the closing `}`:

```python
    "NL":    "MNI",  # Nickel (LME)
    "LE":    "MPB",  # Lead (LME)
    "TI":    "MSN",  # Tin (LME)
    "RS":    "SB",   # Raw Sugar No. 11 (ICE US)
    "GO":    "LGO",  # Low Sulphur Gasoil (ICE Europe)
```

**Step 2: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_generate_ric_mapping.py::TestCommodityFuturesResolver -v`
Expected: ALL tests PASS (19 existing + 9 new = 28 total)

**Step 3: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add NL/LE/TI/RS/GO commodity futures RIC mappings"
```

---

### Task 3: Add equity index futures test cases

**Files:**

- Modify: `tests/test_generate_ric_mapping.py:242` (add after `test_non_futures` in `TestEquityIndexFuturesResolver`)

**Step 1: Write the failing tests**

Add these test methods inside the existing `TestEquityIndexFuturesResolver` class (after `test_non_futures`):

```python
    def test_us500_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.US500H6/USD") == "ESH26"

    def test_us100_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.US100H6/USD") == "NQH26"

    def test_us30_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.US30H6/USD") == "YMH26"

    def test_us500_june_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.US500M6/USD") == "ESM26"

    def test_us30_september_2025(self):
        from generate_ric_mapping import resolve_equity_futures_ric
        assert resolve_equity_futures_ric("Equity.US.US30U5/USD") == "YMU25"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_generate_ric_mapping.py::TestEquityIndexFuturesResolver -v`
Expected: 5 new tests FAIL — the regex `([A-Z]{2})` rejects `US500`, `US100`, `US30` (too many chars / contains digits)

---

### Task 4: Fix equity index regex and add mappings

**Files:**

- Modify: `generate_ric_mapping.py:162-170` (add dict entries + fix regex)

**Step 1: Add the 3 new entries to the dictionary**

Add after line 165 (`"DM": "YM",`), before the closing `}`:

```python
    "US500": "ES",  # S&P 500 E-mini (alias for EM)
    "US100": "NQ",  # Nasdaq 100 E-mini (alias for NM)
    "US30":  "YM",  # Dow Jones E-mini (alias for DM)
```

**Step 2: Fix the regex pattern**

Change line 168-170 from:

```python
_INDEX_FUTURES_PATTERN = re.compile(
    r"^Equity\.US\.([A-Z]{2})([FGHJKMNQUVXZ])(\d)/USD$"
)
```

To:

```python
_INDEX_FUTURES_PATTERN = re.compile(
    r"^Equity\.US\.([A-Z][A-Z0-9]*)([FGHJKMNQUVXZ])(\d)/USD$"
)
```

**Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_generate_ric_mapping.py::TestEquityIndexFuturesResolver -v`
Expected: ALL tests PASS (4 existing + 5 new = 9 total)

**Step 4: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat: add US500/US100/US30 equity index futures aliases and fix regex"
```

---

### Task 5: Add integration test with lazer_symbols fixture + full regression

**Files:**

- Modify: `tests/test_generate_ric_mapping.py` (add fixture entries + integration tests in `TestRICResolver`)

**Step 1: Add new symbols to `SAMPLE_SYMBOLS` fixture**

Add these entries to the `SAMPLE_SYMBOLS` list at the top of the file (after the existing `DMH6` entry, before `BTCUSD`):

```python
    {"pyth_lazer_id": 9001, "name": "NLH6", "symbol": "Commodities.NLH6/USD",
     "description": "NICKEL 18 MARCH 2026", "asset_type": "commodity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 9002, "name": "RSK6", "symbol": "Commodities.RSK6/USD",
     "description": "RAW SUGAR 30 APRIL 2026", "asset_type": "commodity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 9003, "name": "US500H6", "symbol": "Equity.US.US500H6/USD",
     "description": "PYTH US500 20 MARCH 2026", "asset_type": "equity",
     "quote_currency": "USD"},
```

**Step 2: Write integration tests**

Add these test methods inside the existing `TestRICResolver` class (after `test_resolve_not_found`):

```python
    def test_resolve_nickel_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("NLH6")
        assert result.ric == "MNIH26"
        assert result.asset_class == "Commodity Future"
        assert result.confidence == "high"

    def test_resolve_sugar_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("RSK6")
        assert result.ric == "SBK26"
        assert result.asset_class == "Commodity Future"

    def test_resolve_us500_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver
        resolver = RICResolver(symbols_path)
        result = resolver.resolve("US500H6")
        assert result.ric == "ESH26"
        assert result.asset_class == "Equity Future"
        assert result.confidence == "high"
```

**Step 3: Run full test suite**

Run: `python3 -m pytest tests/test_generate_ric_mapping.py -v`
Expected: ALL tests PASS

**Step 4: Commit**

```bash
git add tests/test_generate_ric_mapping.py
git commit -m "test: add integration tests for new futures mappings"
```

---

### Task 6: Verify against test_tickers.txt

**Step 1: Run the resolver against all test tickers**

```bash
python3 generate_ric_mapping.py --ticker-file test_tickers.txt --symbols lazer_symbols.json
```

Expected: All 19 tickers resolve successfully with RICs:

- NLG6 → MNIG26, NLH6 → MNIH26, NLJ6 → MNIJ26
- NGDM6 → NGM26
- LEM6 → MPBM26, LEU6 → MPBU26
- TIH6 → MSNH26, TIM6 → MSNM26, TIU6 → MSNU26
- RSH6 → SBH26, RSK6 → SBK26, RSN6 → SBN26
- GOH6 → LGOH26, GOJ6 → LGOJ26, GOK6 → LGOK26
- WTIM6 → CLM26
- DMM6 → YMM26, EMM6 → ESM26, NMM6 → NQM26

**Step 2: Verify no regressions with existing tickers**

```bash
python3 generate_ric_mapping.py --ticker AAPL EURUSD XAUUSD CCH6 US10Y --symbols lazer_symbols.json
```

Expected: All existing tickers resolve as before.

**Step 3: Final commit with any fixes**

If all good, no commit needed. If fixes required, commit them.
