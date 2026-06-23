# Overnight Candidate Identification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a ranked CSV of US equity tickers (with their volume profile) to inform BlueOcean which feeds are good overnight candidates, by extracting candidates from `lazer_test.json`, running the existing `volume_profile.py`, and ranking the result.

**Architecture:** Two new thin, pure-function CLI scripts bracket the existing volume engine. `extract_overnight_candidates.py` reads `lazer_test.json` and emits a ticker list + metadata side-file. `volume_profile.py` (unchanged) measures per-session volume. `rank_overnight_candidates.py` joins volume metrics with the metadata and emits the final ranked CSV. All decision logic stays out of the volume engine.

**Tech Stack:** Python 3, `pandas` (already a dependency via `volume_profile.py`), `pytest`, `argparse`, stdlib `json`/`csv`.

---

## File Structure

| File                                         | Responsibility                                                                                                |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `extract_overnight_candidates.py`            | NEW. Read `lazer_test.json`, select candidate `Equity.US.*` feeds, write ticker list + meta CSV.              |
| `rank_overnight_candidates.py`               | NEW. Join `volume_profile.py` output with meta, sort by after-hours dollar volume, write final CSV + summary. |
| `tests/test_extract_overnight_candidates.py` | NEW. Unit tests for candidate selection, ticker parsing, overnight-session detection.                         |
| `tests/test_rank_overnight_candidates.py`    | NEW. Unit tests for join/rank, resolved/unresolved split, bool coercion.                                      |
| `volume_profile.py`                          | EXISTING. Reused unchanged.                                                                                   |
| `CLAUDE.md`                                  | MODIFY. Register the two new scripts in the Scripts table.                                                    |
| `.gitignore`                                 | MODIFY. Ignore the generated data artifacts.                                                                  |

Generated (not committed): `overnight_candidates_tickers.txt`, `overnight_candidates_meta.csv`, `overnight_candidates_for_blueocean.csv`, `output_csv/volume_profile_2026-06-11.csv`.

**Conventions to follow** (from existing scripts like `generate_price_list.py`): top-level module imported directly in tests (`from extract_overnight_candidates import ...`); tests run from repo root with `python3 -m pytest`; pure functions separated from `main()`; argparse with sensible defaults; progress/summary printed to `stderr`.

---

## Task 1: Candidate extraction script

**Files:**

- Create: `extract_overnight_candidates.py`
- Test: `tests/test_extract_overnight_candidates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_overnight_candidates.py`:

```python
"""Tests for extract_overnight_candidates.py."""

import csv

from extract_overnight_candidates import (
    build_candidates,
    extract_ticker,
    has_overnight_session,
    is_candidate,
    write_meta,
    write_tickers,
)


def _feed(symbol, state, sessions):
    """Build a minimal feed dict with the given session labels."""
    return {
        "symbol": symbol,
        "state": state,
        "feedId": 100,
        "marketSchedules": [{"session": s} for s in sessions],
    }


class TestHasOvernightSession:
    def test_true_when_overnight_present(self):
        feed = _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"])
        assert has_overnight_session(feed) is True

    def test_false_when_absent(self):
        feed = _feed("Equity.US.A/USD", "STABLE", ["REGULAR"])
        assert has_overnight_session(feed) is False

    def test_false_when_no_schedules(self):
        assert has_overnight_session({"marketSchedules": []}) is False


class TestExtractTicker:
    def test_simple(self):
        assert extract_ticker("Equity.US.AAPL/USD") == "AAPL"

    def test_dotted(self):
        assert extract_ticker("Equity.US.BRK.B/USD") == "BRK.B"


class TestIsCandidate:
    def test_stable_no_overnight_included(self):
        assert is_candidate(_feed("Equity.US.A/USD", "STABLE", ["REGULAR"])) is True

    def test_stable_with_overnight_excluded(self):
        feed = _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is False

    def test_coming_soon_no_overnight_included(self):
        feed = _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR"])
        assert is_candidate(feed) is True

    def test_coming_soon_with_overnight_included(self):
        feed = _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is True

    def test_inactive_excluded(self):
        feed = _feed("Equity.US.DEAD/USD", "INACTIVE", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is False

    def test_non_us_equity_excluded(self):
        assert is_candidate(_feed("Crypto.BTC/USD", "STABLE", ["REGULAR"])) is False


class TestBuildCandidates:
    def test_rows_and_flag(self):
        feeds = [
            _feed("Equity.US.A/USD", "STABLE", ["REGULAR"]),
            _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"]),
            _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR", "OVER_NIGHT"]),
            _feed("Crypto.BTC/USD", "STABLE", ["REGULAR"]),
        ]
        rows = build_candidates(feeds)
        tickers = [r["ticker"] for r in rows]
        assert tickers == ["A", "NEW"]  # AAPL (stable+overnight) and BTC excluded; sorted
        by_ticker = {r["ticker"]: r for r in rows}
        assert by_ticker["A"]["overnight_configured"] is False
        assert by_ticker["NEW"]["overnight_configured"] is True
        assert by_ticker["NEW"]["state"] == "COMING_SOON"


class TestWriters:
    def test_write_tickers_one_per_line(self, tmp_path):
        rows = [{"ticker": "A"}, {"ticker": "NEW"}]
        path = tmp_path / "t.txt"
        write_tickers(rows, path)
        assert path.read_text().splitlines() == ["A", "NEW"]

    def test_write_meta_roundtrip(self, tmp_path):
        rows = [
            {"ticker": "A", "feedId": 1, "state": "STABLE", "overnight_configured": False},
        ]
        path = tmp_path / "m.csv"
        write_meta(rows, path)
        with open(path) as f:
            got = list(csv.DictReader(f))
        assert got[0]["ticker"] == "A"
        assert got[0]["overnight_configured"] == "False"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_extract_overnight_candidates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'extract_overnight_candidates'`.

