# generate_short_name_candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only script that proposes shorter display names for HK/JP/KR/CN
equity feeds — HK/KR sourced from Yahoo Finance's `shortName` (exchanges' own official
abbreviation), JP/CN from stripping trailing corporate-designator words off the existing
description-derived name — and writes them to a CSV for human review. The script never
writes to any Lazer config file.

**Architecture:** One new standalone script, `generate_short_name_candidates.py`, built
from small pure functions plus one network-touching function. It imports
`MARKET_PREFIXES`, `in_scope`, and `derive_name` from the already-shipped
`rename_numeric_feed_names.py` rather than re-deriving that logic. The two proposal
strategies (Yahoo lookup, suffix-stripping) are independent functions so each is
unit-testable without a live network call.

**Tech Stack:** Python 3.12, `yfinance` (already a repo dependency, `requirements.txt:
yfinance>=1.1.0`), stdlib `argparse`/`csv`/`json`/`re`, `pytest` with
`unittest.mock.patch`.

## Global Constraints

- Never write to `lazer-state.json` or any other Lazer config file — this tool has no
  `--apply` flag and no code path that opens a config file for writing.
- Never make a live network call for JP/CN feeds — suffix-stripping is offline-only.
- Reuse `MARKET_PREFIXES`, `in_scope`, `derive_name` from `rename_numeric_feed_names.py`
  rather than duplicating them.
- All `yfinance` calls in tests are mocked via `@patch("yfinance.Ticker")` (see
  `tests/test_isin_resolver.py::TestYFinanceSource` for the established pattern in this
  repo) — no real network access in the test suite.
- Follow existing repo conventions: `#!/usr/bin/env python3` shebang, module docstring
  referencing the design spec, `@dataclass(frozen=True)` for value objects, `Path` for
  file arguments, `str | None`-style type hints (Python 3.12).
- Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash;
  this suite is run standalone: `pytest tests/test_generate_short_name_candidates.py -v`.
- Run `pre-commit run --files <changed files>` before each commit.

---

### Task 1: Exchange-code extraction and corporate-suffix stripping

**Files:**

- Create: `generate_short_name_candidates.py`
- Test: `tests/test_generate_short_name_candidates.py`

**Interfaces:**

- Produces: `extract_exchange_code(symbol: str) -> str` — pulls the numeric exchange
  code out of a symbol like `"Equity.HK.9901/HKD"` → `"9901"`. Works regardless of
  whether `metadata.name` still holds the numeric code or has already been renamed to
  the full company name, since it reads `symbol`, which is never modified by
  `rename_numeric_feed_names.py`.
- Produces: `SUFFIX_WORDS: frozenset[str]` — the corporate-designator vocabulary.
- Produces: `strip_corporate_suffix(name: str) -> str` — iteratively removes trailing
  designator words/`&`; returns the input unchanged if nothing matched.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_generate_short_name_candidates.py`:

```python
"""Tests for generate_short_name_candidates.py."""

from generate_short_name_candidates import (
    extract_exchange_code,
    strip_corporate_suffix,
)


class TestExtractExchangeCode:
    def test_hk_symbol(self):
        assert extract_exchange_code("Equity.HK.9901/HKD") == "9901"

    def test_kr_symbol(self):
        assert extract_exchange_code("Equity.KR.005380/KRW") == "005380"

    def test_cn_symbol_with_letter_suffix(self):
        assert extract_exchange_code("Equity.JP.285A/JPY") == "285A"


