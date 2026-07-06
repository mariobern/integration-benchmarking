# Lazer-DQ Research Parity (#285 + #286) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `lazer_dq/evaluate_feed_standalone.py` and `lazer_dq/evaluate_feeds_bulk.py` to parity with research PRs #285 (broader futures qualifier filter) and #286 (RIC-based benchmark queries, UST price mode, `us-equities-on` alias).

**Architecture:** A new pure-stdlib resolver module (`lazer_dq/benchmark_identifiers.py`) maps a mode to a `market_schedules` session and extracts the Datascope RIC from `benchmarkMapping.datascope_ric`. The engine selects `market_schedules` from `feeds_metadata_latest`, resolves the RIC, and every benchmark query keys on `ric = '<resolved>'` instead of `pyth_lazer_id = feed_id`. A `ric is None` guard soft-skips (`sys.exit(2)`) feeds with no mapping.

**Tech Stack:** Python 3.12, pandas, clickhouse-connect, pytest, unittest.mock (no real DB in tests).

## Global Constraints

- **Python interpreter:** `python` is not on PATH — use `python3` or the repo venv (`source venv/bin/activate`). All test/tooling commands below assume the venv is active or `python3 -m` is used.
- **Run tests with:** `python3 -m pytest lazer_dq/tests/ -v` from repo root.
- **Pre-commit before every commit:** `venv/bin/pre-commit run --files <changed files>` (black, prettier, trailing-whitespace, end-of-file). Re-stage and amend if a hook reformats.
- **Scope is `lazer_dq/` only** — do not touch `lib/config.py`, `quick_benchmark.py`, `feed_readiness.py`, or other scripts.
- **Preserve, do not fix, two pre-existing issues:** the overnight qualifier filter's `OR` chain (engine `us-equities-overnight` branch) and the UST-yield branch's `AND price IS NOT NULL`. They are carried verbatim for parity.
- **No `pyth_lazer_id` fallback** — full RIC parity. A missing RIC soft-skips.
- **Exact UST rename** — `us-treasuries` is removed; only `us-treasuries-yield` and `us-treasuries-price` exist.
- **Branch:** work on `feat/lazer-dq-research-parity-285-286` (already created).

---

### Task 1: RIC resolver module

**Files:**

- Create: `lazer_dq/benchmark_identifiers.py`
- Test: `lazer_dq/tests/test_benchmark_identifiers.py`

**Interfaces:**

- Consumes: nothing (pure stdlib).
- Produces:

  - `SESSION_BY_MODE: dict[str, str]`
  - `session_for_mode(mode: str) -> str` — returns the session for a mode, defaulting to `"REGULAR"`.
  - `resolve_benchmark_identifier(market_schedules, session_name: str, identifier_key: str = "datascope_ric") -> str | None` — `market_schedules` may be a `list[dict]`, a JSON `str`, or `None`.

- [ ] **Step 1: Write the failing tests**

Create `lazer_dq/tests/test_benchmark_identifiers.py`:

