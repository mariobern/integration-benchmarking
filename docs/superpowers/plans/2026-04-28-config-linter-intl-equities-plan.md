# Config Linter — International Equities & Severity-by-State Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine E011/W003 schedule-consistency rules in `lib/config_lint.py` so they group equity feeds by listing prefix (`US`, `JP`, `KR`, …), and split severity by feed state (E011 STABLE-only ERROR, W003 STABLE+COMING_SOON WARNING).

**Architecture:** Add a small symbol helper, then collapse the dual-collection logic in `check_schedules` into a single `group_signatures` dict tagged with feed state. Both rules consume that dict; they differ only by state filter and severity. Futures are sub-grouped by root within their listing prefix and are no longer exempt from W003.

**Tech Stack:** Python 3, pytest, stdlib only (no new deps). Pre-commit (black, prettier) is required before each commit.

**Reference spec:** `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-design.md`

---

## File Structure

| File                                  | Role                                                                   |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `lib/symbol_utils.py` (modify)        | Add `equity_listing_prefix(symbol) -> str` helper.                     |
| `lib/config_lint.py` (modify)         | Refactor `check_schedules` group key, state scope, severity wiring.    |
| `tests/test_symbol_utils.py` (modify) | Tests for the new helper.                                              |
| `tests/test_config_lint.py` (modify)  | New tests for E011/W003 behavior; clarify one existing W003 docstring. |
| `docs/config_linter.md` (modify)      | Update E011/W003 rows + scope notes.                                   |

---

## Task 1: Add `equity_listing_prefix` helper

**Files:**

- Modify: `lib/symbol_utils.py`
- Modify: `tests/test_symbol_utils.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_symbol_utils.py`:

```python
from lib.symbol_utils import equity_listing_prefix


class TestEquityListingPrefix:
    def test_us_equity(self):
        assert equity_listing_prefix("Equity.US.AAPL/USD") == "US"

    def test_jp_equity(self):
        assert equity_listing_prefix("Equity.JP.1305/JPY") == "JP"

    def test_kr_equity(self):
        assert equity_listing_prefix("Equity.KR.000100/KRW") == "KR"

    def test_index_equity(self):
        assert equity_listing_prefix("Equity.Index.TSLA/USD") == "Index"

    def test_us_equity_future(self):
        assert equity_listing_prefix("Equity.US.EMH6/USD") == "US"

    def test_non_equity_crypto(self):
        assert equity_listing_prefix("Crypto.BTC/USD") == ""

    def test_non_equity_fx(self):
        assert equity_listing_prefix("FX.EUR/USD") == ""

    def test_non_equity_commodity(self):
        assert equity_listing_prefix("Commodities.WTIK6/USD") == ""

    def test_malformed_two_segments(self):
        assert equity_listing_prefix("Equity.US") == ""

    def test_malformed_no_dots(self):
        assert equity_listing_prefix("EquityUSAAPL") == ""

    def test_empty_string(self):
        assert equity_listing_prefix("") == ""
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
source venv/bin/activate
pytest tests/test_symbol_utils.py::TestEquityListingPrefix -v
```

Expected: every test in `TestEquityListingPrefix` errors with `ImportError` (cannot import `equity_listing_prefix`).

- [ ] **Step 3: Implement the helper**

Append to `lib/symbol_utils.py` (after `futures_root`):

```python
def equity_listing_prefix(symbol: str) -> str:
    """For 'Equity.<X>.<Y>/<Z>' return '<X>', else ''.

    Examples:
        'Equity.US.AAPL/USD' -> 'US'
        'Equity.JP.1305/JPY' -> 'JP'
        'Equity.Index.TSLA/USD' -> 'Index'
        'Crypto.BTC/USD' -> ''
        'Equity.US' -> ''  # malformed, two segments only
    """
    parts = symbol.split(".")
    if len(parts) >= 3 and parts[0] == "Equity":
        return parts[1]
    return ""
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_symbol_utils.py -v
```