class TestStripCorporateSuffix:
    def test_single_suffix_corp(self):
        assert strip_corporate_suffix("TAISEI CORP") == "TAISEI"

    def test_single_suffix_corporation(self):
        assert (
            strip_corporate_suffix("TOYOTA MOTOR CORPORATION") == "TOYOTA MOTOR"
        )

    def test_co_ltd_strips_both_words(self):
        assert strip_corporate_suffix("KWEICHOW MOUTAI CO LTD") == "KWEICHOW MOUTAI"

    def test_holdings_inc_strips_both_words(self):
        assert (
            strip_corporate_suffix("BANDAI NAMCO HOLDINGS INC") == "BANDAI NAMCO"
        )

    def test_plc_and_holdings_strip_iteratively(self):
        assert strip_corporate_suffix("HSBC HOLDINGS PLC") == "HSBC"

    def test_kabushiki_kaisha_strips_both_words(self):
        assert (
            strip_corporate_suffix("NIPPON YUSEN KABUSHIKI KAISHA")
            == "NIPPON YUSEN"
        )

    def test_dangling_ampersand_is_also_stripped(self):
        assert strip_corporate_suffix("MITSUI & CO") == "MITSUI"

    def test_meaningful_ampersand_is_preserved(self):
        assert (
            strip_corporate_suffix("SEVEN & I HOLDINGS CO LTD") == "SEVEN & I"
        )

    def test_group_is_never_stripped(self):
        assert strip_corporate_suffix("RAKUTEN GROUP INC") == "RAKUTEN GROUP"
        assert strip_corporate_suffix("SOFTBANK GROUP CORP") == "SOFTBANK GROUP"

    def test_industries_and_heavy_are_never_stripped(self):
        assert (
            strip_corporate_suffix("MITSUBISHI HEAVY INDUSTRIES LTD")
            == "MITSUBISHI HEAVY INDUSTRIES"
        )

    def test_no_match_returns_unchanged(self):
        assert strip_corporate_suffix("SEKISUI HOUSE") == "SEKISUI HOUSE"

    def test_typo_no_space_is_left_unchanged(self):
        assert strip_corporate_suffix("IDEMITSU KOSAN COLTD") == "IDEMITSU KOSAN COLTD"

    def test_never_strips_down_to_nothing(self):
        assert strip_corporate_suffix("CORP") == "CORP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_short_name_candidates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'generate_short_name_candidates'`

- [ ] **Step 3: Write minimal implementation**

Create `generate_short_name_candidates.py`:

```python
#!/usr/bin/env python3
"""Propose shorter display names for HK/JP/KR/CN equity feeds.

HK and KR have official exchange-published English short names, reachable via
Yahoo Finance's `shortName` field (yfinance, already a repo dependency). JP and
CN have no equivalent public standard, so a legal-suffix-stripping heuristic is
applied to the existing description-derived name instead.

This script never writes to any Lazer config file. It writes a review CSV
(default `name_override_candidates.csv`) for a human to curate into the
existing, version-controlled `feed_name_overrides.csv`, which then flows
through `rename_numeric_feed_names.py --apply --name-overrides ...` unchanged.

See docs/superpowers/specs/2026-07-28-short-name-candidates-design.md.
"""

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rename_numeric_feed_names import MARKET_PREFIXES, derive_name, in_scope

SUFFIX_WORDS = frozenset(
    {
        "CORP",
        "CORPORATION",
        "LTD",
        "LIMITED",
        "INC",
        "CO",
        "COMPANY",
        "HOLDINGS",
        "HLDGS",
        "PLC",
        "KAISHA",
        "KABUSHIKI",
    }
)


def extract_exchange_code(symbol: str) -> str:
    """Pull the numeric exchange code out of e.g. 'Equity.HK.9901/HKD' -> '9901'.

    Reads `symbol`, which `rename_numeric_feed_names.py` never modifies, so this
    works whether or not `metadata.name` has already been renamed.
    """
    root = symbol.split("/", 1)[0]
    return root.rsplit(".", 1)[1]


def strip_corporate_suffix(name: str) -> str:
    """Iteratively remove trailing legal-entity words/`&` from `name`.

    Returns `name` unchanged if nothing in the vocabulary matched. Never strips
    a name down to fewer than one token.
    """
    tokens = name.split()
    while len(tokens) > 1:
        last = tokens[-1].rstrip(".,").upper()
        if last in SUFFIX_WORDS or last == "&":
            tokens.pop()
        else:
            break
    return " ".join(tokens)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_short_name_candidates.py -v`
Expected: PASS (all `TestExtractExchangeCode` and `TestStripCorporateSuffix` cases)

- [ ] **Step 5: Commit**

```bash
git add generate_short_name_candidates.py tests/test_generate_short_name_candidates.py
git commit -m "feat: add exchange-code extraction and corporate-suffix stripping"
```

---

### Task 2: Yahoo shortName normalization

**Files:**

- Modify: `generate_short_name_candidates.py`
- Test: `tests/test_generate_short_name_candidates.py`

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces: `normalize_yahoo_name(raw: str) -> str` — splits camelCase word
  boundaries, strips punctuation, collapses whitespace, uppercases.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate_short_name_candidates.py`:

```python
from generate_short_name_candidates import normalize_yahoo_name