```python
"""Unit tests for the RIC / benchmark-identifier resolver."""
import json

import pytest

from lazer_dq.benchmark_identifiers import (
    SESSION_BY_MODE,
    resolve_benchmark_identifier,
    session_for_mode,
)


def _schedules(session, identifiers, key="datascope_ric"):
    return [
        {
            "session": session,
            "benchmarkMapping": {key: {"identifiers": identifiers}},
        }
    ]


# ---- session_for_mode ----


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("us-equities", "REGULAR"),
        ("us-equities-pre", "PRE_MARKET"),
        ("us-equities-post", "POST_MARKET"),
        ("us-equities-on", "OVER_NIGHT"),
        ("us-equities-overnight", "OVER_NIGHT"),
        ("fx", "REGULAR"),
        ("metals", "REGULAR"),
        ("us-futures", "REGULAR"),
        ("us-treasuries-yield", "REGULAR"),
        ("us-treasuries-price", "REGULAR"),
        ("something-unknown", "REGULAR"),
    ],
)
def test_session_for_mode(mode, expected):
    assert session_for_mode(mode) == expected


# ---- resolve_benchmark_identifier ----


def test_resolves_single_identifier():
    ms = _schedules("REGULAR", [{"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}])
    assert resolve_benchmark_identifier(ms, "REGULAR") == "AAPL.O"


def test_picks_most_recent_validfrom():
    ms = _schedules(
        "REGULAR",
        [
            {"identifier": "OLD.O", "validFrom": "2020-01-01T00:00:00Z"},
            {"identifier": "NEW.O", "validFrom": "2026-01-01T00:00:00Z"},
        ],
    )
    assert resolve_benchmark_identifier(ms, "REGULAR") == "NEW.O"


def test_overnight_session_isolated_from_regular():
    ms = [
        {"session": "REGULAR", "benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}]}}},
        {"session": "OVER_NIGHT", "benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": "AAPL.BLUE", "validFrom": "1970-01-01T00:00:00Z"}]}}},
    ]
    assert resolve_benchmark_identifier(ms, "OVER_NIGHT") == "AAPL.BLUE"
    assert resolve_benchmark_identifier(ms, "REGULAR") == "AAPL.O"


def test_parses_json_string_input():
    ms = json.dumps(_schedules("REGULAR", [{"identifier": "EUR=", "validFrom": "1970-01-01T00:00:00Z"}]))
    assert resolve_benchmark_identifier(ms, "REGULAR") == "EUR="


def test_missing_session_returns_none():
    ms = _schedules("REGULAR", [{"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}])
    assert resolve_benchmark_identifier(ms, "PRE_MARKET") is None


def test_missing_mapping_returns_none():
    assert resolve_benchmark_identifier([{"session": "REGULAR"}], "REGULAR") is None


def test_empty_identifiers_returns_none():
    ms = _schedules("REGULAR", [])
    assert resolve_benchmark_identifier(ms, "REGULAR") is None


def test_none_input_returns_none():
    assert resolve_benchmark_identifier(None, "REGULAR") is None


def test_invalid_json_string_returns_none():
    assert resolve_benchmark_identifier("{not valid json", "REGULAR") is None


def test_crypto_coinpaprika_not_matched_by_datascope_ric():
    # Crypto feeds carry coinpaprika_symbol, NOT datascope_ric.
    ms = _schedules(
        "REGULAR",
        [{"identifier": "btc-bitcoin", "validFrom": "1970-01-01T00:00:00Z"}],
        key="coinpaprika_symbol",
    )
    assert resolve_benchmark_identifier(ms, "REGULAR") is None  # default key = datascope_ric
    assert resolve_benchmark_identifier(ms, "REGULAR", identifier_key="coinpaprika_symbol") == "btc-bitcoin"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_identifiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazer_dq.benchmark_identifiers'`.

- [ ] **Step 3: Write the resolver module**

Create `lazer_dq/benchmark_identifiers.py`:

```python
"""Resolve the benchmark identifier (Datascope RIC) for a feed/session.

The Lazer config stores per-session benchmark identifiers under
``market_schedules[].benchmarkMapping``. TradFi feeds carry a ``datascope_ric``
(e.g. ``AAPL.O``); crypto feeds instead carry a ``coinpaprika_symbol`` (e.g.
``btc-bitcoin``). This module maps a benchmarking *mode* to the market session
whose identifier we want, and extracts the most recently valid identifier.

Pure stdlib so it is unit-testable without pandas or a database.
"""
import json

# Map a benchmarking mode to the market_schedules session whose identifier we
# query by. Any mode not listed here uses the REGULAR session.
SESSION_BY_MODE = {
    "us-equities": "REGULAR",
    "us-equities-pre": "PRE_MARKET",
    "us-equities-post": "POST_MARKET",
    "us-equities-on": "OVER_NIGHT",
    "us-equities-overnight": "OVER_NIGHT",
}


def session_for_mode(mode):
    """Return the market session name for a mode (default REGULAR)."""
    return SESSION_BY_MODE.get(mode, "REGULAR")


def resolve_benchmark_identifier(market_schedules, session_name, identifier_key="datascope_ric"):
    """Return the identifier string for a session, or None if unavailable.

    - ``market_schedules`` may be a list of session dicts, a JSON string, or None.
    - Finds the session entry whose ``session`` == ``session_name``.
    - Reads ``benchmarkMapping[identifier_key]["identifiers"]`` and returns the
      identifier whose ``validFrom`` is the maximum (most recently valid).
    - Returns None if the input, session, mapping, or identifiers are missing.
    """
    if market_schedules is None:
        return None
    if isinstance(market_schedules, str):
        try:
            market_schedules = json.loads(market_schedules)
        except (ValueError, TypeError):
            return None
    if not isinstance(market_schedules, list):
        return None

    for session in market_schedules:
        if not isinstance(session, dict) or session.get("session") != session_name:
            continue
        mapping = session.get("benchmarkMapping") or {}
        identifiers = (mapping.get(identifier_key) or {}).get("identifiers") or []
        if not identifiers:
            return None
        best = max(identifiers, key=lambda i: i.get("validFrom", ""))
        return best.get("identifier")
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_identifiers.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Pre-commit and commit**

```bash
venv/bin/pre-commit run --files lazer_dq/benchmark_identifiers.py lazer_dq/tests/test_benchmark_identifiers.py
git add lazer_dq/benchmark_identifiers.py lazer_dq/tests/test_benchmark_identifiers.py
git commit -m "feat(lazer_dq): add benchmark identifier / RIC resolver

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire RIC resolution into the engine (metadata query + resolve, queries unchanged)