- [ ] **Step 3: Write the implementation**

Create `extract_overnight_candidates.py`:

```python
#!/usr/bin/env python3
"""Extract US equity overnight candidates from a Lazer config.

Selects Equity.US.* feeds that are STABLE-without-overnight or COMING_SOON
(with or without overnight), writing a ticker list for volume_profile.py and a
metadata side-file (ticker, feedId, state, overnight_configured) for ranking.

See docs/superpowers/specs/2026-06-12-overnight-candidates-design.md.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

US_EQUITY_PREFIX = "Equity.US."
OVERNIGHT_SESSION = "OVER_NIGHT"
META_FIELDS = ["ticker", "feedId", "state", "overnight_configured"]


def has_overnight_session(feed: dict) -> bool:
    """True iff any market schedule entry is an OVER_NIGHT session."""
    return any(
        ms.get("session") == OVERNIGHT_SESSION
        for ms in feed.get("marketSchedules", [])
    )


def extract_ticker(symbol: str) -> str:
    """'Equity.US.AAPL/USD' -> 'AAPL' (handles dotted tickers like BRK.B)."""
    return symbol[len(US_EQUITY_PREFIX):].split("/")[0]


def is_candidate(feed: dict) -> bool:
    """Include COMING_SOON (any), or STABLE without an overnight session."""
    if not feed.get("symbol", "").startswith(US_EQUITY_PREFIX):
        return False
    state = feed.get("state")
    if state == "COMING_SOON":
        return True
    if state == "STABLE" and not has_overnight_session(feed):
        return True
    return False


def build_candidates(feeds: list[dict]) -> list[dict]:
    """Return candidate rows sorted by ticker."""
    rows = [
        {
            "ticker": extract_ticker(f["symbol"]),
            "feedId": f["feedId"],
            "state": f["state"],
            "overnight_configured": has_overnight_session(f),
        }
        for f in feeds
        if is_candidate(f)
    ]
    rows.sort(key=lambda r: r["ticker"])
    return rows


def load_feeds(config_path: Path) -> list[dict]:
    with open(config_path) as f:
        return json.load(f)["feeds"]


def write_tickers(rows: list[dict], path: Path) -> None:
    path.write_text("\n".join(r["ticker"] for r in rows) + "\n")


def write_meta(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=META_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in META_FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("lazer_test.json"))
    parser.add_argument(
        "--tickers-out", type=Path, default=Path("overnight_candidates_tickers.txt")
    )
    parser.add_argument(
        "--meta-out", type=Path, default=Path("overnight_candidates_meta.csv")
    )
    args = parser.parse_args()

    feeds = load_feeds(args.config)
    rows = build_candidates(feeds)
    write_tickers(rows, args.tickers_out)
    write_meta(rows, args.meta_out)

    net_new = sum(1 for r in rows if not r["overnight_configured"])
    configured = len(rows) - net_new
    print(
        f"{len(rows)} candidates "
        f"({net_new} net-new, {configured} already-configured) "
        f"-> {args.tickers_out}, {args.meta_out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_extract_overnight_candidates.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Smoke-test against the real config**

Run: `python3 extract_overnight_candidates.py`
Expected stderr: `872 candidates (675 net-new, 197 already-configured) -> overnight_candidates_tickers.txt, overnight_candidates_meta.csv`

- [ ] **Step 6: Commit**

```bash
git add extract_overnight_candidates.py tests/test_extract_overnight_candidates.py
git commit -m "feat: extract US equity overnight candidates from Lazer config"
```

---

## Task 2: Ranking / assembly script

**Files:**

- Create: `rank_overnight_candidates.py`
- Test: `tests/test_rank_overnight_candidates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rank_overnight_candidates.py`:

```python
"""Tests for rank_overnight_candidates.py."""