class TestNormalizeYahooName:
    def test_already_uppercase_single_word(self):
        assert normalize_yahoo_name("TENCENT") == "TENCENT"

    def test_camel_case_two_words(self):
        assert normalize_yahoo_name("SamsungElec") == "SAMSUNG ELEC"

    def test_camel_case_three_words(self):
        assert normalize_yahoo_name("SamsungHvyInd") == "SAMSUNG HVY IND"

    def test_acronym_then_word_boundary(self):
        assert normalize_yahoo_name("SKTelecom") == "SK TELECOM"

    def test_lowercase_input(self):
        assert normalize_yahoo_name("kakaopay") == "KAKAOPAY"

    def test_already_spaced_title_case(self):
        assert normalize_yahoo_name("Hanwha Ocean") == "HANWHA OCEAN"

    def test_punctuation_replaced_not_glued(self):
        assert normalize_yahoo_name("SAMSUNG SDI CO.,LTD.") == "SAMSUNG SDI CO LTD"

    def test_apostrophe_preserved(self):
        assert normalize_yahoo_name("HENGAN INT'L") == "HENGAN INT'L"

    def test_share_class_hyphen_preserved(self):
        assert normalize_yahoo_name("ZTO EXPRESS-W") == "ZTO EXPRESS-W"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k NormalizeYahooName`
Expected: FAIL with `ImportError: cannot import name 'normalize_yahoo_name'`

- [ ] **Step 3: Write minimal implementation**

Add to `generate_short_name_candidates.py` (after `strip_corporate_suffix`):

```python
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_PUNCTUATION_RE = re.compile(r"[.,]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_yahoo_name(raw: str) -> str:
    """Normalize a Yahoo Finance `shortName` for display consistency.

    Yahoo stores some short names camelCase-merged with no spaces (e.g.
    'HyundaiMtr', 'SKTelecom'); blindly uppercasing those collapses them into
    unreadable blobs ('HYUNDAIMTR'). This inserts a space at camelCase word
    boundaries first, then strips stray punctuation ('CO.,LTD.' -> 'CO LTD',
    not 'COLTD'), before uppercasing.
    """
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", raw)
    spaced = _PUNCTUATION_RE.sub(" ", spaced)
    collapsed = _WHITESPACE_RE.sub(" ", spaced).strip()
    return collapsed.upper()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k NormalizeYahooName`
Expected: PASS (all 9 cases)

- [ ] **Step 5: Commit**

```bash
git add generate_short_name_candidates.py tests/test_generate_short_name_candidates.py
git commit -m "feat: add Yahoo shortName camelCase and punctuation normalization"
```

---

### Task 3: Yahoo shortName lookup strategy

**Files:**

- Modify: `generate_short_name_candidates.py`
- Test: `tests/test_generate_short_name_candidates.py`

**Interfaces:**

- Consumes: `extract_exchange_code` (Task 1), `normalize_yahoo_name` (Task 2).
- Produces: `Candidate` and `SkipReason` frozen dataclasses (fields below).
- Produces: `yahoo_tickers(market: str, code: str) -> list[str]`.
- Produces: `suggest_from_yahoo(feed: dict) -> tuple[Candidate | None, SkipReason | None]`.

```python
@dataclass(frozen=True)
class Candidate:
    feed_id: int
    symbol: str
    current_name: str
    proposed_name: str
    source: str  # "yahoo_shortname" or "suffix_stripped"
    notes: str = ""


@dataclass(frozen=True)
class SkipReason:
    feed_id: int
    symbol: str
    reason: str
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate_short_name_candidates.py`:

```python
from unittest.mock import MagicMock, patch

from generate_short_name_candidates import (
    Candidate,
    SkipReason,
    suggest_from_yahoo,
    yahoo_tickers,
)


def _feed(
    feed_id=100,
    symbol="Equity.HK.0700/HKD",
    name="0700",
):
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "metadata": {
            "asset_type": "equity",
            "name": name,
        },
    }


class TestYahooTickers:
    def test_hk_zero_pads_to_four_digits(self):
        assert yahoo_tickers("HK", "700") == ["0700.HK"]

    def test_hk_already_four_digits(self):
        assert yahoo_tickers("HK", "0005") == ["0005.HK"]

    def test_kr_tries_kospi_then_kosdaq(self):
        assert yahoo_tickers("KR", "005380") == ["005380.KS", "005380.KQ"]