Resolve the RIC and print it, without yet changing any benchmark query. This keeps the engine fully working (queries still key on `pyth_lazer_id`) while introducing the metadata column and the `ric` / `session_name` values Task 3 will consume.

**Files:**

- Modify: `lazer_dq/evaluate_feed_standalone.py` (init block ~933-935; metadata query ~939-951; metadata try-block ~952-960)
- Modify: `lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py` (mock must supply `market_schedules`)

**Interfaces:**

- Consumes: `session_for_mode`, `resolve_benchmark_identifier` from Task 1.
- Produces: module-scope locals in `main()` — `session_name: str` and `ric: str | None` — available to the benchmark-query block (Task 3).

- [ ] **Step 1: Update the existing regression test's mock to supply `market_schedules`**

In `lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py`, replace the `feeds_metadata_latest` branch of `query_df` (currently returns a df with `feed_id/symbol/exponent/updated_at`) so it also returns a `market_schedules` column. Change the block starting `if "feeds_metadata_latest" in sql:` to:

```python
        if "feeds_metadata_latest" in sql:
            import json as _json

            market_schedules = _json.dumps(
                [
                    {
                        "session": s,
                        "benchmarkMapping": {
                            "datascope_ric": {
                                "identifiers": [
                                    {"identifier": ric, "validFrom": "1970-01-01T00:00:00Z"}
                                ]
                            }
                        },
                    }
                    for s, ric in [
                        ("REGULAR", "AAPL.O"),
                        ("PRE_MARKET", "AAPL.O"),
                        ("POST_MARKET", "AAPL.O"),
                        ("OVER_NIGHT", "AAPL.BLUE"),
                    ]
                ]
            )
            return pd.DataFrame(
                {
                    "feed_id": [123],
                    "symbol": ["Equity.US.AAPL/USD"],
                    "exponent": [-5],
                    "market_schedules": [market_schedules],
                    "updated_at": [pd.Timestamp("2026-05-19 00:00:00")],
                }
            )
```

Also add one assertion to `test_empty_benchmark_exits_2_with_diagnostic`, after the existing `assert "ric=" in out` line:

```python
    assert "RIC:" in out  # resolution line printed
```

- [ ] **Step 2: Run the regression test to verify it still fails cleanly (module not yet wired)**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py -v`
Expected: FAIL on the new `assert "RIC:" in out` (the engine does not print a `RIC:` line yet). Other assertions still pass.

- [ ] **Step 3: Add the import**

In `lazer_dq/evaluate_feed_standalone.py`, after the existing imports (after line 39 `import clickhouse_connect`), add:

```python
from lazer_dq.benchmark_identifiers import resolve_benchmark_identifier, session_for_mode
```

- [ ] **Step 4: Initialize `session_name` alongside the other names**

Find the init block (currently):

```python
    symbol = None
    ticker = None
    ric = None
```

Replace with:

```python
    symbol = None
    ticker = None
    ric = None
    session_name = session_for_mode(mode)
```

- [ ] **Step 5: Add `market_schedules` to the metadata SELECT**

In `feed_metadata_query`, add `market_schedules,` to the column list. The SELECT becomes:

```python
    feed_metadata_query = f"""
        SELECT
            pyth_lazer_id as feed_id,
            symbol,
            exponent,
            market_schedules,
            updated_at
        FROM feeds_metadata_latest
        FINAL
        WHERE pyth_lazer_id = {feed_id}
          AND exponent IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 1
    """