import pandas as pd

from rank_overnight_candidates import (
    OUTPUT_COLUMNS,
    coerce_bool,
    join_and_rank,
    split_resolved,
)


def _meta():
    return pd.DataFrame(
        [
            {"ticker": "AAA", "feedId": 1, "state": "STABLE", "overnight_configured": False},
            {"ticker": "BBB", "feedId": 2, "state": "COMING_SOON", "overnight_configured": True},
            {"ticker": "CCC", "feedId": 3, "state": "STABLE", "overnight_configured": False},
        ]
    )


def _volume():
    # CCC has no row -> unresolved. BBB has higher after-hours dollar vol than AAA.
    return pd.DataFrame(
        [
            {
                "ticker": "AAA", "liquidity_tier": "MEDIUM", "total_dollar_vol": 9.0,
                "regular_dollar_vol": 8.0, "after_hours_dollar_vol": 1.0,
                "after_hours_pct": 11.0, "pre_market_dollar_vol": 0.0,
            },
            {
                "ticker": "BBB", "liquidity_tier": "HIGH", "total_dollar_vol": 100.0,
                "regular_dollar_vol": 90.0, "after_hours_dollar_vol": 5.0,
                "after_hours_pct": 5.0, "pre_market_dollar_vol": 5.0,
            },
        ]
    )


class TestCoerceBool:
    def test_string_false(self):
        assert coerce_bool("False") is False

    def test_string_true(self):
        assert coerce_bool("True") is True

    def test_real_bool(self):
        assert coerce_bool(True) is True


class TestSplitResolved:
    def test_unresolved_listed(self):
        resolved, unresolved = split_resolved(_volume(), _meta())
        assert unresolved == ["CCC"]
        assert set(resolved["ticker"]) == {"AAA", "BBB"}


