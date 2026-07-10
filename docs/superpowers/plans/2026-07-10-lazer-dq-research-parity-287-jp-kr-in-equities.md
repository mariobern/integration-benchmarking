# JP/KR/IN Equities Parity (research PR #287) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `lazer_dq` to full parity with research PR #287 by adding `jp-equities`, `kr-equities`, and `in-equities` support across the bulk runner, standalone engine, summary tool, tests, and docs.

**Architecture:** Three new equity-market modes are added by mirroring the existing `hk-equities` code paths. The bulk runner (`evaluate_feeds_bulk.py`) gains three local-exchange session windows; the standalone engine (`evaluate_feed_standalone.py`) routes the modes to the shared global-equities benchmark branch and gains three new qualifier filters (applied to all equities modes); `summarize_feeds.py` gains three single-mode asset-class config entries.

**Tech Stack:** Python 3, `zoneinfo`, ClickHouse SQL (string-built queries), pytest.

## Global Constraints

- Use `python3` (not `python`) on this system.
- Timezones for the new markets observe **no DST** — UTC offsets are fixed year-round: JST (Asia/Tokyo) +9, KST (Asia/Seoul) +9, IST (Asia/Kolkata) +5:30.
- New qualifier filters apply to **all** equities modes (true parity with #287), not only the new markets.
- `session_for_mode` is **not** edited — unknown modes default to `REGULAR`, which is correct for RIC resolution.
- All three modes reuse the existing `datascope_global_equities_benchmark_data` table — no new table.
- Run `pre-commit run --files <changed files>` before each commit; hooks: black, prettier, trailing-whitespace, end-of-file-fixer.
- Run tests with `python3 -m pytest` from the repo root.

---

### Task 1: Bulk runner session windows (jp/kr/in)

**Files:**
- Modify: `lazer_dq/evaluate_feeds_bulk.py` (`compute_times_from_mode`, after the `hk-equities` branch ~line 38-42)
- Test: `lazer_dq/tests/test_evaluate_feeds_bulk.py`

**Interfaces:**
- Consumes: `compute_times_from_mode(date: str, mode: str) -> tuple[str, str]` and its inner helper `_local_to_utc(t: str, tz: str) -> str` (already present).
- Produces: `compute_times_from_mode` returns correct `(start_utc, end_utc)` HH:MM:SS strings for `jp-equities`, `kr-equities`, `in-equities`.

- [ ] **Step 1: Write the failing tests**

Add to `lazer_dq/tests/test_evaluate_feeds_bulk.py` after the `test_time_computation_hk_equities_case_insensitive` test (~line 93):

```python
def test_time_computation_jp_equities():
    # JST is fixed UTC+9 (no DST): 09:00 JST -> 00:00 UTC, 10:00 JST -> 01:00 UTC.
    assert compute_times_from_mode("2026-05-04", "jp-equities") == (
        "00:00:00",
        "01:00:00",
    )


def test_time_computation_jp_equities_winter_matches_summer():
    # No DST in Japan — winter date must produce identical UTC times.
    assert compute_times_from_mode("2026-12-15", "jp-equities") == (
        "00:00:00",
        "01:00:00",
    )


def test_time_computation_kr_equities():
    # KST is fixed UTC+9 (no DST): 09:00 KST -> 00:00 UTC, 10:00 KST -> 01:00 UTC.
    assert compute_times_from_mode("2026-05-04", "kr-equities") == (
        "00:00:00",
        "01:00:00",
    )


def test_time_computation_in_equities():
    # IST is fixed UTC+5:30 (no DST): 09:15 IST -> 03:45 UTC, 10:15 IST -> 04:45 UTC.
    assert compute_times_from_mode("2026-05-04", "in-equities") == (
        "03:45:00",
        "04:45:00",
    )


def test_time_computation_in_equities_case_insensitive():
    # mode_lower normalization should accept mixed-case input.
    assert compute_times_from_mode("2026-12-15", "IN-Equities") == (
        "03:45:00",
        "04:45:00",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feeds_bulk.py -k "jp_equities or kr_equities or in_equities" -v`
Expected: FAIL — the new modes fall through to the default NY branch, so the returned UTC times are wrong (e.g. jp returns the 09:30 NY→UTC default, not `00:00:00`).

- [ ] **Step 3: Add the three branches**

In `lazer_dq/evaluate_feeds_bulk.py`, immediately after the existing `hk-equities` early-return block (the `if mode_lower == "hk-equities":` return), add:

```python
    if mode_lower == "jp-equities":
        return (
            _local_to_utc("09:00:00", "Asia/Tokyo"),
            _local_to_utc("10:00:00", "Asia/Tokyo"),
        )

    if mode_lower == "kr-equities":
        return (
            _local_to_utc("09:00:00", "Asia/Seoul"),
            _local_to_utc("10:00:00", "Asia/Seoul"),
        )

    if mode_lower == "in-equities":
        return (
            _local_to_utc("09:15:00", "Asia/Kolkata"),
            _local_to_utc("10:15:00", "Asia/Kolkata"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_evaluate_feeds_bulk.py -v`
Expected: PASS (all bulk tests, including the new five and existing ones).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/evaluate_feeds_bulk.py lazer_dq/tests/test_evaluate_feeds_bulk.py
git add lazer_dq/evaluate_feeds_bulk.py lazer_dq/tests/test_evaluate_feeds_bulk.py
git commit -m "feat(lazer_dq): add jp/kr/in equities session windows to bulk runner"
```

---

### Task 2: Standalone engine — benchmark branch, qualifier filters, help text

**Files:**
- Modify: `lazer_dq/evaluate_feed_standalone.py` (equities benchmark branch tuple ~line 1148; qualifier filter block ~line 1183; `--mode` help ~line 850)
- Test: `lazer_dq/tests/test_benchmark_ric_queries.py`

**Interfaces:**
- Consumes: the module-level `main()` entrypoint exercised via `test_benchmark_ric_queries.py`'s `_run_and_capture(engine, monkeypatch, tmp_path, mode)` helper and `_benchmark_sql(sql_log)` (both already present).
- Produces: for modes `jp-equities`, `kr-equities`, `in-equities`, the engine builds a query against `datascope_global_equities_benchmark_data`; the equities filter (all equities modes) includes `141[IRGCOND]`, `2835[IRGCOND]`, `4575[IRGCOND]`.

- [ ] **Step 1: Write the failing tests**

In `lazer_dq/tests/test_benchmark_ric_queries.py`, add three rows to the `test_benchmark_query_keys_on_ric` parametrize list (after the `hk-equities` row ~line 123):

```python
        ("jp-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("kr-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("in-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
```

Then add a new test after `test_futures_qualifier_filter_broadened` (~line 154):

```python
def test_equities_new_qualifier_filters_present(engine, monkeypatch, tmp_path):
    # PR #287 added three IRGCOND filters to the shared equities branch;
    # they must appear for every equities mode.
    for mode in ("us-equities", "hk-equities", "jp-equities", "kr-equities", "in-equities"):
        sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, mode)
        sql = _benchmark_sql(sql_log)
        assert "'%141[IRGCOND]%'" in sql
        assert "'%2835[IRGCOND]%'" in sql
        assert "'%4575[IRGCOND]%'" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_ric_queries.py -k "keys_on_ric or new_qualifier" -v`
Expected: FAIL — jp/kr/in rows fail because those modes hit no benchmark branch (`benchmark_query` undefined → error → empty df, so `_benchmark_sql` finds no query / wrong table); the qualifier test fails because the three codes are absent.

- [ ] **Step 3: Add the three modes to the equities branch tuple**

In `lazer_dq/evaluate_feed_standalone.py`, change the equities benchmark-branch condition (~line 1148) from:

```python
    elif mode in (
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
        "hk-equities",
    ):
```

to:

```python
    elif mode in (
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
        "hk-equities",
        "jp-equities",
        "kr-equities",
        "in-equities",
    ):
```

- [ ] **Step 4: Add the three new qualifier filters**

In the same equities `benchmark_query` string, locate the filter lines (~1182-1184):

```python
                AND qualifiers NOT LIKE '%102[ODDSALCOND]%'
                AND qualifiers NOT LIKE '%101[IRGSALCOND]%'
                AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
```

Insert the three new filters between the `%101[IRGSALCOND]%` line and the `PD_` match line (matching #287 notebook ordering):

```python
                AND qualifiers NOT LIKE '%102[ODDSALCOND]%'
                AND qualifiers NOT LIKE '%101[IRGSALCOND]%'
                AND qualifiers NOT LIKE '%141[IRGCOND]%'
                AND qualifiers NOT LIKE '%2835[IRGCOND]%'
                AND qualifiers NOT LIKE '%4575[IRGCOND]%'
                AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
```

- [ ] **Step 5: Update the `--mode` help string**

In `lazer_dq/evaluate_feed_standalone.py` (~line 850), change the `--mode` help text to include the new modes. Replace:

```python
        help="Mode (e.g. fx, metals, us-equities, us-equities-pre, us-equities-post, us-equities-overnight, us-equities-on, hk-equities, us-futures, us-treasuries-yield, us-treasuries-price)",
```

with:

```python
        help="Mode (e.g. fx, metals, us-equities, us-equities-pre, us-equities-post, us-equities-overnight, us-equities-on, hk-equities, jp-equities, kr-equities, in-equities, us-futures, us-treasuries-yield, us-treasuries-price)",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_benchmark_ric_queries.py -v`
Expected: PASS (all rows including jp/kr/in and the new qualifier test).

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_benchmark_ric_queries.py
git add lazer_dq/evaluate_feed_standalone.py lazer_dq/tests/test_benchmark_ric_queries.py
git commit -m "feat(lazer_dq): route jp/kr/in equities to global-equities table; add #287 qualifier filters"
```

---

### Task 3: summarize_feeds asset-class entries (jp/kr/in)

**Files:**
- Modify: `lazer_dq/summarize_feeds.py` (`ASSET_CLASS_CONFIG` dict, after the `hk-equities` entry ~line 64)
- Test: `lazer_dq/tests/test_summarize_feeds.py`

**Interfaces:**
- Consumes: the module-level `ASSET_CLASS_CONFIG` dict; `--asset-class` argparse uses `choices=sorted(ASSET_CLASS_CONFIG.keys())`, and the output layout branches on `us-equities` (24-col) vs. all others (6-col single-mode), so new single-mode entries route through the 6-col path automatically.
- Produces: `ASSET_CLASS_CONFIG` contains `jp-equities`, `kr-equities`, `in-equities`, each single-mode, `REGULAR` session, `default_max_ros` 1.0, `default_min_hit` 80.0.

- [ ] **Step 1: Write the failing test**

Add to `lazer_dq/tests/test_summarize_feeds.py` (near the top-level tests, e.g. after the imports/first test):

```python
import pytest

from lazer_dq.summarize_feeds import ASSET_CLASS_CONFIG


@pytest.mark.parametrize("asset_class", ["jp-equities", "kr-equities", "in-equities"])
def test_asset_class_config_has_new_markets(asset_class):
    cfg = ASSET_CLASS_CONFIG[asset_class]
    assert cfg["modes"] == [asset_class]
    assert cfg["sessions"] == {asset_class: "REGULAR"}
    assert cfg["default_max_ros"] == {asset_class: 1.0}
    assert cfg["default_min_hit"] == {asset_class: 80.0}
```

(If `import pytest` / the `summarize_feeds` import already exists at the top of the file, do not duplicate them — add only the test function.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "new_markets" -v`
Expected: FAIL with `KeyError: 'jp-equities'`.

- [ ] **Step 3: Add the three config entries**

In `lazer_dq/summarize_feeds.py`, inside `ASSET_CLASS_CONFIG`, after the `hk-equities` entry (~line 64, before the closing `}` of the dict), add:

```python
    "jp-equities": {
        "modes": ["jp-equities"],
        "sessions": {"jp-equities": "REGULAR"},
        "default_max_ros": {"jp-equities": 1.0},
        "default_min_hit": {"jp-equities": 80.0},
    },
    "kr-equities": {
        "modes": ["kr-equities"],
        "sessions": {"kr-equities": "REGULAR"},
        "default_max_ros": {"kr-equities": 1.0},
        "default_min_hit": {"kr-equities": 80.0},
    },
    "in-equities": {
        "modes": ["in-equities"],
        "sessions": {"in-equities": "REGULAR"},
        "default_max_ros": {"in-equities": 1.0},
        "default_min_hit": {"in-equities": 80.0},
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: PASS (new parametrized test + existing tests still green).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(lazer_dq): add jp/kr/in single-mode asset classes to summarize_feeds"
```

---

### Task 4: Documentation — CLAUDE.md gotchas

**Files:**
- Modify: `CLAUDE.md` (Key Gotchas section — lines ~185, ~186, ~191)

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: gotchas reflecting jp/kr/in support.

- [ ] **Step 1: Update the "Equities qualifier filter" gotcha**

In `CLAUDE.md`, replace the existing bullet (~line 185):

```markdown
- **Equities qualifier filter** — benchmark queries for `us-equities*` and `hk-equities` modes (in `lazer_dq/evaluate_feed_standalone.py`) filter out irregular trade conditions: IRGCOND qualifiers, plus `102[ODDSALCOND]` (odd-lot sales) and `101[IRGSALCOND]` (irregular sales)
```

with:

```markdown
- **Equities qualifier filter** — benchmark queries for `us-equities*`, `hk-equities`, `jp-equities`, `kr-equities`, and `in-equities` modes (in `lazer_dq/evaluate_feed_standalone.py`) share one filter that drops irregular trade conditions: IRGCOND qualifiers (including `141[IRGCOND]`, `2835[IRGCOND]`, `4575[IRGCOND]`), plus `102[ODDSALCOND]` (odd-lot sales) and `101[IRGSALCOND]` (irregular sales). All equities modes reuse `datascope_global_equities_benchmark_data`.
```

- [ ] **Step 2: Add a jp/kr/in windows gotcha**

Immediately after the existing `hk-equities` mode bullet (~line 186), add:

```markdown
- **`jp-equities` / `kr-equities` / `in-equities` modes (lazer_dq)** — foreign-equity first-hour windows for the per-row window in `evaluate_feeds_bulk`, all with no DST: JP `09:00:00–10:00:00 Asia/Tokyo` (UTC+9), KR `09:00:00–10:00:00 Asia/Seoul` (UTC+9), IN `09:15:00–10:15:00 Asia/Kolkata` (UTC+5:30). All three reuse the global-equities benchmark table and resolve their RIC via the `REGULAR` session (like `hk-equities`).
```

- [ ] **Step 3: Update the `summarize_feeds` asset-class gotcha**

In the `summarize_feeds` asset class bullet (~line 191), replace:

```markdown
For HK equities use `--asset-class hk-equities` (1 mode).
```

with:

```markdown
For single-market foreign equities use `--asset-class hk-equities`, `jp-equities`, `kr-equities`, or `in-equities` (each 1 mode).
```

- [ ] **Step 4: Commit**

```bash
pre-commit run --files CLAUDE.md
git add CLAUDE.md
git commit -m "docs: document jp/kr/in equities in lazer_dq gotchas"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full lazer_dq test suite**

Run: `python3 -m pytest lazer_dq/tests/ -v`
Expected: PASS — all tests green, including the new bulk, ric-query, and summarize_feeds tests.

- [ ] **Step 2: Confirm the three modes end-to-end at the CLI arg layer**

Run: `python3 -m lazer_dq.summarize_feeds --help`
Expected: `--asset-class` choices list includes `in-equities`, `jp-equities`, `kr-equities` (alphabetized alongside `hk-equities`, `us-equities`).

Run: `python3 -m lazer_dq.evaluate_feed_standalone --help`
Expected: `--mode` help text lists `jp-equities, kr-equities, in-equities`.

## Self-Review Notes

- **Spec coverage:** Task 1 → change #1 (bulk windows); Task 2 → change #2 (benchmark branch + filters + help); Task 3 → change #3 (summarize_feeds); Task 4 → change #5 (docs). The spec's "tests" change (#4) is folded into Tasks 1–3 (TDD). Non-changes (`session_for_mode`, no new table) are enforced by the plan doing nothing to them.
- **No placeholders:** every code and test block is concrete.
- **Type consistency:** `compute_times_from_mode` / `_local_to_utc` signatures, `ASSET_CLASS_CONFIG` shape, and the test helpers (`_run_and_capture`, `_benchmark_sql`) match the existing codebase exactly.