```

- [ ] **Step 6: Resolve the RIC inside the metadata try-block**

Find:

```python
        if not df_feed_metadata.empty:
            symbol = df_feed_metadata["symbol"].iloc[0]
            ticker = symbol.rsplit(".", 1)[-1].split("/")[0]
            print(f"Symbol: {symbol}, Ticker: {ticker}")
```

Replace with:

```python
        if not df_feed_metadata.empty:
            symbol = df_feed_metadata["symbol"].iloc[0]
            ticker = symbol.rsplit(".", 1)[-1].split("/")[0]
            print(f"Symbol: {symbol}, Ticker: {ticker}")

            ric = resolve_benchmark_identifier(
                df_feed_metadata["market_schedules"].iloc[0], session_name
            )
            print(f"Mode: {mode} -> session: {session_name}, RIC: {ric}")
            if ric is None:
                print(f"Warning: no datascope RIC found for session '{session_name}'")
```

- [ ] **Step 7: Run the regression test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py -v`
Expected: PASS — every parametrized mode still exits rc=2 with `No benchmark data available`, and the `RIC:` line is now printed.

- [ ] **Step 8: Pre-commit and commit**

```bash
venv/bin/pre-commit run --files lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py
git add lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_evaluate_feed_standalone_missing_data.py
git commit -m "feat(lazer_dq): resolve datascope RIC from market_schedules in engine

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Rewrite the benchmark-query block (RIC keying + futures filter + UST split + overnight alias)

Replace the entire `if mode == "fx" ...` / `elif ...` benchmark-query chain (currently ~lines 1112–1230) so every branch keys on `ric`, applies the broadened futures filter (PR #285), splits treasuries into `-yield`/`-price`, and matches `us-equities-on`. Add the `ric is None` soft-skip guard at the top of the block.

**Files:**

- Modify: `lazer_dq/evaluate_feed_standalone.py` (benchmark-query block, ~1112–1230)
- Test: `lazer_dq/tests/test_benchmark_ric_queries.py` (new)

**Interfaces:**

- Consumes: `ric`, `session_name`, `feed_id`, `date`, `mode` from `main()` scope (Task 2).
- Produces: `benchmark_query` string keyed on `ric = '{ric}'` for every supported mode; `sys.exit(2)` when `ric is None`.

- [ ] **Step 1: Write the failing tests**

Create `lazer_dq/tests/test_benchmark_ric_queries.py`:

```python
"""Verify the engine builds RIC-keyed benchmark queries per mode.

Drives main() with a single shared mock ClickHouse client that records every
SQL string. Benchmark tables return empty, so the engine exits rc=2 after the
benchmark query is built and captured.
"""
import json
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _metadata_df():
    market_schedules = json.dumps(
        [
            {"session": s, "benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": r, "validFrom": "1970-01-01T00:00:00Z"}]}}}
            for s, r in [("REGULAR", "AAPL.O"), ("PRE_MARKET", "AAPL.O"), ("POST_MARKET", "AAPL.O"), ("OVER_NIGHT", "AAPL.BLUE")]
        ]
    )
    return pd.DataFrame(
        {
            "feed_id": [123],
            "symbol": ["Equity.US.AAPL/USD"],
            "exponent": [-5],
            "market_schedules": [market_schedules],
            "updated_at": [pd.Timestamp("2026-05-19 00:00:00")],
        }
    )