class TestJoinAndRank:
    def test_sorted_desc_by_after_hours_and_columns(self):
        ranked = join_and_rank(_volume(), _meta())
        assert list(ranked["ticker"]) == ["BBB", "AAA"]  # 5.0 > 1.0
        assert list(ranked.columns) == OUTPUT_COLUMNS
        assert ranked.iloc[0]["feedId"] == 2
        assert ranked.iloc[0]["overnight_configured"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rank_overnight_candidates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rank_overnight_candidates'`.

- [ ] **Step 3: Write the implementation**

Create `rank_overnight_candidates.py`:

```python
#!/usr/bin/env python3
"""Rank overnight candidates by volume profile for BlueOcean.

Joins volume_profile.py output with the candidate metadata from
extract_overnight_candidates.py, sorts descending by after-hours dollar volume,
and writes a ranked CSV. No tiering or cutoffs -- raw metrics for a human to
draw the line. Candidates with no volume data are reported as unresolved.

See docs/superpowers/specs/2026-06-12-overnight-candidates-design.md.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

OUTPUT_COLUMNS = [
    "ticker",
    "feedId",
    "state",
    "overnight_configured",
    "liquidity_tier",
    "total_dollar_vol",
    "regular_dollar_vol",
    "after_hours_dollar_vol",
    "after_hours_pct",
    "pre_market_dollar_vol",
]


def coerce_bool(value) -> bool:
    """Robustly read a bool that may have round-tripped through CSV as a string."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def load_meta(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["overnight_configured"] = df["overnight_configured"].map(coerce_bool)
    return df


def split_resolved(volume: pd.DataFrame, meta: pd.DataFrame):
    """Return (resolved_meta, sorted_unresolved_tickers)."""
    vol_tickers = set(volume["ticker"])
    resolved = meta[meta["ticker"].isin(vol_tickers)]
    unresolved = sorted(meta.loc[~meta["ticker"].isin(vol_tickers), "ticker"])
    return resolved, unresolved


def join_and_rank(volume: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Inner-join on ticker, sort desc by after-hours dollar volume."""
    merged = meta.merge(volume, on="ticker", how="inner")
    merged = merged.sort_values(
        "after_hours_dollar_vol", ascending=False, na_position="last"
    ).reset_index(drop=True)
    return merged[OUTPUT_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--volume-csv", type=Path, required=True,
        help="Output CSV from volume_profile.py",
    )
    parser.add_argument(
        "--meta", type=Path, default=Path("overnight_candidates_meta.csv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("overnight_candidates_for_blueocean.csv"),
    )
    args = parser.parse_args()

    volume = pd.read_csv(args.volume_csv)
    if volume.empty:
        print(f"ERROR: {args.volume_csv} has no rows.", file=sys.stderr)
        sys.exit(1)

    meta = load_meta(args.meta)
    resolved, unresolved = split_resolved(volume, meta)
    ranked = join_and_rank(volume, meta)
    ranked.to_csv(args.output, index=False)

    net_new = int((~resolved["overnight_configured"]).sum())
    configured = len(resolved) - net_new
    print(
        f"Ranked {len(ranked)} candidates "
        f"({net_new} net-new, {configured} already-configured) -> {args.output}",
        file=sys.stderr,
    )
    print(f"Unresolved (no volume data): {len(unresolved)}", file=sys.stderr)
    if unresolved:
        print("  " + ", ".join(unresolved), file=sys.stderr)
    print("Top 10 by after-hours dollar volume:", file=sys.stderr)
    for _, row in ranked.head(10).iterrows():
        print(
            f"  {row['ticker']:8s} ${row['after_hours_dollar_vol']:>14,.0f} "
            f"[{row['liquidity_tier']}] "
            f"{'configured' if row['overnight_configured'] else 'net-new'}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rank_overnight_candidates.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add rank_overnight_candidates.py tests/test_rank_overnight_candidates.py
git commit -m "feat: rank overnight candidates by volume profile"
```

---

## Task 3: End-to-end run + register scripts

**Files:**

- Modify: `.gitignore`
- Modify: `CLAUDE.md` (Scripts table)

- [ ] **Step 1: Run the full pipeline against real data**

```bash
python3 extract_overnight_candidates.py
python3 volume_profile.py --ticker-file overnight_candidates_tickers.txt --date 2026-06-11
python3 rank_overnight_candidates.py --volume-csv output_csv/volume_profile_2026-06-11.csv
```

Expected: `overnight_candidates_for_blueocean.csv` is created; stderr shows net-new/already-configured counts, an unresolved list, and a Top-10 after-hours table. (If 2026-06-11 returns no Datascope data — holiday/ingestion gap — retry with the previous trading day, e.g. `--date 2026-06-10`, threading the matching filename into the rank command.)

- [ ] **Step 2: Eyeball the deliverable**

Run: `head -20 overnight_candidates_for_blueocean.csv`
Expected: header is exactly `ticker,feedId,state,overnight_configured,liquidity_tier,total_dollar_vol,regular_dollar_vol,after_hours_dollar_vol,after_hours_pct,pre_market_dollar_vol`, rows sorted by `after_hours_dollar_vol` descending.

- [ ] **Step 3: Ignore generated artifacts**

Add to `.gitignore`:

```
overnight_candidates_tickers.txt
overnight_candidates_meta.csv
overnight_candidates_for_blueocean.csv
```

- [ ] **Step 4: Register the scripts in CLAUDE.md**

In `CLAUDE.md`, in the `## Scripts` table, add these two rows after the `volume_profile.py` row:

```markdown
| `extract_overnight_candidates.py` | Extract US equity overnight candidates (Equity.US.\*) from a Lazer config | `python3 extract_overnight_candidates.py --config lazer_test.json` | - |
| `rank_overnight_candidates.py` | Rank overnight candidates by volume profile (joins volume_profile.py output) for BlueOcean | `python3 rank_overnight_candidates.py --volume-csv output_csv/volume_profile_2026-06-11.csv` | - |
```

- [ ] **Step 5: Run pre-commit on changed files**

Run: `pre-commit run --files extract_overnight_candidates.py rank_overnight_candidates.py tests/test_extract_overnight_candidates.py tests/test_rank_overnight_candidates.py CLAUDE.md .gitignore`
Expected: all hooks Pass (black may reformat — re-stage and re-run if so).

- [ ] **Step 6: Commit**

```bash
git add .gitignore CLAUDE.md
git commit -m "chore: register overnight-candidate scripts, ignore generated outputs"
```

---

## Self-Review

- **Spec coverage:**
  - Universe (872, STABLE-no-overnight + all COMING_SOON) → Task 1 `is_candidate` + tests.
  - `overnight_configured` flag (net-new vs already-configured) → Task 1 `build_candidates`, carried through Task 2 `OUTPUT_COLUMNS`.
  - Reuse `volume_profile.py` unchanged → Task 3 Step 1.
  - Rank desc by after-hours dollar volume, raw metrics, no tiering → Task 2 `join_and_rank`.
  - Unresolved reported, not dropped → Task 2 `split_resolved` + `main` summary.
  - Empty/failed volume run surfaced → Task 2 `main` empty-check.
  - Output columns match spec exactly → `OUTPUT_COLUMNS`.
- **Placeholder scan:** none — every code/test step contains full content.
- **Type consistency:** `META_FIELDS` (extract) == meta columns read by `load_meta`; `overnight_configured` written as bool, read via `coerce_bool`; `OUTPUT_COLUMNS` references only columns present after the meta⋈volume join.

```

```
