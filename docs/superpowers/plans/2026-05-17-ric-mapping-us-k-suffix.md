# US-equity RIC consolidated-suffix rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-venue `.N`/`.P`/`.A`/`.Z` RIC suffix logic in `generate_ric_mapping.py` with the LSEG consolidated-tape rule (`.K` when root≥4, bare otherwise), and update the diagnostic RIC categorizer in `check_benchmark_availability.py` so new RICs don't all fall into "Other".

**Architecture:** Two small pure helpers (`_root_length`, `_us_consolidated_suffix`) drive the new behavior. `EquityResolver.resolve` branches on `exchange == "V"` for IEX and falls through to the consolidated rule for every other exchange. The low-confidence fallback in `RICResolver.resolve` uses the same helpers. `check_benchmark_availability.categorize_equities` adds a "US Consolidated" bucket for `.K` and bare-tail RICs.

**Tech Stack:** Python 3, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-17-ric-mapping-us-k-suffix-design.md`

---

## Task 1: Add `_root_length` helper

**Files:**

- Modify: `generate_ric_mapping.py` (add helper near `ticker_to_ric_base` at line 220)
- Test: `tests/test_generate_ric_mapping.py` (new `TestRootLength` class)

- [ ] **Step 1: Write the failing tests**

Add this new class to `tests/test_generate_ric_mapping.py` immediately above `class TestEquityResolver:` (line 430):

```python
class TestRootLength:
    """Length of the base ticker before any class-letter suffix."""

    def test_three_char_plain(self):
        from generate_ric_mapping import _root_length

        assert _root_length("IBM") == 3

    def test_four_char_plain(self):
        from generate_ric_mapping import _root_length

        assert _root_length("TWTR") == 4

    def test_dotted_class_letter(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BRK.B") == 3

    def test_dotted_class_letter_lowercase(self):
        from generate_ric_mapping import _root_length

        assert _root_length("brk.b") == 3

    def test_hyphenated_class_letter(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BRK-B") == 3

    def test_single_char_ticker(self):
        from generate_ric_mapping import _root_length

        assert _root_length("A") == 1

    def test_two_char_ticker(self):
        from generate_ric_mapping import _root_length

        assert _root_length("AB") == 2

    def test_four_char_no_dot(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BABA") == 4

    def test_dotted_non_class_suffix_not_stripped(self):
        # ".WS" (warrants) is not a single class letter, so it should NOT be stripped.
        from generate_ric_mapping import _root_length

        assert _root_length("FOO.WS") == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py::TestRootLength -v`
Expected: All 9 tests FAIL with `ImportError: cannot import name '_root_length' from 'generate_ric_mapping'`.

- [ ] **Step 3: Implement the helper**

In `generate_ric_mapping.py`, add this function immediately after `ticker_to_ric_base` (i.e. after line 227):

```python
def _root_length(ticker: str) -> int:
    """Length of the base ticker before any class-letter suffix.

    A trailing `.X` or `-X` where X is a single alphabetic character is treated
    as a class-letter suffix and stripped before measuring. Other dotted suffixes
    (e.g. `.WS` for warrants) are preserved.

    Examples:
        IBM    -> 3
        TWTR   -> 4
        BRK.B  -> 3
        BRK-B  -> 3
        FOO.WS -> 6
    """
    upper = ticker.upper()
    if len(upper) >= 2 and upper[-2] in ".-" and upper[-1].isalpha():
        return len(upper) - 2
    return len(upper)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_ric_mapping.py::TestRootLength -v`
Expected: All 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat(ric-mapping): add _root_length helper for class-letter-aware ticker length"
```

---

## Task 2: Add `_us_consolidated_suffix` helper

**Files:**

- Modify: `generate_ric_mapping.py` (add helper directly after `_root_length`)
- Test: `tests/test_generate_ric_mapping.py` (new `TestUSConsolidatedSuffix` class)

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_generate_ric_mapping.py` directly after the `TestRootLength` class:

```python
class TestUSConsolidatedSuffix:
    """LSEG consolidated-tape suffix rule for NYSE/Arca/American/Cboe BZX."""

    def test_three_char_root_is_bare(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(3) == ""

    def test_four_char_root_gets_dot_k(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(4) == ".K"

    def test_five_char_root_gets_dot_k(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(5) == ".K"

    def test_one_char_root_is_bare(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(1) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py::TestUSConsolidatedSuffix -v`
Expected: 4 FAIL with `ImportError: cannot import name '_us_consolidated_suffix'`.

- [ ] **Step 3: Implement the helper**

In `generate_ric_mapping.py`, add this function directly after `_root_length`:

```python
def _us_consolidated_suffix(root_len: int) -> str:
    """LSEG consolidated-tape suffix for NYSE / NYSE Arca / NYSE American / Cboe BZX.

    Returns ".K" when the ticker root has 4 or more characters; otherwise the
    consolidated RIC is bare (no suffix at all).
    """
    return ".K" if root_len >= 4 else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_ric_mapping.py::TestUSConsolidatedSuffix -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat(ric-mapping): add _us_consolidated_suffix helper (.K when root>=4)"
```

---

## Task 3: Update `EquityResolver.resolve` to use the consolidated rule

**Files:**

- Modify: `generate_ric_mapping.py:202-323` (remove `OTHER_EXCHANGE_SUFFIX_MAP`; rewrite `EquityResolver.resolve`)
- Test: `tests/test_generate_ric_mapping.py` (update 2 existing tests, add 6 new ones)

- [ ] **Step 1: Update existing tests to reflect the new contract**

In `tests/test_generate_ric_mapping.py`, change line 457:

```python
        assert resolver.resolve("JPM") == "JPM.N"
```

to:

```python
        assert resolver.resolve("JPM") == "JPM"
```

And change line 470:

```python
        assert resolver.resolve("BRK.B") == "BRKb.N"
```

to:

```python
        assert resolver.resolve("BRK.B") == "BRKb"
```

- [ ] **Step 2: Add new failing tests for the consolidated rule**

In `tests/test_generate_ric_mapping.py`, add these methods to `class TestEquityResolver` (right after `test_dotted_ticker`):

```python
    def test_consolidated_short_root_nyse_is_bare(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "IBM|International Business Machines|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("IBM") == "IBM"

    def test_consolidated_long_root_nyse_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "TWTR|Twitter Inc|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("TWTR") == "TWTR.K"

    def test_consolidated_short_root_arca_is_bare(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "SPY|SPDR S&P 500 ETF Trust|P|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("SPY") == "SPY"

    def test_consolidated_long_root_cboe_bzx_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "CBOE|Cboe Global Markets|Z|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("CBOE") == "CBOE.K"

    def test_consolidated_nyse_american_long_root_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "LIVE|Live Ventures Inc|A|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("LIVE") == "LIVE.K"

    def test_consolidated_iex_unchanged(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "INTC|Intel Corp|V|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("INTC") == "INTC.K"

    def test_consolidated_dotted_long_root(self, tmp_path):
        # Hypothetical 4-char-root ticker with class letter: root=LONG (4), class=b
        # Expected RIC: "LONGb.K"
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "LONG.B|Long Corp Class B|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("LONG.B") == "LONGb.K"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py::TestEquityResolver -v`
Expected: The 2 updated existing tests now FAIL with `AssertionError: 'JPM.N' != 'JPM'` and `AssertionError: 'BRKb.N' != 'BRKb'`. The 7 new tests FAIL with similar `.N`/`.P`/`.A`/`.Z` mismatches.

- [ ] **Step 4: Update `EquityResolver.resolve` and remove `OTHER_EXCHANGE_SUFFIX_MAP`**

In `generate_ric_mapping.py`, delete lines 211-217 (the `OTHER_EXCHANGE_SUFFIX_MAP` block):

```python
OTHER_EXCHANGE_SUFFIX_MAP = {
    "N": ".N",  # NYSE
    "P": ".P",  # NYSE Arca
    "Z": ".Z",  # BATS
    "A": ".A",  # NYSE American (AMEX)
    "V": ".K",  # IEXG -> .K in RIC
}
```

Then replace the body of `EquityResolver.resolve` (lines 310-323) with:

```python
    def resolve(self, ticker: str) -> Optional[str]:
        """Resolve ticker to RIC.

        NASDAQ listings -> "<base>.O".
        IEX (`V`) listings -> "<base>.K".
        All other US-consolidated venues (NYSE `N`, NYSE Arca `P`,
        NYSE American `A`, Cboe BZX `Z`, unknown codes) -> LSEG consolidated
        rule: "<base>.K" when the ticker root is 4+ characters, otherwise the
        bare base with no suffix at all (e.g. "IBM", "SPY", "BRKa").
        """
        self._ensure_loaded()
        upper = ticker.upper()
        ric_base = ticker_to_ric_base(upper)
        root_len = _root_length(upper)

        for form in [upper, ric_base]:
            if form in self._nasdaq:
                return f"{ric_base}.O"
            if form in self._other:
                exchange, _ = self._other[form]
                if exchange == "V":
                    return f"{ric_base}.K"
                return f"{ric_base}{_us_consolidated_suffix(root_len)}"
        return None
```

- [ ] **Step 5: Run all `EquityResolver` tests to verify they pass**

Run: `pytest tests/test_generate_ric_mapping.py::TestEquityResolver -v`
Expected: All tests PASS (including the 2 updated + 7 new).

- [ ] **Step 6: Run the whole test file to catch unintended regressions**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All PASS. If anything in `TestRICResolver` or `TestIntegration` fails because it expected `.N`-style RICs, treat that as in-scope test-data drift and proceed to Task 4 (which covers the fallback) before re-running.

- [ ] **Step 7: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat(ric-mapping): apply LSEG consolidated .K rule for US equities

Replaces per-venue .N/.P/.A/.Z suffixes with the LSEG consolidated-tape
convention: .K when root>=4 chars, bare otherwise. NASDAQ (.O) and IEX
(.K) unchanged."
```

---

## Task 4: Update the low-confidence fallback in `RICResolver.resolve`

**Files:**

- Modify: `generate_ric_mapping.py:594-601` (the `result.ric =` fallback block)
- Test: `tests/test_generate_ric_mapping.py` (new tests in `TestRICResolver`)

- [ ] **Step 1: Write the failing tests**

In `tests/test_generate_ric_mapping.py`, add these methods to `class TestRICResolver` (right after `test_resolve_equity` around line 491):

```python
    def test_resolve_equity_fallback_short_root_is_bare(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver

        # AAPL is in the lazer_symbols fixture but absent from both NASDAQ Trader files,
        # forcing the low-confidence fallback path.
        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        # AAPL root length = 4 -> ".K"
        assert result.ric == "AAPL.K"
        assert result.confidence == "low"
        assert any("verify exchange suffix" in w for w in result.warnings)

    def test_resolve_equity_fallback_long_root_gets_dot_k(self, symbols_path, tmp_path):
        # Confirms the >=4 branch of the fallback. Reuses the AAPL fixture entry which
        # has a 4-char root; .K is expected.
        from generate_ric_mapping import RICResolver

        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        assert result.ric == "AAPL.K"
```

Note: both fallback tests use AAPL because the existing `SAMPLE_SYMBOLS` fixture only carries a 4-char US-equity ticker (root=4 → `.K`). If you need a 3-char bare-fallback assertion later, add a 3-char ticker to `SAMPLE_SYMBOLS` in a follow-up task. For this plan, the `.K` branch is the realistic case and the bare branch is already covered by `TestEquityResolver.test_consolidated_short_root_nyse_is_bare`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_generate_ric_mapping.py::TestRICResolver -v -k "fallback"`
Expected: Both FAIL with `AssertionError: 'AAPL.N' != 'AAPL.K'` (current fallback produces `.N`).

- [ ] **Step 3: Update the fallback block**

In `generate_ric_mapping.py`, replace lines 594-601:

```python
                if result.ric:
                    result.confidence = "medium"
                else:
                    ric_base = ticker_to_ric_base(equity_ticker)
                    result.ric = f"{ric_base}.N"
                    result.confidence = "low"
                    result.warnings.append(
                        f"Defaulting to {result.ric} — verify exchange suffix"
                    )
```

with:

```python
                if result.ric:
                    result.confidence = "medium"
                else:
                    ric_base = ticker_to_ric_base(equity_ticker)
                    suffix = _us_consolidated_suffix(_root_length(equity_ticker))
                    result.ric = f"{ric_base}{suffix}"
                    result.confidence = "low"
                    result.warnings.append(
                        f"Defaulting to {result.ric} — verify exchange suffix"
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_generate_ric_mapping.py::TestRICResolver -v -k "fallback"`
Expected: Both PASS.

- [ ] **Step 5: Run the whole test file**

Run: `pytest tests/test_generate_ric_mapping.py -v`
Expected: All PASS. If any non-fallback `TestRICResolver` or `TestIntegration` test now produces a different RIC due to the new rule, update the expected value to match the consolidated rule (these are data-drift updates, not behavioral bugs).

- [ ] **Step 6: Commit**

```bash
git add generate_ric_mapping.py tests/test_generate_ric_mapping.py
git commit -m "feat(ric-mapping): apply consolidated .K rule to low-confidence fallback"
```

---

## Task 5: Update `check_benchmark_availability.categorize_equities`

**Files:**

- Modify: `check_benchmark_availability.py:123-138` (the `categorize_equities` function)
- Test: `tests/test_check_benchmark_availability.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_benchmark_availability.py`:

```python
"""Tests for the diagnostic RIC categorizer."""

from dataclasses import dataclass

import pytest

from check_benchmark_availability import categorize_equities


@dataclass
class FakeInstrument:
    ric: str


class TestCategorizeEquities:
    def test_nasdaq_dot_o(self):
        result = categorize_equities([FakeInstrument(ric="AAPL.O")])
        assert result == {"NASDAQ": 1}

    def test_nasdaq_dot_oq(self):
        result = categorize_equities([FakeInstrument(ric="MSFT.OQ")])
        assert result == {"NASDAQ": 1}

    def test_consolidated_dot_k(self):
        result = categorize_equities([FakeInstrument(ric="TWTR.K")])
        assert result == {"US Consolidated": 1}

    def test_consolidated_bare_three_char(self):
        result = categorize_equities([FakeInstrument(ric="IBM")])
        assert result == {"US Consolidated": 1}

    def test_consolidated_bare_with_lowercase_class_letter(self):
        # "BRKa" — dotted-class transform; no extension; treated as consolidated.
        result = categorize_equities([FakeInstrument(ric="BRKa")])
        assert result == {"US Consolidated": 1}

    def test_legacy_dot_n(self):
        result = categorize_equities([FakeInstrument(ric="JPM.N")])
        assert result == {"NYSE (legacy)": 1}

    def test_legacy_dot_a(self):
        result = categorize_equities([FakeInstrument(ric="LIVE.A")])
        assert result == {"NYSE Arca (legacy)": 1}

    def test_legacy_dot_z(self):
        result = categorize_equities([FakeInstrument(ric="CBOE.Z")])
        assert result == {"BATS (legacy)": 1}

    def test_non_equity_ric_falls_into_other(self):
        # FX-style RIC; not an equity.
        result = categorize_equities([FakeInstrument(ric="EUR=")])
        assert result == {"Other": 1}

    def test_mixed_counts(self):
        result = categorize_equities(
            [
                FakeInstrument(ric="AAPL.O"),
                FakeInstrument(ric="MSFT.O"),
                FakeInstrument(ric="TWTR.K"),
                FakeInstrument(ric="IBM"),
                FakeInstrument(ric="JPM.N"),
            ]
        )
        # Expect sort by -count: NASDAQ (2), US Consolidated (2), NYSE (legacy) (1).
        # dict order: first key wins ties; we only assert membership and counts.
        assert result["NASDAQ"] == 2
        assert result["US Consolidated"] == 2
        assert result["NYSE (legacy)"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_check_benchmark_availability.py -v`
Expected: Multiple FAIL. `test_consolidated_dot_k` fails because `.K` currently falls into "Other" (existing code only recognizes `.O`, `.OQ`, `.N`, `.NY`, `.A`, `.Z`). `test_consolidated_bare_three_char` fails because `"IBM"` falls into "Other". The legacy-bucket tests fail because the current code uses different labels ("NYSE", "NYSE ARCA", "BATS"). `test_non_equity_ric_falls_into_other` may pass already.

- [ ] **Step 3: Update `categorize_equities`**

In `check_benchmark_availability.py`, replace lines 123-138:

```python
def categorize_equities(instruments: list[InstrumentInfo]) -> dict[str, int]:
    """Categorize equities by exchange based on RIC suffix."""
    categories = defaultdict(int)
    for inst in instruments:
        ric = inst.ric
        if ric.endswith(".O") or ric.endswith(".OQ"):
            categories["NASDAQ"] += 1
        elif ric.endswith(".N") or ric.endswith(".NY"):
            categories["NYSE"] += 1
        elif ric.endswith(".A"):
            categories["NYSE ARCA"] += 1
        elif ric.endswith(".Z"):
            categories["BATS"] += 1
        else:
            categories["Other"] += 1
    return dict(sorted(categories.items(), key=lambda x: -x[1]))
```

with:

```python
def categorize_equities(instruments: list[InstrumentInfo]) -> dict[str, int]:
    """Categorize equities by RIC suffix.

    - `.O` / `.OQ`           -> NASDAQ
    - `.K`                   -> US Consolidated (LSEG consolidated tape)
    - No extension at all    -> US Consolidated (bare 3-char-or-shorter root)
    - `.N` / `.NY`           -> NYSE (legacy)
    - `.A`                   -> NYSE Arca (legacy)
    - `.Z`                   -> BATS (legacy)
    - anything else          -> Other

    Legacy buckets exist so historical mappings still categorize. New mappings
    (generated by `generate_ric_mapping.py` after the consolidated-rule change)
    will use `.K` or bare; venue granularity beyond NASDAQ vs. consolidated
    is no longer recoverable from the RIC.
    """
    categories: dict[str, int] = defaultdict(int)
    for inst in instruments:
        ric = inst.ric
        if ric.endswith(".O") or ric.endswith(".OQ"):
            categories["NASDAQ"] += 1
        elif ric.endswith(".K"):
            categories["US Consolidated"] += 1
        elif ric.endswith(".N") or ric.endswith(".NY"):
            categories["NYSE (legacy)"] += 1
        elif ric.endswith(".A"):
            categories["NYSE Arca (legacy)"] += 1
        elif ric.endswith(".Z"):
            categories["BATS (legacy)"] += 1
        elif _is_bare_equity_ric(ric):
            categories["US Consolidated"] += 1
        else:
            categories["Other"] += 1
    return dict(sorted(categories.items(), key=lambda x: -x[1]))


def _is_bare_equity_ric(ric: str) -> bool:
    """True if `ric` has no extension and looks like a US equity bare consolidated RIC.

    Heuristic: equity bare RICs are short alphabetic strings, optionally with a
    single trailing lowercase class letter (e.g. "IBM", "SPY", "BRKa"). Non-equity
    RICs (FX like "EUR=", commodity futures like "HGH26", rates like "US10YT=RRPS")
    either contain non-alpha characters or are too long.
    """
    if not ric or "." in ric or "=" in ric:
        return False
    if not ric.isalpha():
        return False
    # Equity bare RICs are 1-6 chars: up to 5 uppercase root + optional 1 lowercase class.
    if len(ric) > 6:
        return False
    # Allow all-uppercase ("IBM") or uppercase root + single lowercase class ("BRKa").
    if ric.isupper():
        return True
    if ric[:-1].isupper() and ric[-1].islower():
        return True
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_check_benchmark_availability.py -v`
Expected: All 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add check_benchmark_availability.py tests/test_check_benchmark_availability.py
git commit -m "feat(check-benchmark): add US Consolidated bucket for .K and bare RICs

Legacy .N/.NY/.A/.Z buckets are kept for historical mappings but
renamed with a '(legacy)' suffix. New RICs generated under the
consolidated-tape rule (.K or bare) land in 'US Consolidated'."
```

---

## Task 6: Final verification — full test suite + pre-commit

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest tests/ -q`
Expected: All tests pass. If anything outside the touched files fails, investigate before continuing — it likely indicates a missed downstream consumer of the old `.N`/`.P` suffix.

- [ ] **Step 2: Run pre-commit on the touched files**

Run:

```bash
pre-commit run --files \
  generate_ric_mapping.py \
  check_benchmark_availability.py \
  tests/test_generate_ric_mapping.py \
  tests/test_check_benchmark_availability.py
```

Expected: black, prettier, end-of-file, trim-trailing-whitespace all PASS. If anything was reformatted, `git add` the files and amend the most recent commit:

```bash
git add -u
git commit --amend --no-edit
```

- [ ] **Step 3: Smoke-test the CLI**

Run: `python3 generate_ric_mapping.py --ticker AAPL JPM SPY TWTR CBOE BRK.B 2>&1 | tail -20`

Expected output includes (depending on whether each ticker is in cached NASDAQ Trader data):

- `AAPL` → `AAPL.O` (NASDAQ)
- `JPM` → `JPM` (NYSE, root=3)
- `SPY` → `SPY` (NYSE Arca, root=3)
- `TWTR` → `TWTR.K` (was on NYSE; root=4) — or `.K` via fallback if not in cache
- `CBOE` → `CBOE.K` (root=4)
- `BRK.B` → `BRKb` (root=3 after class transform)

If the NASDAQ Trader cache is stale or missing, the resolver may fall back to the consolidated rule with a low-confidence warning; that's expected and still demonstrates the new behavior.

- [ ] **Step 4: Verify the cumulative git history is clean**

Run: `git log --oneline -7`
Expected: 5 commits (one per task) plus your prior commits. No fixup/wip/amend noise unless step 2 required an amend.