class TestSuggestFromYahoo:
    @patch("yfinance.Ticker")
    def test_kospi_hit_on_first_try(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "HyundaiMtr"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.005380/KRW", name="005380")
        )
        assert skip is None
        assert candidate == Candidate(
            feed_id=100,
            symbol="Equity.KR.005380/KRW",
            current_name="005380",
            proposed_name="HYUNDAI MTR",
            source="yahoo_shortname",
            notes="",
        )
        mock_ticker_cls.assert_called_once_with("005380.KS")

    @patch("yfinance.Ticker")
    def test_kosdaq_fallback_when_kospi_has_no_shortname(self, mock_ticker_cls):
        kospi_miss = MagicMock()
        kospi_miss.info = {}
        kosdaq_hit = MagicMock()
        kosdaq_hit.info = {"shortName": "SomeKosdaqCo"}
        mock_ticker_cls.side_effect = [kospi_miss, kosdaq_hit]

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.377300/KRW", name="377300")
        )
        assert skip is None
        assert candidate.proposed_name == "SOME KOSDAQ CO"
        assert candidate.source == "yahoo_shortname"
        assert mock_ticker_cls.call_args_list[0].args == ("377300.KS",)
        assert mock_ticker_cls.call_args_list[1].args == ("377300.KQ",)

    @patch("yfinance.Ticker")
    def test_no_shortname_on_any_ticker_is_skipped(self, mock_ticker_cls):
        miss = MagicMock()
        miss.info = {}
        mock_ticker_cls.return_value = miss

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.000000/KRW", name="000000")
        )
        assert candidate is None
        assert isinstance(skip, SkipReason)
        assert skip.feed_id == 100

    @patch("yfinance.Ticker")
    def test_network_error_is_skipped_not_raised(self, mock_ticker_cls):
        mock_ticker_cls.side_effect = ConnectionError("network unreachable")

        candidate, skip = suggest_from_yahoo(_feed())
        assert candidate is None
        assert isinstance(skip, SkipReason)

    @patch("yfinance.Ticker")
    def test_result_matching_current_name_is_skipped(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "TENCENT"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.HK.0700/HKD", name="TENCENT")
        )
        assert candidate is None
        assert "matches current name" in skip.reason

    @patch("yfinance.Ticker")
    def test_share_class_suffix_is_flagged_in_notes(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "ZTO EXPRESS-W"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.HK.2057/HKD", name="2057")
        )
        assert skip is None
        assert candidate.proposed_name == "ZTO EXPRESS-W"
        assert candidate.notes == "share_class_suffix_retained"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k "YahooTickers or SuggestFromYahoo"`
Expected: FAIL with `ImportError` for `Candidate`, `SkipReason`, `suggest_from_yahoo`, `yahoo_tickers`

- [ ] **Step 3: Write minimal implementation**

Add to `generate_short_name_candidates.py` (after the normalization block):

```python
_SHARE_CLASS_SUFFIX_RE = re.compile(r"-[A-Z]{1,3}$")


@dataclass(frozen=True)
class Candidate:
    """One proposed shorter name, awaiting human review."""

    feed_id: int
    symbol: str
    current_name: str
    proposed_name: str
    source: str  # "yahoo_shortname" or "suffix_stripped"
    notes: str = ""


@dataclass(frozen=True)
class SkipReason:
    """A feed that produced no candidate, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def yahoo_tickers(market: str, code: str) -> list[str]:
    """Ordered Yahoo Finance ticker candidates to try for a given market/code.

    KR tries KOSPI (.KS) before KOSDAQ (.KQ) since there is no way to tell
    which board a code belongs to without querying.
    """
    if market == "HK":
        return [f"{code.zfill(4)}.HK"]
    if market == "KR":
        return [f"{code}.KS", f"{code}.KQ"]
    raise ValueError(f"unsupported market for Yahoo lookup: {market}")


def _fetch_yahoo_short_name(ticker: str) -> str | None:
    """Return `info['shortName']` for `ticker`, or None on any failure."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except (ValueError, KeyError, AttributeError, ConnectionError, OSError):
        return None
    short_name = info.get("shortName") if info else None
    return short_name or None