Expected: all `TestEquityListingPrefix` tests pass; pre-existing `TestIsFuturesSymbol`, `TestIsUsEquity`, `TestFuturesRoot` still pass.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/symbol_utils.py tests/test_symbol_utils.py
git add lib/symbol_utils.py tests/test_symbol_utils.py
git commit -m "feat: add equity_listing_prefix helper for symbol parsing"
```

---

## Task 2: Add failing tests for the new E011/W003 behavior

This task only adds tests. They will all fail until Task 3 lands the implementation.

**Files:**

- Modify: `tests/test_config_lint.py`

- [ ] **Step 1: Add new test class for E011 prefix grouping (intl equities)**

Append to `tests/test_config_lint.py` after `class TestCheckE011ScheduleInconsistency`:

```python
class TestE011IntlEquityGrouping:
    """E011 must group equities by listing prefix (US, JP, Index, ...) so
    non-US equities are not compared against the US-majority signature."""

    def test_e011_intra_jp_drift_fires(self):
        """3 STABLE Equity.JP feeds, 1 with a different schedule -> E011."""
        sched_a = [
            {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "Asia/Tokyo;0900-1530;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.JP.1305/JPY", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                2, symbol="Equity.JP.1306/JPY", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                3, symbol="Equity.JP.1308/JPY", asset_type="equity",
                state="STABLE", schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3

    def test_e011_cross_prefix_silent(self):
        """An Equity.JP feed and an Equity.US feed with different
        timezones must NOT trip E011 — they belong to different groups."""
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2, symbol="Equity.JP.1305/JPY", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_index_standalone_from_us(self):
        """Equity.Index.* must NOT group with Equity.US.* — they are
        separate prefixes even though both use America/New_York."""
        sched = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_dev = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=sched,
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=sched,
            ),
            _make_feed(
                3, symbol="Equity.Index.TSLA/USD", asset_type="equity",
                state="STABLE", schedules=sched_dev,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        # Index is a single-member group; no peer to disagree with.
        assert len(errors) == 0

    def test_e011_intra_index_drift_fires(self):
        """If 2+ Equity.Index feeds disagree, E011 must fire on the minority."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.Index.TSLA/USD", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                2, symbol="Equity.Index.MSTR/USD", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                3, symbol="Equity.Index.CRCL/USD", asset_type="equity",
                state="STABLE", schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3

    def test_e011_intl_futures_subgrouped_by_country(self):
        """KR equity futures and US equity futures must not cross-compare."""
        feeds = [
            _make_feed(
                1, symbol="Equity.US.EMH6/USD", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2, symbol="Equity.KR.KSM6/KRW", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Seoul;0900-1530;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0
```

- [ ] **Step 2: Add new test class for E011 STABLE-only scope**

Append to `tests/test_config_lint.py`:

```python
class TestE011StableOnlyScope:
    """E011 is a CI blocker; it must only fire on STABLE feeds.
    COMING_SOON drift is W003's responsibility."""

    def test_e011_silent_on_coming_soon_only_drift(self):
        """A COMING_SOON feed disagreeing with another COMING_SOON feed
        does NOT fire E011 (no STABLE involvement)."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.US.NEW1/USD", asset_type="equity",
                state="COMING_SOON", schedules=sched_a,
            ),
            _make_feed(
                2, symbol="Equity.US.NEW2/USD", asset_type="equity",
                state="COMING_SOON", schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_silent_when_only_coming_soon_deviates(self):
        """Multiple agreeing STABLE feeds + one COMING_SOON deviant ->
        E011 must NOT fire (drift is in non-STABLE feed)."""
        sched_majority = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_deviant = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=sched_majority,
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=sched_majority,
            ),
            _make_feed(
                3, symbol="Equity.US.NEW1/USD", asset_type="equity",
                state="COMING_SOON", schedules=sched_deviant,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_fires_when_stable_deviates_from_stable(self):
        """Sanity: STABLE-vs-STABLE drift still fires (already covered by
        TestCheckE011ScheduleInconsistency, repeated here for clarity)."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=sched_a,
            ),
            _make_feed(
                3, symbol="Equity.US.GOOG/USD", asset_type="equity",
                state="STABLE", schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
```

- [ ] **Step 3: Add new test class for W003 expanded scope (prefix + COMING_SOON + futures)**

Append to `tests/test_config_lint.py`:

```python
class TestW003ExpandedScope:
    """W003 must:
       - group equities by listing prefix (same as E011),
       - cover STABLE + COMING_SOON,
       - include futures via futures_root sub-grouping (no longer exempt).
    """

    def test_w003_intl_equity_prefix_grouping(self):
        """3 STABLE Equity.JP majority + 1 STABLE Equity.JP minority -> W003 fires."""
        sched_a = [
            {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "Asia/Tokyo;0900-1530;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                i, symbol=f"Equity.JP.130{i}/JPY", asset_type="equity",
                state="STABLE", schedules=sched_a,
            )
            for i in range(1, 4)
        ] + [
            _make_feed(
                4, symbol="Equity.JP.1308/JPY", asset_type="equity",
                state="STABLE", schedules=sched_b,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 4

    def test_w003_cross_prefix_silent(self):
        """An Equity.JP feed and an Equity.US feed must NOT cross-flag W003."""
        feeds = [
            _make_feed(
                i, symbol=f"Equity.US.SYM{i}/USD", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
                ],
            )
            for i in range(1, 4)
        ] + [
            _make_feed(
                4, symbol="Equity.JP.1305/JPY", asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_w003_coming_soon_drift_fires(self):
        """COMING_SOON spot feed drifts from STABLE majority -> W003 fires."""
        sched_majority = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_deviant = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                i, symbol=f"Equity.US.SYM{i}/USD", asset_type="equity",
                state="STABLE", schedules=sched_majority,
            )
            for i in range(1, 4)
        ] + [
            _make_feed(
                4, symbol="Equity.US.NEW1/USD", asset_type="equity",
                state="COMING_SOON", schedules=sched_deviant,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 4

    def test_w003_stable_futures_intra_root_drift_fires(self):
        """Two STABLE futures with the same root but different schedules ->
        W003 fires (futures are no longer exempt under the new grouping)."""
        feeds = [
            _make_feed(
                1, symbol="Commodities.WTIK6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2, symbol="Commodities.WTIM6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                3, symbol="Commodities.WTIN6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 3

    def test_w003_coming_soon_futures_drift_fires(self):
        """COMING_SOON futures drift from STABLE peers in the same root ->
        W003 fires (was previously silent due to futures exemption)."""
        feeds = [
            _make_feed(
                1, symbol="Commodities.WTIK6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2, symbol="Commodities.WTIM6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                3, symbol="Commodities.WTIQ6/USD", asset_type="commodity",
                state="COMING_SOON",
                schedules=[
                    {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 3

    def test_w003_different_futures_roots_silent(self):
        """Different futures roots are different groups -> no W003."""
        feeds = [
            _make_feed(
                1, symbol="Commodities.WTIK6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2, symbol="Commodities.CLK6/USD", asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0
```

- [ ] **Step 4: Run the new tests and verify they fail**

```bash
pytest tests/test_config_lint.py::TestE011IntlEquityGrouping \
       tests/test_config_lint.py::TestE011StableOnlyScope \
       tests/test_config_lint.py::TestW003ExpandedScope -v
```

Expected: most tests fail. Specifically:

- `test_e011_cross_prefix_silent` fails (today both feeds share `("equity",)` group, signatures differ → E011 fires).
- `test_e011_silent_when_only_coming_soon_deviates` fails (today E011 runs on all non-INACTIVE feeds).
- `test_e011_silent_on_coming_soon_only_drift` fails for the same reason.
- `test_w003_coming_soon_drift_fires` fails (today W003 is STABLE-only, doesn't see the COMING_SOON feed).
- `test_w003_stable_futures_intra_root_drift_fires` fails (today W003 exempts futures).
- `test_w003_coming_soon_futures_drift_fires` fails for both reasons above.
- `test_w003_intl_equity_prefix_grouping` may pass coincidentally (all 4 in same `("equity",)` group, 3 vs 1 majority); leave it.

A handful (e.g. `test_e011_intra_jp_drift_fires`, `test_e011_index_standalone_from_us`, `test_e011_intra_index_drift_fires`, `test_w003_cross_prefix_silent`, `test_e011_intl_futures_subgrouped_by_country`) may pass or fail depending on current grouping coincidences — that is fine, Task 3 brings them all green.

- [ ] **Step 5: Commit failing tests**

```bash
pre-commit run --files tests/test_config_lint.py
git add tests/test_config_lint.py
git commit -m "test: add failing tests for E011/W003 prefix grouping and state scope"
```

---

## Task 3: Refactor `check_schedules` to implement the new design

This is the core implementation task. It collapses the dual-collection logic in `check_schedules` into a single state-tagged `group_signatures` dict consumed by both rules.

**Files:**

- Modify: `lib/config_lint.py`

- [ ] **Step 1: Update the import line**

Open `lib/config_lint.py`. Change line 15 from:

```python
from lib.symbol_utils import futures_root, is_futures_symbol, is_us_equity
```

to:

```python
from lib.symbol_utils import (
    equity_listing_prefix,
    futures_root,
    is_futures_symbol,
    is_us_equity,
)
```

- [ ] **Step 2: Replace the body of `check_schedules`**

In `lib/config_lint.py`, replace the entire function `check_schedules` (currently lines 417-589) with the implementation below. This rewrites both the data-collection block (a single `group_signatures` dict storing `(fid, sym, sig, state)` per entry) and the firing logic for E011 and W003.

```python
def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006, E010, E011, W001, W002, W003: schedule validation rules.

    E011 fires on STABLE feeds only (CI blocker).
    W003 fires on STABLE + COMING_SOON feeds (advisory).
    Both rules use the same group_signatures dict, keyed by:
        - ("equity", listing_prefix)             for equity spot feeds
        - ("equity", listing_prefix, futures_root) for equity futures
        - (asset_type, futures_root)             for non-equity futures
        - (asset_type,)                          for non-equity spot feeds
    """
    findings: list[LintFinding] = []

    # group_key -> list of (feed_id, symbol, signature, state)
    group_signatures: dict[tuple, list[tuple[int, str, tuple, str]]] = {}

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        schedules = feed.get("marketSchedules", [])

        if state == "INACTIVE":
            continue

        sessions = [s.get("session", "") for s in schedules]

        # E010: duplicate session within a single feed
        session_counts = Counter(sessions)
        dup_sessions = sorted({s for s, c in session_counts.items() if c > 1 and s})
        if dup_sessions:
            findings.append(
                LintFinding(
                    rule_id="E010",
                    severity="ERROR",
                    message=(
                        f"duplicate session(s) in marketSchedules: {dup_sessions}"
                    ),
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # E010: identical (session, marketSchedule) tuple repeated
        sched_tuples = [
            (s.get("session", ""), s.get("marketSchedule", "")) for s in schedules
        ]
        tuple_counts = Counter(sched_tuples)
        if any(c > 1 for c in tuple_counts.values()):
            findings.append(
                LintFinding(
                    rule_id="E010",
                    severity="ERROR",
                    message="duplicate verbatim marketSchedules entry",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        sessions_set = set(sessions)

        # E006: non-equity with extended sessions
        if asset_type != "equity":
            extended = sessions_set & _EXTENDED_SESSIONS
            if extended:
                findings.append(
                    LintFinding(
                        rule_id="E006",
                        severity="ERROR",
                        message=f"non-equity ({asset_type}) has extended sessions: {sorted(extended)}",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # Build the group key for E011 / W003.
        if asset_type == "equity":
            prefix = equity_listing_prefix(sym)
            if is_futures_symbol(sym):
                group_key: tuple = (asset_type, prefix, futures_root(sym))
            else:
                group_key = (asset_type, prefix)
        else:
            if is_futures_symbol(sym):
                group_key = (asset_type, futures_root(sym))
            else:
                group_key = (asset_type,)

        sig = _get_schedule_signature(schedules)
        group_signatures.setdefault(group_key, []).append((fid, sym, sig, state))

        # STABLE-only single-feed schedule rules
        if state == "STABLE":
            # W001: US equity missing extended sessions
            if is_us_equity(feed):
                missing = _US_EQUITY_EXPECTED_SESSIONS - sessions_set
                if missing:
                    findings.append(
                        LintFinding(
                            rule_id="W001",
                            severity="WARNING",
                            message=f"STABLE US equity missing sessions: {sorted(missing)}",
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

                # W002: US equity wrong timezone
                for sched in schedules:
                    tz = _extract_timezone(sched.get("marketSchedule", ""))
                    if tz and tz != "America/New_York":
                        findings.append(
                            LintFinding(
                                rule_id="W002",
                                severity="WARNING",
                                message=f"US equity using timezone '{tz}' instead of 'America/New_York'",
                                feed_id=fid,
                                symbol=sym,
                            )
                        )
                        break  # one finding per feed is enough

    # E011: STABLE-only strict schedule inconsistency.
    # Reference signature is the most common signature among STABLE feeds in
    # the group; any STABLE feed with a different signature fires.
    for group_key, entries in group_signatures.items():
        stable_entries = [(fid, sym, sig) for fid, sym, sig, st in entries if st == "STABLE"]
        if len(stable_entries) < 2:
            continue
        distinct_sigs = {sig for _, _, sig in stable_entries}
        if len(distinct_sigs) < 2:
            continue

        sig_counter: Counter[tuple] = Counter(sig for _, _, sig in stable_entries)
        reference_sig = sig_counter.most_common(1)[0][0]
        group_label = ", ".join(str(k) for k in group_key)

        for fid, sym, sig in stable_entries:
            if sig != reference_sig:
                findings.append(
                    LintFinding(
                        rule_id="E011",
                        severity="ERROR",
                        message=(
                            f"schedule disagrees with other feeds in group"
                            f" ({group_label}): {len(distinct_sigs)} distinct"
                            f" schedules across {len(stable_entries)} STABLE feeds"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    # W003: schedule deviation from group majority across STABLE + COMING_SOON.
    # Majority is the most common signature among all entries in the group.
    for group_key, entries in group_signatures.items():
        active_entries = [
            (fid, sym, sig) for fid, sym, sig, st in entries
            if st in ("STABLE", "COMING_SOON")
        ]
        if len(active_entries) <= 1:
            continue

        sig_counts: Counter[tuple] = Counter(sig for _, _, sig in active_entries)
        majority_sig = sig_counts.most_common(1)[0][0]
        # If every signature is unique, there is no majority -> skip.
        if sig_counts[majority_sig] == 1:
            continue

        # Match group label format used elsewhere in the linter: just the
        # asset_type for non-equity spot, otherwise the joined key.
        if len(group_key) == 1:
            group_label = group_key[0]
        else:
            group_label = ", ".join(str(k) for k in group_key)

        for fid, sym, sig in active_entries:
            if sig != majority_sig:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=f"schedule deviates from {group_label} majority",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    return findings
```

- [ ] **Step 3: Run the new test classes and verify they pass**

```bash
pytest tests/test_config_lint.py::TestE011IntlEquityGrouping \
       tests/test_config_lint.py::TestE011StableOnlyScope \
       tests/test_config_lint.py::TestW003ExpandedScope -v
```

Expected: all green.

- [ ] **Step 4: Run the full `tests/test_config_lint.py` and verify everything still passes**

```bash
pytest tests/test_config_lint.py -v
```

Expected: all tests pass. In particular:

- `TestCheckE011ScheduleInconsistency` — all four pre-existing tests still green.
- `TestCheckSchedules.test_w003_schedule_deviation` — still green (5 STABLE majority + 1 STABLE deviant in `("commodity",)` group).
- `TestCheckSchedules.test_w003_futures_exempt` — still green for a different mechanical reason: the lone future is in its own `("commodity", "CC")` group with only 1 entry, so W003 can't fire. (Step 5 will refresh the docstring.)
- `TestCheckSchedules.test_w003_single_feed_in_class` — still green.
- `TestCheckSchedules.test_inactive_feeds_skipped` — still green.

- [ ] **Step 5: Refresh the misleading docstring on `test_w003_futures_exempt`**

The test name and docstring describe the OLD reason W003 stayed silent (futures explicitly exempt). Under the new grouping the silence comes from the future being in its own subgroup. Update only the docstring to keep grep'ability of the test name intact.

In `tests/test_config_lint.py`, find:

```python
    def test_w003_futures_exempt(self):
        """Futures contracts are exempt from schedule deviation warnings."""
```

Replace with:

```python
    def test_w003_futures_exempt(self):
        """A lone future is silent because its (asset_type, futures_root)
        subgroup has only one feed — no peer to disagree with. Spot peers
        live in a different group and are not compared against it."""
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests across the project still pass. (No other module depends on the removed `is_future` flag in `asset_type_schedules`.)

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: refine E011/W003 grouping + split severity by feed state

E011 (ERROR, CI blocker) now runs on STABLE feeds only, grouped by
(asset_type, listing_prefix, futures_root?) so non-US equities and
multi-listed instruments are no longer compared against the US majority.

W003 (WARNING, advisory) now runs on STABLE + COMING_SOON, uses the
same group key, and includes futures (no longer exempt). Closes the
COMING_SOON futures coverage gap that scoping E011 to STABLE created."
```

---

## Task 4: Update `docs/config_linter.md`

**Files:**

- Modify: `docs/config_linter.md`

- [ ] **Step 1: Update the E011 row in the Errors table**

Find the row in the `## Errors` table:

```markdown
| E011 | Schedule inconsistency within asset group | non-INACTIVE, grouped by `asset_type` (+ futures root) |
```

Replace with:

```markdown
| E011 | Schedule inconsistency within asset group | STABLE only, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
```

- [ ] **Step 2: Update the W003 row in the Warnings table**

Find:

```markdown
| W003 | Schedule deviates from the asset-class majority | STABLE, non-futures |
```

Replace with:

```markdown
| W003 | Schedule deviates from the asset-class majority | STABLE + COMING_SOON, grouped by `(asset_type, equity_listing_prefix?, futures_root?)` |
```

- [ ] **Step 3: Update the "E011 vs W003" subsection**

Find the section starting with `### E011 vs W003` and replace its body with:

```markdown
### E011 vs W003

Both flag schedule drift, but with different scopes and severity:

- **E011 (ERROR)** is the CI-blocking rule. It fires when two **STABLE** feeds in the same group have any distinct schedule signature. Groups are `(asset_type, equity_listing_prefix, futures_root?)` for equities and `(asset_type, futures_root?)` for everything else. Equity futures are sub-grouped by both listing prefix and root.
- **W003 (WARNING)** is the soft heads-up. It fires on minority deviation from the group majority across **STABLE + COMING_SOON** feeds. It uses the same group key as E011, including futures sub-grouping.

They intentionally overlap on STABLE feeds. W003 additionally surfaces drift that E011 cannot see — namely COMING_SOON spot or futures feeds that disagree with their STABLE peers — without blocking CI.
```

- [ ] **Step 4: Update the "Rule Scope" bullet for E010/E011**

Find:

```markdown
- E010/E011 are schedule-integrity checks that run on every non-INACTIVE feed.
```

Replace with:

```markdown
- E010 runs on every non-INACTIVE feed. E011 runs on STABLE feeds only (it is a CI blocker).
- W003 runs on STABLE + COMING_SOON feeds (advisory; not a CI blocker unless `--warnings-as-errors`).
```

- [ ] **Step 5: Run pre-commit and commit**

```bash
pre-commit run --files docs/config_linter.md
git add docs/config_linter.md
git commit -m "docs: update config_linter docs for E011/W003 scope and grouping changes"
```

---

## Task 5: Smoke test against the real `after.json`

This task confirms the empirical behavior described in the spec ("~620 non-US equity feeds stop firing", "newly visible signal in IE/NL/KR"). It is read-only — no code changes — and produces a small evidence note that gets committed.

**Files:**

- Create: `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md`

- [ ] **Step 1: Capture the post-change finding counts**

```bash
source venv/bin/activate
python3 config_linter.py --config after.json --format json --output /tmp/lint_after.json || true
python3 -c "
import json
with open('/tmp/lint_after.json') as f:
    findings = json.load(f)
from collections import Counter
by_rule = Counter(f['rule_id'] for f in findings)
for rule in sorted(by_rule):
    print(f'{rule}: {by_rule[rule]}')
print(f'TOTAL: {len(findings)}')
"
```

Expected behavior (qualitative — exact counts depend on current `after.json`):

- `E011`: dramatically fewer findings than before; should be near-zero or only legitimately-deviant feeds (e.g. the 3 IE ETF minorities, the 1 NL Berlin ETF, the 4 KR feeds with `0900-1545`).
- `W003`: a handful of new findings on legit deviations; no longer any "non-US equity vs US majority" noise.

- [ ] **Step 2: Capture which symbols still trip E011 and W003**

```bash
python3 -c "
import json
with open('/tmp/lint_after.json') as f:
    findings = json.load(f)
for rule in ('E011', 'W003'):
    print(f'--- {rule} ---')
    for f in findings:
        if f['rule_id'] == rule:
            print(f\"  feed {f['feed_id']:>5}  {f['symbol']:<35}  {f['message']}\")
"
```

- [ ] **Step 3: Write a short rollout-notes file capturing the result**

Create `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md` with this template (replace the bracketed placeholders with values from Step 1 / Step 2 output):

```markdown
# Config Linter Intl Equities — Rollout Notes (2026-04-28)

Captured after merging `feat/config-linter-intl-equities`.

## Finding counts on `after.json`

| Rule          | Count     |
| ------------- | --------- |
| E011          | <fill in> |
| W003          | <fill in> |
| (other rules) | <fill in> |

## Surviving E011 findings (by symbol)

<paste the E011 list from Step 2; one bullet per finding>

## Surviving W003 findings (by symbol)

<paste the W003 list from Step 2; one bullet per finding>

## Triage decisions

<short notes per finding: "legit drift — split into sub-feed", "config bug — fix in next config patch", "accept as-is", etc.>
```

- [ ] **Step 4: Commit the rollout notes**

```bash
pre-commit run --files docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md
git add docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md
git commit -m "docs: capture lint findings on after.json after intl-equities rollout"
```

---

## Verification Checklist

Before declaring the work done, confirm:

- [ ] `pytest tests/test_symbol_utils.py tests/test_config_lint.py -v` is fully green.
- [ ] `pytest tests/ -v` is fully green (no incidental regressions in other modules).
- [ ] `python3 config_linter.py --config after.json` exits 0 (no E011 errors), or any remaining E011 findings are intentional and documented in the rollout notes.
- [ ] `git log feat/config-linter-intl-equities --oneline` shows distinct commits for: spec (already on branch), helper, failing tests, refactor, doc update, rollout notes.
- [ ] `pre-commit run --all-files` is clean.