def _run_and_capture(engine, monkeypatch, tmp_path, mode, metadata_df=None, no_ric=False):
    sql_log = []
    md = metadata_df if metadata_df is not None else _metadata_df()

    def query_df(sql, *a, **k):
        sql_log.append(sql)
        if "feeds_metadata_latest" in sql:
            return md
        if "publisher_updates" in sql:
            return pd.DataFrame(
                {
                    "publisher_id": [1],
                    "feed_id": [123],
                    "publisher_price": [10_000_000.0],
                    "publisher_timestamp": [pd.Timestamp("2026-05-19 14:00:00")],
                }
            )
        return pd.DataFrame()  # price_feeds + all benchmark tables empty

    client = MagicMock()
    client.query_df.side_effect = query_df
    monkeypatch.setattr(engine.clickhouse_connect, "get_client", lambda **kw: client)
    monkeypatch.setattr(
        engine.yaml,
        "safe_load",
        lambda _f: {
            "clickhouse": {"host": "x", "user": "x", "password": "x"},
            "lazer_clickhouse_prod": {"host": "x", "user": "x", "password": "x"},
            "analytics_clickhouse": {"host": "x", "user": "x", "password": "x"},
        },
    )
    monkeypatch.setattr(
        sys, "argv",
        [
            "evaluate_feed_standalone", "--feed-id", "123", "--date", "2026-05-19",
            "--mode", mode, "--cluster", "lazer-prod",
            "--start-time", "13:30:00", "--end-time", "20:00:00",
            "--output-path", str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        engine.main()
    return sql_log, exc.value.code


@pytest.fixture
def engine():
    from lazer_dq import evaluate_feed_standalone as e
    return e


def _benchmark_sql(sql_log):
    hits = [s for s in sql_log if "benchmark_data" in s]
    assert hits, "no benchmark query was issued"
    return hits[-1]


@pytest.mark.parametrize(
    "mode,expected_ric,expected_table",
    [
        ("fx", "AAPL.O", "datascope_fx_benchmark_data"),
        ("metals", "AAPL.O", "datascope_fx_benchmark_data"),
        ("us-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("hk-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("us-equities-overnight", "AAPL.BLUE", "datascope_global_equities_benchmark_data"),
        ("us-equities-on", "AAPL.BLUE", "datascope_global_equities_benchmark_data"),
        ("us-futures", "AAPL.O", "datascope_futures_benchmark_data"),
        ("us-treasuries-yield", "AAPL.O", "datascope_us_treasury_benchmark_data"),
        ("us-treasuries-price", "AAPL.O", "datascope_us_treasury_benchmark_data"),
    ],
)
def test_benchmark_query_keys_on_ric(engine, monkeypatch, tmp_path, mode, expected_ric, expected_table):
    sql_log, code = _run_and_capture(engine, monkeypatch, tmp_path, mode)
    assert code == 2
    sql = _benchmark_sql(sql_log)
    assert f"ric = '{expected_ric}'" in sql
    assert expected_table in sql
    assert "pyth_lazer_id = " not in sql


def test_futures_qualifier_filter_broadened(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-futures")
    sql = _benchmark_sql(sql_log)
    assert "'%SBL[OFFBK_TYPE]%'" in sql
    assert "'%SYS[OFFBK_TYPE]%'" in sql
    assert "'%Spread Price|Spread Volume[USER]%'" in sql


def test_treasuries_price_selects_price(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-treasuries-price")
    sql = _benchmark_sql(sql_log)
    assert "price as benchmark_price" in sql
    assert "yield as benchmark_price" not in sql


def test_treasuries_yield_selects_yield(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-treasuries-yield")
    sql = _benchmark_sql(sql_log)
    assert "yield as benchmark_price" in sql


def test_missing_ric_soft_skips(engine, monkeypatch, tmp_path, capsys):
    # market_schedules with only a coinpaprika_symbol -> no datascope_ric.
    md = _metadata_df()
    md.loc[0, "market_schedules"] = json.dumps(
        [{"session": "REGULAR", "benchmarkMapping": {"coinpaprika_symbol": {"identifiers": [{"identifier": "btc-bitcoin", "validFrom": "1970-01-01T00:00:00Z"}]}}}]
    )
    sql_log, code = _run_and_capture(engine, monkeypatch, tmp_path, "fx", metadata_df=md)
    assert code == 2
    out = capsys.readouterr().out
    assert "No datascope RIC configured" in out
    assert not [s for s in sql_log if "benchmark_data" in s]  # never queried benchmark
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_ric_queries.py -v`
Expected: FAIL — e.g. `test_benchmark_query_keys_on_ric[fx-...]` fails because the fx branch still emits `pyth_lazer_id = '123'`; `us-treasuries-yield`/`-price` fail because those modes do not exist yet (no benchmark query built → `no benchmark query was issued`).

- [ ] **Step 3: Replace the benchmark-query block**

In `lazer_dq/evaluate_feed_standalone.py`, replace the whole block from the `# === CELL 11 ===` comment through the end of the `elif mode == "us-treasuries":` query string (the `if mode == "fx" ... elif mode == "us-treasuries":` chain) with:

```python
    # === CELL 11 ===
    # Process benchmark data, keyed on the RIC resolved from market_schedules.
    if ric is None:
        print(
            f"No datascope RIC configured for feed {feed_id} "
            f"(mode={mode}, session={session_name}); skipping analysis."
        )
        sys.exit(2)

    if mode == "fx" or mode == "metals":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price
            FROM datascope_fx_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
            ORDER BY benchmark_timestamp ASC, ric
        """
    elif mode in (
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
        "hk-equities",
    ):
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price,
                qualifiers
            FROM datascope_global_equities_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                qualifiers NOT LIKE '%CON[IRGCOND]%'
                AND qualifiers NOT LIKE '%ODD[IRGCOND]%'
                AND qualifiers NOT LIKE '%378[IRGCOND]%'
                AND qualifiers NOT LIKE '%705[IRGCOND]%'
                AND qualifiers NOT LIKE '%ODT[IRGCOND]%'
                AND qualifiers NOT LIKE '%DAB[IRGCOND]%'
                AND qualifiers NOT LIKE '%2795[IRGCOND]%'
                AND qualifiers NOT LIKE '%2315[IRGCOND]%'
                AND qualifiers NOT LIKE '%4445[IRGCOND]%'
                AND qualifiers NOT LIKE '%132[IRGCOND]%'
                AND qualifiers NOT LIKE '%4385[IRGCOND]%'
                AND qualifiers NOT LIKE '%DAP[IRGCOND]%'
                AND qualifiers NOT LIKE '%102[ODDSALCOND]%'
                AND qualifiers NOT LIKE '%101[IRGSALCOND]%'
                AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
                )
                )
            ORDER BY benchmark_timestamp ASC, ric
        """
    elif mode == "us-equities-overnight" or mode == "us-equities-on":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price,
                qualifiers
            FROM datascope_global_equities_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                    qualifiers NOT LIKE '%CON[IRGCOND]%'
                    OR qualifiers NOT LIKE '%ODD[IRGCOND]%'
                    OR qualifiers NOT LIKE '%378[IRGCOND]%'
                    OR qualifiers NOT LIKE '%2315[IRGCOND]%'
                    OR qualifiers NOT LIKE '%DAP[IRGCOND]%'
                    OR NOT match(qualifiers, 'PD_[A-Za-z0-9_]*'
                    )
                   )
                  )
            ORDER BY benchmark_timestamp ASC, ric
        """
    elif mode == "us-futures":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price
            FROM datascope_futures_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                    qualifiers NOT LIKE '%SBL[OFFBK_TYPE]%'
                    AND qualifiers NOT LIKE '%SYS[OFFBK_TYPE]%'
                    AND qualifiers NOT LIKE '%Spread Price|Spread Volume[USER]%'
                    AND qualifiers NOT LIKE 'Block Trade[USER]%'
                    )
                  )
            ORDER BY benchmark_timestamp ASC, ric
        """
    elif mode == "us-treasuries-yield":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                yield as benchmark_price,
                bid_yield as bid_price,
                ask_yield as ask_price
            FROM datascope_us_treasury_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
            ORDER BY benchmark_timestamp ASC, ric
        """
    elif mode == "us-treasuries-price":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price as bid_price,
                ask_price as ask_price
            FROM datascope_us_treasury_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ric}'
              AND price IS NOT NULL
            ORDER BY benchmark_timestamp ASC, ric
        """
```

Notes:

- The overnight branch's `OR`-chain qualifier filter and the treasuries-yield `AND price IS NOT NULL` are preserved verbatim per the Global Constraints (parity, not a fix).
- The `us-equities-pre` / `us-equities-post` modes stay in the global-equities branch (their RIC differs only by session, which the resolver already handled).

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_ric_queries.py -v`
Expected: PASS (all parametrized modes + filter/UST/None-guard tests).

- [ ] **Step 5: Run the full lazer_dq suite for regressions**

Run: `python3 -m pytest lazer_dq/tests/ -v`
Expected: PASS — including `test_evaluate_feed_standalone_missing_data.py` (still rc=2 with diagnostic).

- [ ] **Step 6: Pre-commit and commit**

```bash
venv/bin/pre-commit run --files lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_benchmark_ric_queries.py
git add lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_benchmark_ric_queries.py
git commit -m "feat(lazer_dq): key benchmark queries on ric; broaden futures filter; split UST; add us-equities-on

Ports research PR #285 (futures qualifiers) and #286 (RIC queries, UST price, us-equities-on).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Overnight alias in session-window + bulk driver, help text, and docs

Complete the `us-equities-on` alias at the two remaining code sites (engine session-window block, bulk driver time computation), update `--mode` help, and update docs.

**Files:**

- Modify: `lazer_dq/evaluate_feed_standalone.py` (session-window block ~126; `--mode` help ~846)
- Modify: `lazer_dq/evaluate_feeds_bulk.py` (`compute_times_from_mode` ~48)
- Modify: `lazer_dq/tests/test_evaluate_feeds_bulk.py` (new time-window assertions)
- Modify: `docs/evaluate_feeds_bulk.md`
- Modify: `CLAUDE.md`

**Interfaces:**

- Consumes: nothing new.
- Produces: `compute_times_from_mode(date, "us-equities-on")` returns the overnight window `("00:00:00", "01:00:00")` on an EDT date.

- [ ] **Step 1: Write the failing bulk-driver tests**

Add to `lazer_dq/tests/test_evaluate_feeds_bulk.py` (after `test_time_computation_us_equities_overnight`):

```python
def test_time_computation_us_equities_on_alias():
    # us-equities-on is an alias for us-equities-overnight (EDT: 20:00 NY -> 00:00 UTC).
    assert compute_times_from_mode("2026-05-04", "us-equities-on") == (
        "00:00:00",
        "01:00:00",
    )


def test_time_computation_us_treasuries_price_default_window():
    # Treasuries modes use the default REGULAR window (EST: 09:30 NY -> 14:30 UTC).
    assert compute_times_from_mode("2026-12-15", "us-treasuries-price") == (
        "14:30:00",
        "15:30:00",
    )
```

- [ ] **Step 2: Run to verify the alias test fails**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feeds_bulk.py::test_time_computation_us_equities_on_alias -v`
Expected: FAIL — `us-equities-on` currently hits the default branch, returning `("14:30:00", "15:30:00")` instead of the overnight window.

- [ ] **Step 3: Add the alias in the bulk driver**

In `lazer_dq/evaluate_feeds_bulk.py`, `compute_times_from_mode`, change:

```python
    elif mode_lower == "us-equities-overnight":
        start_ny, end_ny = "20:00:00", "21:00:00"
```

to:

```python
    elif mode_lower in ("us-equities-overnight", "us-equities-on"):
        start_ny, end_ny = "20:00:00", "21:00:00"
```

- [ ] **Step 4: Add the alias in the engine session-window block**

In `lazer_dq/evaluate_feed_standalone.py`, change:

```python
        elif mode == "us-equities-overnight":
            start_time = time(20, 0, 0)
            end_time = time(4, 0, 0)
            time_label = "US overnight hours (20:00:00-4:00:00 EST)"
```

to:

```python
        elif mode == "us-equities-overnight" or mode == "us-equities-on":
            start_time = time(20, 0, 0)
            end_time = time(4, 0, 0)
            time_label = "US overnight hours (20:00:00-4:00:00 EST)"
```

- [ ] **Step 5: Update the `--mode` help text**

In `lazer_dq/evaluate_feed_standalone.py`, change the `--mode` help string to:

```python
        help="Mode (e.g. fx, metals, us-equities, us-equities-pre, us-equities-post, us-equities-overnight, us-equities-on, hk-equities, us-futures, us-treasuries-yield, us-treasuries-price)",
```

- [ ] **Step 6: Run the bulk-driver tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feeds_bulk.py -v`
Expected: PASS (including the two new tests).

- [ ] **Step 7: Update `docs/evaluate_feeds_bulk.md`**

In the Time Window Resolution table, change the overnight row to cover the alias:

```markdown
| `us-equities-overnight` / `us-equities-on` | 20:00:00–21:00:00 | `America/New_York` |
```

- [ ] **Step 8: Update `CLAUDE.md` gotchas**

In the Key Gotchas list of `CLAUDE.md`, update the two affected bullets to reflect RIC-keyed queries and the treasuries rename. Replace the existing "Equities qualifier filter" bullet's trailing scope so it also notes futures, and add a treasuries-modes note. Concretely, add this bullet after the metals-smoothing bullet:

```markdown
- **`lazer_dq` benchmark queries key on RIC** — `evaluate_feed_standalone.py` resolves the Datascope RIC from `feeds_metadata_latest.market_schedules` (`benchmarkMapping.datascope_ric`, most-recent `validFrom`) via `session_for_mode()` and queries every benchmark table by `ric = '<resolved>'`. A feed with no `datascope_ric` for its session soft-skips (`exit 2`). Crypto feeds carry `coinpaprika_symbol`, not `datascope_ric`, so they skip. Treasuries modes are `us-treasuries-yield` and `us-treasuries-price` (the bare `us-treasuries` mode was removed); futures filter drops `%SBL[OFFBK_TYPE]%`, `%SYS[OFFBK_TYPE]%`, and `%Spread Price|Spread Volume[USER]%` qualifiers.
```

- [ ] **Step 9: Pre-commit and commit**

```bash
venv/bin/pre-commit run --files lazer_dq/evaluate_feed_standalone.py lazer_dq/evaluate_feeds_bulk.py lazer_dq/tests/test_evaluate_feeds_bulk.py docs/evaluate_feeds_bulk.md CLAUDE.md
git add lazer_dq/evaluate_feed_standalone.py lazer_dq/evaluate_feeds_bulk.py lazer_dq/tests/test_evaluate_feeds_bulk.py docs/evaluate_feeds_bulk.md CLAUDE.md
git commit -m "feat(lazer_dq): finish us-equities-on alias; update mode help + docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire lazer_dq test suite**

Run: `python3 -m pytest lazer_dq/tests/ -v`
Expected: PASS — all tests across `test_benchmark_identifiers.py`, `test_benchmark_ric_queries.py`, `test_evaluate_feed_standalone_missing_data.py`, `test_evaluate_feeds_bulk.py`, `test_apply_allowed_to_config.py`, `test_summarize_feeds.py`.

- [ ] **Step 2: Confirm no lingering `pyth_lazer_id` benchmark keys or bare `us-treasuries` mode**

Run:

```bash
grep -n "pyth_lazer_id = " lazer_dq/evaluate_feed_standalone.py || echo "OK: no pyth_lazer_id benchmark keys"
grep -n "\"us-treasuries\"\|'us-treasuries'" lazer_dq/evaluate_feed_standalone.py lazer_dq/evaluate_feeds_bulk.py || echo "OK: bare us-treasuries mode removed"
```

Expected: both print their `OK:` line (the metadata query's `pyth_lazer_id as feed_id` / `WHERE pyth_lazer_id = {feed_id}` are on `feeds_metadata_latest`, which is expected — verify any remaining hits are the metadata query, not a benchmark table).

- [ ] **Step 3: Final pre-commit sweep**

Run: `venv/bin/pre-commit run --all-files`
Expected: all hooks pass (or only reformat unrelated pre-existing files — if so, do not commit those).

---

## Runtime assumption (confirm on first real run)

`feeds_metadata_latest` must expose a `market_schedules` column on `lazer_clickhouse_prod`. The research notebook queries the same cluster for exactly this column, so confidence is high. On the first real `evaluate_feeds_bulk` run, confirm the engine prints a non-null `RIC:` line for a known-mapped feed (e.g. feed 922 / AAPL → `AAPL.O`).

## Self-Review

- **Spec coverage:** A (futures filter) → Task 3 Step 3 futures branch + test. B (UST split, exact rename) → Task 3 (both branches) + Task 4 (help/docs) + Task 5 Step 2 (bare mode removed). C (us-equities-on) → Task 3 (benchmark branch), Task 4 (session-window + bulk driver + help). D (RIC resolution + None-guard) → Task 1 (resolver), Task 2 (wiring), Task 3 (query rewrite + guard). Resolver module + tests → Task 1. Crypto out-of-scope behavior → Task 1 `test_crypto_*` + Task 3 `test_missing_ric_soft_skips`. Docs/CLAUDE.md → Task 4. Verification → Task 5.
- **Placeholder scan:** none — every code and test step contains complete content.
- **Type consistency:** `resolve_benchmark_identifier` / `session_for_mode` signatures identical across Task 1 (definition), Task 2 (import + call), and all tests. `ric` / `session_name` locals defined in Task 2, consumed in Task 3.