def suggest_from_yahoo(feed: dict) -> tuple[Candidate | None, SkipReason | None]:
    """Propose a name for an HK/KR feed from Yahoo Finance's `shortName`."""
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    current_name = str(feed.get("metadata", {}).get("name", ""))
    market = symbol.split(".")[1]
    code = extract_exchange_code(symbol)
    tickers = yahoo_tickers(market, code)

    for ticker in tickers:
        raw_short_name = _fetch_yahoo_short_name(ticker)
        if not raw_short_name:
            continue
        proposed = normalize_yahoo_name(raw_short_name)
        if proposed == current_name:
            return None, SkipReason(
                feed_id, symbol, f"Yahoo shortName matches current name ({ticker})"
            )
        notes = "share_class_suffix_retained" if _SHARE_CLASS_SUFFIX_RE.search(
            proposed
        ) else ""
        return (
            Candidate(feed_id, symbol, current_name, proposed, "yahoo_shortname", notes),
            None,
        )

    return None, SkipReason(
        feed_id, symbol, f"no Yahoo shortName found for tickers {tickers}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k "YahooTickers or SuggestFromYahoo"`
Expected: PASS (all cases)

- [ ] **Step 5: Commit**

```bash
git add generate_short_name_candidates.py tests/test_generate_short_name_candidates.py
git commit -m "feat: add Yahoo shortName lookup strategy for HK/KR feeds"
```

---

### Task 4: Suffix-strip strategy and candidate orchestration

**Files:**

- Modify: `generate_short_name_candidates.py`
- Test: `tests/test_generate_short_name_candidates.py`

**Interfaces:**

- Consumes: `Candidate`, `SkipReason` (Task 3), `strip_corporate_suffix` (Task 1),
  `derive_name`/`in_scope`/`MARKET_PREFIXES` (imported from
  `rename_numeric_feed_names.py`), `suggest_from_yahoo` (Task 3).
- Produces: `suggest_from_suffix_strip(feed: dict) -> tuple[Candidate | None, SkipReason | None]`.
- Produces: `build_candidates(feeds: list[dict], prefixes: tuple[str, ...] = MARKET_PREFIXES) -> tuple[list[Candidate], list[SkipReason]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate_short_name_candidates.py`:

```python
from generate_short_name_candidates import build_candidates, suggest_from_suffix_strip


def _jp_feed(
    feed_id=200,
    symbol="Equity.JP.7203/JPY",
    name="7203",
    description="TOYOTA MOTOR CORPORATION / JAPANESE YEN",
):
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "metadata": {
            "asset_type": "equity",
            "description": description,
            "name": name,
            "quote_currency": "JPY",
        },
    }


class TestSuggestFromSuffixStrip:
    def test_happy_path(self):
        candidate, skip = suggest_from_suffix_strip(_jp_feed())
        assert skip is None
        assert candidate.proposed_name == "TOYOTA MOTOR"
        assert candidate.source == "suffix_stripped"

    def test_no_suffix_matched_is_skipped(self):
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(description="SEKISUI HOUSE / JAPANESE YEN")
        )
        assert candidate is None
        assert "no corporate suffix" in skip.reason

    def test_currency_mismatch_propagates_as_skip(self):
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(description="TOYOTA MOTOR CORP / US DOLLAR")
        )
        assert candidate is None
        assert "does not match expected" in skip.reason

    def test_works_on_already_renamed_feed(self):
        """derive_name reads description, not the current name, so this works
        whether metadata.name is still numeric or already the long name."""
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(name="TOYOTA MOTOR CORPORATION")
        )
        assert skip is None
        assert candidate.current_name == "TOYOTA MOTOR CORPORATION"
        assert candidate.proposed_name == "TOYOTA MOTOR"


class TestBuildCandidates:
    def test_routes_hk_kr_to_yahoo_and_jp_cn_to_suffix_strip(self, monkeypatch):
        import generate_short_name_candidates as module

        calls = []

        def fake_yahoo(feed):
            calls.append(("yahoo", feed["feedId"]))
            return None, SkipReason(feed["feedId"], feed["symbol"], "stub")

        def fake_suffix(feed):
            calls.append(("suffix", feed["feedId"]))
            return None, SkipReason(feed["feedId"], feed["symbol"], "stub")

        monkeypatch.setattr(module, "suggest_from_yahoo", fake_yahoo)
        monkeypatch.setattr(module, "suggest_from_suffix_strip", fake_suffix)

        feeds = [
            _feed(feed_id=1, symbol="Equity.HK.0700/HKD", name="0700"),
            _feed(feed_id=2, symbol="Equity.KR.005380/KRW", name="005380"),
            _jp_feed(feed_id=3),
            _jp_feed(feed_id=4, symbol="Equity.CN.600519/CNY"),
        ]
        module.build_candidates(feeds)
        assert sorted(calls) == [
            ("suffix", 3),
            ("suffix", 4),
            ("yahoo", 1),
            ("yahoo", 2),
        ]

    def test_feed_outside_prefixes_is_never_touched(self, monkeypatch):
        import generate_short_name_candidates as module

        def fail(_feed):
            raise AssertionError("should not be called")

        monkeypatch.setattr(module, "suggest_from_yahoo", fail)
        monkeypatch.setattr(module, "suggest_from_suffix_strip", fail)

        feeds = [_feed(symbol="Equity.US.AAPL/USD", name="AAPL")]
        candidates, skips = module.build_candidates(feeds)
        assert candidates == []
        assert skips == []

    def test_combines_candidates_and_skips(self):
        feeds = [_jp_feed(feed_id=5), _jp_feed(feed_id=6, description="SEKISUI HOUSE / JAPANESE YEN")]
        candidates, skips = build_candidates(feeds)
        assert [c.feed_id for c in candidates] == [5]
        assert [s.feed_id for s in skips] == [6]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k "SuggestFromSuffixStrip or BuildCandidates"`
Expected: FAIL with `ImportError` for `suggest_from_suffix_strip`, `build_candidates`

- [ ] **Step 3: Write minimal implementation**

Add to `generate_short_name_candidates.py` (after `suggest_from_yahoo`):

```python
def suggest_from_suffix_strip(feed: dict) -> tuple[Candidate | None, SkipReason | None]:
    """Propose a name for a JP/CN feed by stripping trailing corporate words
    off the description-derived name. No network call."""
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    current_name = str(feed.get("metadata", {}).get("name", ""))

    base_name, reason = derive_name(feed)
    if base_name is None:
        return None, SkipReason(feed_id, symbol, reason)

    stripped = strip_corporate_suffix(base_name)
    if stripped == base_name:
        return None, SkipReason(feed_id, symbol, "no corporate suffix matched")

    return Candidate(feed_id, symbol, current_name, stripped, "suffix_stripped"), None


def build_candidates(
    feeds: list[dict], prefixes: tuple[str, ...] = MARKET_PREFIXES
) -> tuple[list[Candidate], list[SkipReason]]:
    """Plan name-shortening candidates over every in-scope feed.

    Runs regardless of whether a feed's current `metadata.name` is still
    numeric or already renamed — both strategies derive the base name from
    fields `rename_numeric_feed_names.py` never modifies (`symbol`,
    `description`).
    """
    candidates: list[Candidate] = []
    skips: list[SkipReason] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        market = feed.get("symbol", "").split(".")[1]
        if market in ("HK", "KR"):
            candidate, skip = suggest_from_yahoo(feed)
        elif market in ("JP", "CN"):
            candidate, skip = suggest_from_suffix_strip(feed)
        else:
            continue
        if candidate is not None:
            candidates.append(candidate)
        if skip is not None:
            skips.append(skip)
    return candidates, skips
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k "SuggestFromSuffixStrip or BuildCandidates"`
Expected: PASS (all cases)

- [ ] **Step 5: Commit**

```bash
git add generate_short_name_candidates.py tests/test_generate_short_name_candidates.py
git commit -m "feat: add suffix-strip strategy and candidate orchestration"
```

---

### Task 5: CSV output, console report, and CLI

**Files:**

- Modify: `generate_short_name_candidates.py`
- Test: `tests/test_generate_short_name_candidates.py`

**Interfaces:**

- Consumes: `Candidate`, `SkipReason` (Task 3), `build_candidates` (Task 4).
- Produces: `CANDIDATE_COLUMNS: tuple[str, ...]`, `write_candidates_csv(path: Path,
candidates: list[Candidate]) -> None`, `print_report(candidates: list[Candidate],
skips: list[SkipReason]) -> None`, `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate_short_name_candidates.py`:

```python
import json

from generate_short_name_candidates import main, print_report, write_candidates_csv


class TestWriteCandidatesCsv:
    def test_writes_header_and_rows(self, tmp_path):
        out = tmp_path / "candidates.csv"
        candidates = [
            Candidate(1, "Equity.HK.0700/HKD", "0700", "TENCENT", "yahoo_shortname", ""),
            Candidate(
                2,
                "Equity.JP.7203/JPY",
                "TOYOTA MOTOR CORPORATION",
                "TOYOTA MOTOR",
                "suffix_stripped",
                "",
            ),
        ]
        write_candidates_csv(out, candidates)
        text = out.read_text(encoding="utf-8")
        assert "feed_id,symbol,current_name,proposed_name,source,notes" in text
        assert "TENCENT,yahoo_shortname" in text
        assert "TOYOTA MOTOR,suffix_stripped" in text


class TestPrintReport:
    def test_reports_counts_by_source(self, capsys):
        candidates = [
            Candidate(1, "Equity.HK.0700/HKD", "0700", "TENCENT", "yahoo_shortname", ""),
            Candidate(
                2, "Equity.JP.7203/JPY", "7203", "TOYOTA MOTOR", "suffix_stripped", ""
            ),
        ]
        skips = [SkipReason(3, "Equity.KR.000000/KRW", "no Yahoo shortName found")]
        print_report(candidates, skips)
        out = capsys.readouterr().out
        assert "2 candidate(s)" in out
        assert "1 skip(s)" in out


class TestMain:
    def test_missing_config_returns_error(self, tmp_path, capsys):
        missing = tmp_path / "nope.json"
        code = main(["--config", str(missing)])
        assert code == 1
        assert "not found" in capsys.readouterr().err

    def test_writes_output_csv_from_build_candidates(self, tmp_path, monkeypatch):
        import generate_short_name_candidates as module

        config = tmp_path / "lazer-state.json"
        config.write_text(json.dumps({"feeds": []}), encoding="utf-8")
        output = tmp_path / "out.csv"

        stub_candidates = [
            Candidate(1, "Equity.HK.0700/HKD", "0700", "TENCENT", "yahoo_shortname", "")
        ]
        monkeypatch.setattr(
            module, "build_candidates", lambda feeds, prefixes=None: (stub_candidates, [])
        )

        code = main(["--config", str(config), "--output", str(output)])
        assert code == 0
        assert "TENCENT" in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_short_name_candidates.py -v -k "WriteCandidatesCsv or PrintReport or TestMain"`
Expected: FAIL with `ImportError` for `main`, `print_report`, `write_candidates_csv`

- [ ] **Step 3: Write minimal implementation**

Add to `generate_short_name_candidates.py` (after `build_candidates`):

```python
CANDIDATE_COLUMNS = (
    "feed_id",
    "symbol",
    "current_name",
    "proposed_name",
    "source",
    "notes",
)


def write_candidates_csv(path: Path, candidates: list[Candidate]) -> None:
    """Write the review CSV. Never touches any Lazer config file."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CANDIDATE_COLUMNS)
        for c in candidates:
            writer.writerow(
                [c.feed_id, c.symbol, c.current_name, c.proposed_name, c.source, c.notes]
            )


def print_report(candidates: list[Candidate], skips: list[SkipReason]) -> None:
    if candidates:
        width = max(len(c.symbol) for c in candidates)
        print(f"\nCandidates ({len(candidates)}):")
        for c in candidates:
            note = f"  [{c.notes}]" if c.notes else ""
            print(
                f"  {c.feed_id:5d}  {c.symbol:<{width}}  "
                f"{c.current_name!r} -> {c.proposed_name!r}  [{c.source}]{note}"
            )
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for s in skips:
            print(f"  {s.feed_id:5d}  {s.symbol}  {s.reason}")

    by_source: dict[str, int] = {}
    for c in candidates:
        by_source[c.source] = by_source.get(c.source, 0) + 1
    source_breakdown = ", ".join(f"{n} {src}" for src, n in sorted(by_source.items()))
    print(
        f"\nSummary: {len(candidates)} candidate(s)"
        f"{f' ({source_breakdown})' if source_breakdown else ''}, "
        f"{len(skips)} skip(s)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to the config")
    parser.add_argument(
        "--symbol-prefix",
        action="append",
        dest="symbol_prefixes",
        help=(
            "Symbol namespace to process; repeatable. Defaults to "
            f"{', '.join(MARKET_PREFIXES)}"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("name_override_candidates.csv"),
        help="Where to write the review CSV",
    )
    args = parser.parse_args(argv)

    prefixes = tuple(args.symbol_prefixes) if args.symbol_prefixes else MARKET_PREFIXES

    if not args.config.exists():
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        return 1

    data = json.loads(args.config.read_text(encoding="utf-8"))
    feeds = data["feeds"]
    print(f"Reading {args.config} ({len(feeds)} feeds)...")

    candidates, skips = build_candidates(feeds, prefixes)
    print_report(candidates, skips)
    write_candidates_csv(args.output, candidates)
    print(f"\nWrote {len(candidates)} candidate(s) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_short_name_candidates.py -v`
Expected: PASS — full suite green (all tasks 1-5 combined)

- [ ] **Step 5: Commit**

```bash
git add generate_short_name_candidates.py tests/test_generate_short_name_candidates.py
git commit -m "feat: add CSV output, console report, and CLI for generate_short_name_candidates"
```

---

### Task 6: Documentation and CLAUDE.md Scripts table

**Files:**

- Create: `docs/generate_short_name_candidates.md`
- Modify: `CLAUDE.md` (Scripts table)

**Interfaces:**

- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks — this is the final task.

- [ ] **Step 1: Write the docs file**

Create `docs/generate_short_name_candidates.md`:

````markdown
# Short Name Candidates (generate_short_name_candidates.py)

Proposes shorter display names for Hong Kong, Japan, South Korea and mainland China
equity feeds, for a human to review before adding to `feed_name_overrides.csv`. This
script never writes to any Lazer config file.

HKEX and KRX publish an official English short/abbreviated name per listed company;
Yahoo Finance's `shortName` field reflects this and is reachable via `yfinance`
(already a repo dependency). JPX and SSE/SZSE publish no equivalent, so JP/CN feeds are
handled instead by stripping trailing corporate-designator words (`CORP`, `LTD`, `INC`,
`CO`, `HOLDINGS`, etc.) off the name `rename_numeric_feed_names.py` already derives from
`metadata.description`.

See `docs/superpowers/specs/2026-07-28-short-name-candidates-design.md` for the full
design and the measurements behind it.

## Usage

```bash
python3 generate_short_name_candidates.py --config lazer-state.json

# Write to a specific path
python3 generate_short_name_candidates.py --config lazer-state.json \
    --output name_override_candidates.csv

# Narrow to one market
python3 generate_short_name_candidates.py --config lazer-state.json \
    --symbol-prefix Equity.KR.
```
````

## Arguments

| Argument          | Description                             | Required | Default                                                |
| ----------------- | --------------------------------------- | -------- | ------------------------------------------------------ |
| `--config`        | Path to the Lazer config JSON           | Yes      | —                                                      |
| `--symbol-prefix` | Symbol namespace to process; repeatable | No       | `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.` |
| `--output`        | Where to write the review CSV           | No       | `name_override_candidates.csv`                         |

## Strategies

**HK / KR — Yahoo Finance `shortName`.** Builds a Yahoo ticker from the numeric
exchange code in `symbol` (HK: zero-padded to 4 digits + `.HK`; KR: code + `.KS`,
retrying `.KQ` on a KOSDAQ listing), fetches `shortName`, and normalizes it: inserts a
space at camelCase boundaries (`HyundaiMtr` → `HYUNDAI MTR`), replaces stray punctuation
with spaces (`CO.,LTD.` → `CO LTD`), collapses whitespace, uppercases. Share-class
markers (`-W`, `-S`, `-UW`) are preserved and flagged in `notes` rather than stripped,
since they carry real meaning.

**JP / CN — corporate-suffix stripping.** Works off the same description-derived name
`rename_numeric_feed_names.py` already produces, so it runs identically whether the
feed's current `metadata.name` is still numeric or already renamed. Iteratively removes
trailing words in `{CORP, CORPORATION, LTD, LIMITED, INC, CO, COMPANY, HOLDINGS, HLDGS,
PLC, KAISHA, KABUSHIKI}` plus a dangling `&`. Deliberately never strips `GROUP`,
`INDUSTRIES`, or `HEAVY` — these are conventionally part of how a company is actually
referred to, not legal-entity boilerplate. A feed with no matching suffix produces no
candidate (left for manual handling via `feed_name_overrides.csv`).

## Output

`name_override_candidates.csv` — not committed, a working artifact:

```csv
feed_id,symbol,current_name,proposed_name,source,notes
1610,Equity.HK.0005/HKD,0005,HSBC HOLDINGS,yahoo_shortname,
2080,Equity.JP.7203/JPY,7203,TOYOTA MOTOR,suffix_stripped,
```

Copy the rows you accept into `feed_name_overrides.csv`; they then flow through the
existing `rename_numeric_feed_names.py --apply --name-overrides feed_name_overrides.csv`
path unchanged.

## Tests

```bash
pytest tests/test_generate_short_name_candidates.py -v
```

All `yfinance` calls are mocked — no real network access in the test suite.

```

- [ ] **Step 2: Add the CLAUDE.md Scripts table row**

In `CLAUDE.md`, in the Scripts table, add a row immediately after the
`rename_numeric_feed_names.py` row:

```

| `generate_short_name_candidates.py` | Propose shorter names for HK/JP/KR/CN equities (Yahoo shortName + suffix-stripping) for human review, no config writes | `python3 generate_short_name_candidates.py --config lazer-state.json` | [docs/generate_short_name_candidates.md](docs/generate_short_name_candidates.md) |

````

- [ ] **Step 3: Run pre-commit on the changed files**

Run: `pre-commit run --files generate_short_name_candidates.py tests/test_generate_short_name_candidates.py docs/generate_short_name_candidates.md CLAUDE.md`
Expected: all hooks pass (black, prettier, trailing-whitespace, end-of-file-fixer). Fix
any reformatting the hooks apply, then re-run.

- [ ] **Step 4: Run the full test suite one more time**

Run: `pytest tests/test_generate_short_name_candidates.py -v`
Expected: PASS — full suite green

- [ ] **Step 5: Commit**

```bash
git add docs/generate_short_name_candidates.md CLAUDE.md
git commit -m "docs: add generate_short_name_candidates.py to CLAUDE.md and docs/"
````
