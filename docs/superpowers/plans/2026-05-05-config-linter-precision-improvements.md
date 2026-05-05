# Config linter precision improvements — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten seven existing config-linter rules and the JSON output envelope per the design at `docs/superpowers/specs/2026-05-05-config-linter-precision-improvements-design.md` (commit `5e6ec07`).

**Architecture:** Surgical edits to `lib/config_lint.py` (rule logic), `tools/config-linter/config_linter.py` (CLI envelope), `tools/vscode-extension/src/linter.ts` (parser update), and `docs/config_linter.md` plus two superpowers docs (text fixes). Each task is independently testable and committable. Each task follows TDD: write a failing test first, run it to confirm failure, edit production code, run tests to confirm they pass, then commit.

**Tech stack:**
- Python 3.11+, pytest, stdlib-only linter (no external deps)
- TypeScript / Node.js / Vitest for the VS Code extension
- Run Python tests: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`
- Run extension tests: `cd tools/vscode-extension && npm test`
- Run pre-commit before every commit: `pre-commit run --files <changed-files>`

**File map:**

| File | Touched in | Responsibility |
| --- | --- | --- |
| `lib/config_lint.py` | Tasks 1, 2, 3, 4, 5 | Rule logic; pure functions returning `LintFinding` lists |
| `tools/config-linter/config_linter.py` | Task 6 | CLI argparse, output formatting, envelope |
| `tools/vscode-extension/src/linter.ts` | Task 6 | Subprocess driver and JSON parser for the extension |
| `tools/vscode-extension/test/linter.test.ts` | Task 6 | Vitest fixtures for the extension parser |
| `tests/test_config_lint.py` | Tasks 1, 2, 3, 4, 5 | Library unit tests, ~3000 lines, organized by `class TestCheckXNN` |
| `tests/test_config_linter_cli.py` | Task 6 | CLI integration tests via `subprocess.run` |
| `docs/config_linter.md` | Task 7 | User-facing rule reference |
| `docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md` | Task 7 | Stale exit-code-2 claim |
| `docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md` | Task 7 | Stale exit-code-2 claim |

**Notes for the engineer:**
- The linter is invoked via `python3 tools/config-linter/config_linter.py --config after.json`. There is no installed package; `lib/` is added to `sys.path` from the CLI script.
- `LintFinding` is a dataclass at `lib/lint_finding.py` with fields `rule_id, severity, message, feed_id, symbol`.
- Diff mode (`--baseline ...` / git auto-detect) compares findings by `(rule_id, feed_id, symbol)` and ignores message text. So changing E004's message in Task 1 is silently absorbed by diff-mode suppression — no spurious "new" findings on existing PRs.
- Test helpers live at the top of `tests/test_config_lint.py` (`_make_feed`, `_make_publisher`, `_make_config`, `_futures_feed_with_validto`). Reuse them.
- Tests use `_NOW = datetime(2026, 4, 11, tzinfo=timezone.utc)` as the fixed clock for E013.

---

## Task 1 — E004 message rewording

**Spec ref:** Item 1 in design doc.

**Files:**
- Modify: `lib/config_lint.py:251-263, 370-385` (top-level and session-level E004 emissions)
- Test: `tests/test_config_lint.py` (add to `class TestCheckPublishers`)

- [ ] **Step 1: Add a failing test for the new top-level E004 message text**

Add this test inside `class TestCheckPublishers` in `tests/test_config_lint.py` (anywhere alongside the other `test_e004_*` tests):

```python
    def test_e004_message_uses_not_enough_publishers_permissioned(self):
        """E004's trailing clause must read 'Not enough publishers permissioned'."""
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        e004 = [f for f in findings if f.rule_id == "E004"]
        assert len(e004) == 1
        assert "Not enough publishers permissioned" in e004[0].message
        assert "no fault tolerance" not in e004[0].message
```

Also add a session-level message test (this exercises the second emission site):

```python
    def test_e004_session_level_message_uses_not_enough_publishers_permissioned(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                min_publishers=3,
                publisher_ids=[1, 2, 3, 4, 5],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2],
                        "minPublishers": 2,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        e004 = [f for f in findings if f.rule_id == "E004"]
        assert len(e004) == 1
        assert "Not enough publishers permissioned" in e004[0].message
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `pytest tests/test_config_lint.py::TestCheckPublishers::test_e004_message_uses_not_enough_publishers_permissioned tests/test_config_lint.py::TestCheckPublishers::test_e004_session_level_message_uses_not_enough_publishers_permissioned -v`

Expected: both FAIL with assertion errors on the `"Not enough publishers permissioned"` substring (the current message says `"no fault tolerance"`).

- [ ] **Step 3: Update the top-level E004 message in `lib/config_lint.py`**

In `lib/config_lint.py` around line 252, change:

```python
            if not is_exempt and len(pub_ids) > 0 and min_pub >= len(pub_ids):
                findings.append(
                    LintFinding(
                        rule_id="E004",
                        severity="ERROR",
                        message=(
                            f"minPublishers ({min_pub}) >= publisher count"
                            f" ({len(pub_ids)}), no fault tolerance"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

to:

```python
            if not is_exempt and len(pub_ids) > 0 and min_pub >= len(pub_ids):
                findings.append(
                    LintFinding(
                        rule_id="E004",
                        severity="ERROR",
                        message=(
                            f"minPublishers ({min_pub}) >= publisher count"
                            f" ({len(pub_ids)}), Not enough publishers permissioned"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

- [ ] **Step 4: Update the session-level E004 message in `lib/config_lint.py`**

In `lib/config_lint.py` around line 374, change:

```python
                if session_count > 0 and session_min >= session_count:
                    findings.append(
                        LintFinding(
                            rule_id="E004",
                            severity="ERROR",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" >= publisher count ({session_count})"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
```

to:

```python
                if session_count > 0 and session_min >= session_count:
                    findings.append(
                        LintFinding(
                            rule_id="E004",
                            severity="ERROR",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" >= publisher count ({session_count}),"
                                f" Not enough publishers permissioned"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
```

- [ ] **Step 5: Run the new tests to confirm they pass**

Run: `pytest tests/test_config_lint.py::TestCheckPublishers -v`

Expected: all `TestCheckPublishers` tests pass, including both new ones. The pre-existing `test_e004_*` tests do not assert on the trailing clause so they continue to pass.

- [ ] **Step 6: Run the full lint test suite to confirm no other regression**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass. (`docs/config_linter_examples.md` may show the old message text in fixtures — that's documentation, not under test.)

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "fix(linter): reword E004 to 'Not enough publishers permissioned'

Replaces the old 'no fault tolerance' phrase with operator-friendly
language. Same condition, same severity. Both top-level and session-
level E004 emissions updated."
```

---

## Task 2 — E011 ambiguous-tie handling

**Spec ref:** Item 2 in design doc.

When two STABLE feeds in the same group have two distinct schedules, today's code uses `Counter.most_common(1)` to pick a "reference" — but with a tie, that pick is non-deterministic dict-order. Fix: detect ties on the top count and emit one finding per feed with a "no consensus" message.

**Files:**
- Modify: `lib/config_lint.py:570-604` (the E011 emission block in `check_schedules`)
- Modify: `tests/test_config_lint.py:986` (existing `test_e011_futures_same_root_disagree` asserts `len(errors) == 1`; under tie-mode it becomes 2)
- Test: `tests/test_config_lint.py` (add to `class TestCheckE011ScheduleInconsistency`)

- [ ] **Step 1: Add a failing test for symmetric tie-mode emission**

Add to `class TestCheckE011ScheduleInconsistency` in `tests/test_config_lint.py`:

```python
    def test_e011_two_feeds_two_schedules_emits_per_feed_no_consensus(self):
        """Tie case: 2 STABLE feeds with 2 distinct schedules. Both feeds
        get a finding with a 'no consensus' message — neither is treated
        as the reference."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 2
        flagged_ids = sorted(f.feed_id for f in errors)
        assert flagged_ids == [1, 2]
        for f in errors:
            assert "no consensus" in f.message

    def test_e011_clear_majority_keeps_per_minority_behavior(self):
        """Sanity: 3 feeds, 2 of them share a schedule. Only the lone
        deviant gets flagged (not the majority)."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
        assert "no consensus" not in errors[0].message
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pytest tests/test_config_lint.py::TestCheckE011ScheduleInconsistency::test_e011_two_feeds_two_schedules_emits_per_feed_no_consensus tests/test_config_lint.py::TestCheckE011ScheduleInconsistency::test_e011_clear_majority_keeps_per_minority_behavior -v`

Expected: the tie-mode test FAILS with `assert 1 == 2` (current code emits one finding for an arbitrary feed). The clear-majority test passes (it documents existing behavior).

- [ ] **Step 3: Replace the E011 emission block in `lib/config_lint.py`**

In `lib/config_lint.py` find this block (lines 570–604):

```python
    # E011: STABLE-only strict per-session schedule inconsistency.
    for bucket_key, entries in session_groups.items():
        stable_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st == "STABLE"
        ]
        if len(stable_entries) < 2:
            continue
        distinct = {sched_str for _, _, sched_str in stable_entries}
        if len(distinct) < 2:
            continue

        sig_counter: Counter[str] = Counter(
            sched_str for _, _, sched_str in stable_entries
        )
        reference = sig_counter.most_common(1)[0][0]
        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        for fid, sym, sched_str in stable_entries:
            if sched_str != reference:
                findings.append(
                    LintFinding(
                        rule_id="E011",
                        severity="ERROR",
                        message=(
                            f"{session} schedule disagrees with group"
                            f" {group_label}: {len(distinct)} distinct"
                            f" schedules across {len(stable_entries)} STABLE feeds"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

Replace with:

```python
    # E011: STABLE-only strict per-session schedule inconsistency.
    for bucket_key, entries in session_groups.items():
        stable_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st == "STABLE"
        ]
        if len(stable_entries) < 2:
            continue
        distinct = {sched_str for _, _, sched_str in stable_entries}
        if len(distinct) < 2:
            continue

        sig_counter: Counter[str] = Counter(
            sched_str for _, _, sched_str in stable_entries
        )
        top_count = sig_counter.most_common(1)[0][1]
        top_schedules = {s for s, c in sig_counter.items() if c == top_count}
        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        if len(top_schedules) == 1:
            # Clear majority — flag only the minority feeds.
            reference = next(iter(top_schedules))
            for fid, sym, sched_str in stable_entries:
                if sched_str != reference:
                    findings.append(
                        LintFinding(
                            rule_id="E011",
                            severity="ERROR",
                            message=(
                                f"{session} schedule disagrees with group"
                                f" {group_label}: {len(distinct)} distinct"
                                f" schedules across {len(stable_entries)} STABLE"
                                f" feeds"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
        else:
            # Tie at the top — no clear majority. Flag every STABLE feed
            # in the bucket symmetrically.
            for fid, sym, _sched_str in stable_entries:
                findings.append(
                    LintFinding(
                        rule_id="E011",
                        severity="ERROR",
                        message=(
                            f"{session} schedule has no consensus across group"
                            f" {group_label}: {len(distinct)} distinct schedules"
                            f" across {len(stable_entries)} STABLE feeds, no"
                            f" majority"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

- [ ] **Step 4: Update the existing 2-feed test that depends on the old arbitrary-pick**

The existing test at `tests/test_config_lint.py:986` (`test_e011_futures_same_root_disagree`) asserts `len(errors) == 1`. Under the new tie logic it becomes 2. Change:

```python
    def test_e011_futures_same_root_disagree(self):
        sched_a = [{"marketSchedule": "America/New_York;O;", "session": "REGULAR"}]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Commodities.WTIM6/USD",
                asset_type="commodity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
```

to:

```python
    def test_e011_futures_same_root_disagree(self):
        """Two-feed tie case: both feeds get a 'no consensus' E011."""
        sched_a = [{"marketSchedule": "America/New_York;O;", "session": "REGULAR"}]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Commodities.WTIM6/USD",
                asset_type="commodity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 2
        for f in errors:
            assert "no consensus" in f.message
```

- [ ] **Step 5: Run the E011 test class to confirm everything passes**

Run: `pytest tests/test_config_lint.py::TestCheckE011ScheduleInconsistency tests/test_config_lint.py::TestE011IntlEquityGrouping tests/test_config_lint.py::TestE011StableOnlyScope -v`

Expected: all tests pass.

- [ ] **Step 6: Run the full lint test suite**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "fix(linter): E011 emits per-feed 'no consensus' on schedule ties

Previously most_common(1) arbitrarily picked one schedule as the
reference when two STABLE feeds in a group had distinct schedules
with equal counts; the chosen feed depended on dict insertion order.
Now ties trigger symmetric per-feed findings with a 'no majority'
message."
```

---

## Task 3 — E013 expand to STABLE expired futures

**Spec ref:** Item 3 in design doc.

Today `check_expired_coming_soon_futures` only fires on `state == "COMING_SOON"`. Extend it to also fire on `state == "STABLE"` and branch the message by state. Rename the function to `check_expired_futures` so the name matches its scope.

**Files:**
- Modify: `lib/config_lint.py:951-995` (function body and rename)
- Modify: `lib/config_lint.py:1070` (orchestrator call site)
- Modify: `tests/test_config_lint.py:12, 1605-1692` (import + class with state-not-flagged test)
- Test: `tests/test_config_lint.py` (add to `class TestCheckE013ExpiredFutures`)

- [ ] **Step 1: Add failing tests for STABLE expired and the renamed function**

Add to `class TestCheckE013ExpiredFutures` in `tests/test_config_lint.py`:

```python
    def test_e013_expired_stable_futures_flagged(self):
        """STABLE futures with all validTo in the past must fire E013
        with a state-tagged message."""
        feed = _futures_feed_with_validto(
            1,
            "Commodities.WTIK6/USD",
            "2026-01-01T00:00:00.000000000Z",
            state="STABLE",
        )
        findings = check_expired_futures([feed], _NOW)
        errors = [f for f in findings if f.rule_id == "E013"]
        assert len(errors) == 1
        assert "STABLE futures feed has expired" in errors[0].message
        assert "change state to INACTIVE" in errors[0].message

    def test_e013_expired_coming_soon_message_unchanged(self):
        """COMING_SOON message keeps its existing wording."""
        feed = _futures_feed_with_validto(
            1, "Commodities.WTIK6/USD", "2026-01-01T00:00:00.000000000Z"
        )
        findings = check_expired_futures([feed], _NOW)
        errors = [f for f in findings if f.rule_id == "E013"]
        assert len(errors) == 1
        assert "COMING_SOON futures feed has expired" in errors[0].message

    def test_e013_inactive_stable_futures_not_flagged(self):
        """INACTIVE feeds (regardless of expiry) must never fire E013."""
        feed = _futures_feed_with_validto(
            1,
            "Commodities.WTIK6/USD",
            "2026-01-01T00:00:00.000000000Z",
            state="INACTIVE",
        )
        findings = check_expired_futures([feed], _NOW)
        assert findings == []
```

Update the import at the top of `tests/test_config_lint.py` (line 12):

```python
from lib.config_lint import (
    LintFinding,
    lint_config,
    check_duplicates,
    check_schema,
    check_publishers,
    check_publisher_duplicates,
    check_schedules,
    check_hermes_ids,
    check_expired_coming_soon_futures,
    check_benchmark_mapping,
    check_corporate_actions,
    check_identifier_continuity,
)
```

becomes:

```python
from lib.config_lint import (
    LintFinding,
    lint_config,
    check_duplicates,
    check_schema,
    check_publishers,
    check_publisher_duplicates,
    check_schedules,
    check_hermes_ids,
    check_expired_futures,
    check_benchmark_mapping,
    check_corporate_actions,
    check_identifier_continuity,
)
```

Update the existing test at `tests/test_config_lint.py:1621` (`test_e013_stable_state_not_flagged`) — under the new behavior, STABLE expired IS flagged. Replace its body so it now checks the *non-expired* STABLE case (which is still silent):

```python
    def test_e013_stable_not_yet_expired(self):
        """STABLE futures with future validTo must not fire E013."""
        feed = _futures_feed_with_validto(
            1,
            "Commodities.WTIK6/USD",
            "2026-12-01T00:00:00.000000000Z",
            state="STABLE",
        )
        findings = check_expired_futures([feed], _NOW)
        assert findings == []
```

(Yes, rename the method too. The previous semantics — "STABLE not flagged" — is no longer correct.)

Then do a verbatim rename across the rest of the test file so all six pre-existing tests in `TestCheckE013ExpiredFutures` (the original 6 at lines 1606, 1614, 1621, 1631, 1638, 1664) call the new function. The simplest way is a single sed-style replacement; verify by grep:

```bash
sed -i 's/check_expired_coming_soon_futures/check_expired_futures/g' tests/test_config_lint.py
grep -c check_expired_coming_soon_futures tests/test_config_lint.py
# Expected: 0
grep -c check_expired_futures tests/test_config_lint.py
# Expected: 10
```

The 10 occurrences are: 1 import line, plus 9 calls in test bodies (5 original tests kept + 1 replaced + 3 newly added).

- [ ] **Step 2: Run the new tests to confirm failure**

Run: `pytest tests/test_config_lint.py::TestCheckE013ExpiredFutures -v`

Expected: tests fail with `ImportError` (function doesn't exist yet) or `AttributeError`.

- [ ] **Step 3: Rename and extend the function in `lib/config_lint.py`**

In `lib/config_lint.py` lines 951–995, replace the entire `check_expired_coming_soon_futures` function with:

```python
def check_expired_futures(
    feeds: list[dict], now: datetime
) -> list[LintFinding]:
    """E013: STABLE or COMING_SOON futures whose every validTo is in the past.

    A feed is flagged when:
      - state is STABLE or COMING_SOON, AND
      - the symbol matches the futures pattern, AND
      - at least one identifier has a validTo, AND
      - every validTo found is earlier than `now`.

    INACTIVE feeds and feeds with no validTo identifiers are skipped.
    """
    findings: list[LintFinding] = []

    for feed in feeds:
        state = feed.get("state", "")
        if state not in ("STABLE", "COMING_SOON"):
            continue
        sym = feed.get("symbol", "")
        if not is_futures_symbol(sym):
            continue

        valid_tos: list[datetime] = []
        for sched in feed.get("marketSchedules", []):
            bm = sched.get("benchmarkMapping", {}) or {}
            for vendor_obj in bm.values():
                if not isinstance(vendor_obj, dict):
                    continue
                for idf in vendor_obj.get("identifiers", []) or []:
                    vt = idf.get("validTo")
                    parsed = _parse_iso(vt) if vt else None
                    if parsed is not None:
                        valid_tos.append(parsed)

        if not valid_tos:
            continue

        if all(vt < now for vt in valid_tos):
            latest = max(valid_tos)
            findings.append(
                LintFinding(
                    rule_id="E013",
                    severity="ERROR",
                    message=(
                        f"{state} futures feed has expired"
                        f" (latest validTo: {latest.isoformat()});"
                        f" change state to INACTIVE"
                    ),
                    feed_id=feed.get("feedId"),
                    symbol=sym,
                )
            )

    return findings
```

- [ ] **Step 4: Update the orchestrator call in `lib/config_lint.py:1070`**

In `lib/config_lint.py` find this block in `lint_config`:

```python
    findings.extend(check_expired_coming_soon_futures(feeds, now))
```

Replace with:

```python
    findings.extend(check_expired_futures(feeds, now))
```

- [ ] **Step 5: Run E013 tests to confirm they pass**

Run: `pytest tests/test_config_lint.py::TestCheckE013ExpiredFutures -v`

Expected: all tests pass, including the three new ones and the five updated ones.

- [ ] **Step 6: Run the full lint test suite**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat(linter): E013 also fires on STABLE expired futures

Renames check_expired_coming_soon_futures to check_expired_futures and
extends the rule to STABLE state. Message text branches on state so
operators see whether the expired feed is mid-lifecycle (STABLE) or
pre-launch (COMING_SOON). INACTIVE feeds remain unaffected."
```

---

## Task 4 — E014 lift OVER_NIGHT exemption

**Spec ref:** Item 4 in design doc.

Empirically, all 126 STABLE feeds with an OVER_NIGHT session in `after.json` already populate `benchmarkMapping`, so this is a tightening of an already-followed convention.

**Files:**
- Modify: `lib/config_lint.py:691-693` (delete the `if session_name == "OVER_NIGHT": continue`)
- Modify: `tests/test_config_lint.py:538-547` (existing `test_e014_overnight_exempt` is now wrong)
- Test: `tests/test_config_lint.py` (add to `class TestCheckE014BenchmarkMapping`)

- [ ] **Step 1: Add failing tests for OVER_NIGHT enforcement**

Add to `class TestCheckE014BenchmarkMapping` in `tests/test_config_lint.py`:

```python
    def test_e014_overnight_missing_bm_flagged(self):
        """OVER_NIGHT must now be checked like every other session."""
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_without_bm("OVER_NIGHT")],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        assert len(errors) == 1
        assert "OVER_NIGHT" in errors[0].message

    def test_e014_overnight_with_bm_silent(self):
        """OVER_NIGHT with benchmarkMapping populated must not fire."""
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_with_bm("OVER_NIGHT")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_all_four_equity_sessions_missing_bm_emits_four(self):
        """All four sessions of a STABLE US equity missing bm → 4 findings."""
        sessions = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_without_bm(s) for s in sessions],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        flagged_sessions = sorted(
            session for session in sessions
            if any(session in f.message for f in errors)
        )
        assert flagged_sessions == sorted(sessions)
        assert len(errors) == 4
```

Replace the existing `test_e014_overnight_exempt` test (lines 538–547) — it's now wrong:

```python
    def test_e014_overnight_exempt(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_without_bm("OVER_NIGHT")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []
```

Delete it. The new `test_e014_overnight_missing_bm_flagged` and `test_e014_overnight_with_bm_silent` tests above replace it with the correct semantics.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `pytest tests/test_config_lint.py::TestCheckE014BenchmarkMapping -v`

Expected: the new `test_e014_overnight_missing_bm_flagged` test FAILS with `assert 0 == 1`. The other new tests pass once the existing `test_e014_overnight_exempt` is deleted.

- [ ] **Step 3: Lift the OVER_NIGHT exemption in `lib/config_lint.py`**

In `lib/config_lint.py` lines 690–704, change:

```python
        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            if session_name == "OVER_NIGHT":
                continue
            bm = schedule.get("benchmarkMapping")
            if not bm:
                findings.append(
                    LintFinding(
                        rule_id="E014",
                        severity="ERROR",
                        message=f"{session_name} session missing benchmarkMapping",
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

to:

```python
        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            bm = schedule.get("benchmarkMapping")
            if not bm:
                findings.append(
                    LintFinding(
                        rule_id="E014",
                        severity="ERROR",
                        message=f"{session_name} session missing benchmarkMapping",
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

(Two-line deletion: the `if session_name == "OVER_NIGHT": continue`.)

Also update the docstring on line 677:

```python
def check_benchmark_mapping(feeds: list[dict]) -> list[LintFinding]:
    """E014: STABLE benchmarkable feed missing benchmarkMapping on non-OVERNIGHT session."""
```

becomes:

```python
def check_benchmark_mapping(feeds: list[dict]) -> list[LintFinding]:
    """E014: STABLE benchmarkable feed missing benchmarkMapping on any session."""
```

- [ ] **Step 4: Run E014 tests to confirm they pass**

Run: `pytest tests/test_config_lint.py::TestCheckE014BenchmarkMapping -v`

Expected: all tests pass.

- [ ] **Step 5: Run the full lint test suite and exercise on the live `after.json`**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass.

Then run the linter against the live config to confirm zero new E014 findings (per the empirical jq check during brainstorming):

Run: `python3 tools/config-linter/config_linter.py --config after.json --no-baseline --format json | python3 -c "import json,sys; data=json.load(sys.stdin); print('E014 count:', sum(1 for f in data if f.get('rule_id')=='E014'))"`

Expected: `E014 count: 0` (or, if there are existing pre-OVER_NIGHT E014 findings, the count must not increase compared to a `git stash && rerun` baseline).

If E014 count is non-zero on `after.json`, **stop and investigate** before committing — the empirical claim in the spec was that zero feeds need fixing.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat(linter): E014 enforces benchmarkMapping on OVER_NIGHT too

Removes the OVER_NIGHT exemption. All 126 STABLE feeds in current
after.json with an OVER_NIGHT session already populate
benchmarkMapping, so this is a tightening of an already-followed
convention. Docs note in docs/config_linter.md will be updated in
Task 7."
```

---

## Task 5 — W003 fire when no majority

**Spec ref:** Item 5 in design doc.

Today W003 short-circuits when `counts[majority] == 1`, so a bucket where every feed has a unique schedule produces no warning. Detect the no-consensus case and emit per-feed warnings.

**Files:**
- Modify: `lib/config_lint.py:606-637` (W003 emission block)
- Test: `tests/test_config_lint.py` (add to `class TestCheckSchedules` near `test_w003_*`)

- [ ] **Step 1: Add failing tests for the no-consensus case**

Add tests near the existing `test_w003_*` tests in `tests/test_config_lint.py` (line ~810):

```python
    def test_w003_no_majority_unique_schedules_per_feed_flagged(self):
        """3 commodity feeds each with a different schedule — no majority,
        every feed gets a 'no consensus' W003."""
        feeds = []
        for i, hours in enumerate(["0800-1400", "0800-1500", "0800-1600"], start=1):
            feeds.append(
                _make_feed(
                    i,
                    symbol=f"Commodities.GOLD{i}/USD",
                    asset_type="commodity",
                    state="STABLE",
                    schedules=[
                        {
                            "marketSchedule": f"America/New_York;{hours};",
                            "session": "REGULAR",
                        }
                    ],
                )
            )
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 3
        flagged_ids = sorted(f.feed_id for f in warnings)
        assert flagged_ids == [1, 2, 3]
        for w in warnings:
            assert "no consensus" in w.message

    def test_w003_top_count_tied_per_feed_flagged(self):
        """4 feeds, schedules [A, A, B, B] — tie at top, every feed flagged."""
        sched_a = "America/New_York;0930-1600;"
        sched_b = "America/New_York;0800-1500;"
        feeds = []
        for i, sched in enumerate([sched_a, sched_a, sched_b, sched_b], start=1):
            feeds.append(
                _make_feed(
                    i,
                    symbol=f"Commodities.GOLD{i}/USD",
                    asset_type="commodity",
                    state="STABLE",
                    schedules=[{"marketSchedule": sched, "session": "REGULAR"}],
                )
            )
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 4
        for w in warnings:
            assert "no consensus" in w.message
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pytest tests/test_config_lint.py::TestCheckSchedules::test_w003_no_majority_unique_schedules_per_feed_flagged tests/test_config_lint.py::TestCheckSchedules::test_w003_top_count_tied_per_feed_flagged -v`

Expected: both FAIL with `assert 0 == 3` / `assert 0 == 4` (the current short-circuit suppresses the no-majority case).

- [ ] **Step 3: Replace the W003 emission block in `lib/config_lint.py`**

In `lib/config_lint.py` find this block (lines 606–637):

```python
    # W003: per-session schedule deviation across STABLE + COMING_SOON.
    for bucket_key, entries in session_groups.items():
        active_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st in ("STABLE", "COMING_SOON")
        ]
        if len(active_entries) <= 1:
            continue

        counts: Counter[str] = Counter(sched_str for _, _, sched_str in active_entries)
        majority = counts.most_common(1)[0][0]
        if counts[majority] == 1:
            continue

        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        for fid, sym, sched_str in active_entries:
            if sched_str != majority:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=(
                            f"{session} schedule deviates from {group_label}"
                            f" majority"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

Replace with:

```python
    # W003: per-session schedule deviation across STABLE + COMING_SOON.
    for bucket_key, entries in session_groups.items():
        active_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st in ("STABLE", "COMING_SOON")
        ]
        if len(active_entries) <= 1:
            continue

        counts: Counter[str] = Counter(sched_str for _, _, sched_str in active_entries)
        if len(set(counts)) < 2:
            # Everyone agrees — nothing to report.
            continue

        top_count = counts.most_common(1)[0][1]
        top_schedules = {s for s, c in counts.items() if c == top_count}
        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        if top_count >= 2 and len(top_schedules) == 1:
            # Clear majority — flag only the minority feeds.
            majority = next(iter(top_schedules))
            for fid, sym, sched_str in active_entries:
                if sched_str != majority:
                    findings.append(
                        LintFinding(
                            rule_id="W003",
                            severity="WARNING",
                            message=(
                                f"{session} schedule deviates from {group_label}"
                                f" majority"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
        else:
            # No consensus: top_count == 1 (every feed unique) or tie at
            # the top. Flag every active feed in the bucket.
            for fid, sym, _sched_str in active_entries:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=(
                            f"{session} schedule has no consensus across"
                            f" {group_label}"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
```

- [ ] **Step 4: Run W003 tests to confirm everything passes**

Run: `pytest tests/test_config_lint.py -k "w003 or W003" -v`

Expected: all W003 tests pass, including the existing `test_w003_schedule_deviation` (clear-majority case) and the new no-consensus tests.

- [ ] **Step 5: Run the full lint test suite**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "fix(linter): W003 fires when there is no schedule majority

Adds per-feed warnings for buckets where every feed has a unique
schedule or where the top count is tied. Clear-majority behavior is
unchanged. Mirrors the option-c approach already applied to E011."
```

---

## Task 6 — JSON output envelope and VS Code extension parser

**Spec ref:** Item 6 in design doc.

The CLI's `--format json` currently emits a bare findings array. Wrap it in `{"findings": [...], "pre_existing_count": N | null}` so JSON consumers see the same diff-mode metadata that text consumers do. The VS Code extension is the only known JSON consumer and must be updated in lockstep.

**Files:**
- Modify: `tools/config-linter/config_linter.py:121-135` (`_format_json` function)
- Modify: `tools/config-linter/config_linter.py:274-300` (`--output .json` path)
- Modify: `tools/vscode-extension/src/linter.ts:85-102` (`runLinter` parser)
- Modify: `tools/vscode-extension/test/linter.test.ts:33-63` (existing JSON-parse test)
- Modify: `tests/test_config_linter_cli.py:109-123` (existing `test_json_format` and `test_json_format_clean`)
- Test: `tests/test_config_linter_cli.py` (add new tests)
- Test: `tools/vscode-extension/test/linter.test.ts` (add new test)

- [ ] **Step 1: Add failing CLI test for the new envelope**

Add to `class TestCLIOutputFormats` in `tests/test_config_linter_cli.py`:

```python
    def test_json_format_returns_envelope(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())  # E001 dup
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "json", "--no-baseline")
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)
        assert "findings" in payload
        assert "pre_existing_count" in payload
        assert payload["pre_existing_count"] is None  # full lint mode
        assert any(f["rule_id"] == "E001" for f in payload["findings"])

    def test_json_format_envelope_in_diff_mode(self, tmp_path):
        bad = _make_clean_config()
        bad["feeds"].append(bad["feeds"][0].copy())  # E001 dup in both
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(bad))
        after_path = _write_config(tmp_path, bad)
        result = _run_linter(
            "--config",
            after_path,
            "--baseline",
            str(before_path),
            "--format",
            "json",
        )
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)
        assert payload["findings"] == []
        assert isinstance(payload["pre_existing_count"], int)
        assert payload["pre_existing_count"] >= 1
```

Update the two existing tests at `tests/test_config_linter_cli.py:109-123` to match the new shape:

```python
    def test_json_format(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "json", "--no-baseline")
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)
        assert "findings" in payload
        assert any(f["rule_id"] == "E001" for f in payload["findings"])

    def test_json_format_clean(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path, "--format", "json", "--no-baseline")
        payload = json.loads(result.stdout)
        errors = [f for f in payload["findings"] if f["severity"] == "ERROR"]
        assert len(errors) == 0
```

(`--no-baseline` added to keep the test deterministic regardless of the developer's git state.)

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pytest tests/test_config_linter_cli.py::TestCLIOutputFormats -v`

Expected: the two new tests FAIL because the current output is a bare array (`isinstance(payload, dict)` returns False). The two updated tests FAIL on the missing `findings` key.

- [ ] **Step 3: Update `_format_json` and `--output .json` path**

In `tools/config-linter/config_linter.py` lines 121–135 replace:

```python
def _format_json(findings: list[LintFinding]) -> str:
    """Format findings as JSON array."""
    return json.dumps(
        [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "feed_id": f.feed_id,
                "symbol": f.symbol,
            }
            for f in findings
        ],
        indent=2,
    )
```

with:

```python
def _format_json(
    findings: list[LintFinding],
    pre_existing_count: Optional[int] = None,
) -> str:
    """Format findings as a JSON envelope.

    Shape: {"findings": [...], "pre_existing_count": int | null}.

    `pre_existing_count` is None outside diff mode; an int (possibly
    zero) when running with a baseline.
    """
    return json.dumps(
        {
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "message": f.message,
                    "feed_id": f.feed_id,
                    "symbol": f.symbol,
                }
                for f in findings
            ],
            "pre_existing_count": pre_existing_count,
        },
        indent=2,
    )
```

In the same file, update the two call sites that invoke `_format_json`. The `--output .json` path at line 275:

```python
    if args.output:
        if args.output.suffix.lower() == ".json":
            content = _format_json(findings)
```

becomes:

```python
    if args.output:
        if args.output.suffix.lower() == ".json":
            content = _format_json(findings, pre_existing_count=pre_existing_count)
```

And the stdout JSON path at line 303:

```python
        if args.format == "json":
            print(_format_json(findings))
```

becomes:

```python
        if args.format == "json":
            print(_format_json(findings, pre_existing_count=pre_existing_count))
```

- [ ] **Step 4: Run CLI tests to confirm they pass**

Run: `pytest tests/test_config_linter_cli.py -v`

Expected: all CLI tests pass.

- [ ] **Step 5: Add a failing test for the VS Code extension parser**

Update `tools/vscode-extension/test/linter.test.ts` to test the new envelope shape. Replace the existing test at lines 33–63 (`it("parses linter JSON output into findings on exit code 0", ...)`) with:

```typescript
  it("parses linter JSON envelope into findings on exit code 0", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    // Linter now emits {"findings": [...], "pre_existing_count": N | null}.
    const sample = JSON.stringify({
      findings: [
        {
          rule_id: "E001",
          severity: "ERROR",
          message: "feedId 327 is duplicated",
          feed_id: 327,
          symbol: null,
        },
      ],
      pre_existing_count: null,
    });
    child.stdout.emit("data", Buffer.from(sample));
    child.emit("close", 0);

    const result = await promise;
    expect(result.error).toBeUndefined();
    expect(result.findings).toHaveLength(1);
    expect(result.findings[0].rule_id).toBe("E001");
    expect(result.findings[0].feed_id).toBe(327);
  });

  it("rejects bare-array stdout as parse_error (regression guard)", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    // Old bare-array shape — no longer accepted.
    child.stdout.emit("data", Buffer.from("[]"));
    child.emit("close", 0);

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error?.kind).toBe("parse_error");
  });
```

- [ ] **Step 6: Run the extension test to confirm it fails**

Run: `cd tools/vscode-extension && npm test -- --run linter.test.ts`

Expected: both new tests FAIL — the parser still expects a bare array.

- [ ] **Step 7: Update the extension parser in `tools/vscode-extension/src/linter.ts`**

In `tools/vscode-extension/src/linter.ts` find the `child.on("close", ...)` block at lines 85–102:

```typescript
    child.on("close", () => {
      // Linter exits 0 (clean) or 1 (errors and/or input failure).
      try {
        const parsed = JSON.parse(stdout);
        if (Array.isArray(parsed)) {
          settle({ findings: parsed as Finding[] });
          return;
        }
      } catch {
        // fall through
      }
      // Non-JSON output → prefer stderr presence over exit code for dispatch.
      const error: LinterError =
        stderr.trim().length > 0
          ? { kind: "crashed", stderr: firstLine(stderr) }
          : { kind: "parse_error", output: stdout.slice(0, 200) };
      settle({ findings: [], error });
    });
```

Replace with:

```typescript
    child.on("close", () => {
      // Linter exits 0 (clean) or 1 (errors and/or input failure).
      // Stdout is a JSON envelope: {"findings": [...], "pre_existing_count": int | null}.
      try {
        const parsed = JSON.parse(stdout);
        if (
          parsed !== null &&
          typeof parsed === "object" &&
          !Array.isArray(parsed) &&
          Array.isArray((parsed as { findings?: unknown }).findings)
        ) {
          settle({
            findings: (parsed as { findings: Finding[] }).findings,
          });
          return;
        }
      } catch {
        // fall through
      }
      // Non-JSON or bare-array output → prefer stderr presence over exit
      // code for dispatch.
      const error: LinterError =
        stderr.trim().length > 0
          ? { kind: "crashed", stderr: firstLine(stderr) }
          : { kind: "parse_error", output: stdout.slice(0, 200) };
      settle({ findings: [], error });
    });
```

- [ ] **Step 8: Run extension tests to confirm everything passes**

Run: `cd tools/vscode-extension && npm test`

Expected: all extension tests pass.

- [ ] **Step 9: Run the Python full test suite as a final regression check**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v`

Expected: all tests pass.

- [ ] **Step 10: Smoke-test the CLI end-to-end against the live config**

Run: `python3 tools/config-linter/config_linter.py --config after.json --format json --no-baseline | python3 -c "import json,sys; p=json.load(sys.stdin); assert isinstance(p, dict) and 'findings' in p and 'pre_existing_count' in p; print('OK', len(p['findings']), 'findings, pre_existing_count=', p['pre_existing_count'])"`

Expected: prints `OK <N> findings, pre_existing_count= None`.

- [ ] **Step 11: Commit**

```bash
pre-commit run --files tools/config-linter/config_linter.py tools/vscode-extension/src/linter.ts tools/vscode-extension/test/linter.test.ts tests/test_config_linter_cli.py
git add tools/config-linter/config_linter.py tools/vscode-extension/src/linter.ts tools/vscode-extension/test/linter.test.ts tests/test_config_linter_cli.py
git commit -m "feat(linter): wrap --format json output in envelope with pre_existing_count

CLI now emits {\"findings\": [...], \"pre_existing_count\": int | null}
for --format json. The bare-array shape is gone; pre_existing_count is
None outside diff mode and an int (possibly zero) in diff mode.
VS Code extension parser updated in lockstep to read response.findings."
```

---

## Task 7 — Documentation updates

**Spec ref:** Items 3, 4, 7 (the doc bits) in design doc.

**Files:**
- Modify: `docs/config_linter.md:173-179` (E013 / E014 notes)
- Modify: `docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md:86`
- Modify: `docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md:893`

This task has no production-code changes; verification is done by reading the diffs. No tests required, but the existing test suites must still pass after the docs are committed (sanity check).

- [ ] **Step 1: Update the E013 note in `docs/config_linter.md`**

Find lines 173–175:

```markdown
## Notes on E013 (Expired COMING_SOON Futures)

A COMING_SOON futures feed is considered expired if **every** `validTo` timestamp found under `marketSchedules[*].benchmarkMapping.*.identifiers[*].validTo` is earlier than the current UTC time. Feeds with no `validTo` identifiers are skipped — E013 only fires when there is evidence that every mapped contract has already rolled off. The fix is usually to flip the feed to `INACTIVE`.
```

Replace with:

```markdown
## Notes on E013 (Expired Futures)

A STABLE or COMING_SOON futures feed is considered expired if **every** `validTo` timestamp found under `marketSchedules[*].benchmarkMapping.*.identifiers[*].validTo` is earlier than the current UTC time. Feeds with no `validTo` identifiers are skipped — E013 only fires when there is evidence that every mapped contract has already rolled off. The fix is to flip the feed to `INACTIVE`. INACTIVE feeds are never flagged.

The message text branches on state (`STABLE futures feed has expired...` vs `COMING_SOON futures feed has expired...`) so operators can tell at a glance whether a mid-lifecycle or pre-launch feed has rolled off.
```

Also update the rule-table row at line 122:

```markdown
| E013 | COMING_SOON futures past every `validTo`                                                              | COMING_SOON futures only                                                      |
```

becomes:

```markdown
| E013 | STABLE or COMING_SOON futures past every `validTo`                                                    | STABLE + COMING_SOON futures                                                  |
```

- [ ] **Step 2: Update the E014 note in `docs/config_linter.md`**

Find lines 177–179:

```markdown
## Notes on E014 (Benchmark Mapping)

Benchmarkable asset types are: `equity`, `fx`, `metal`, `commodity`, `rates`. All other asset types are skipped. The `OVER_NIGHT` session is always exempt since it uses publisher 32 peer comparison rather than Datascope benchmarks.
```

Replace with:

```markdown
## Notes on E014 (Benchmark Mapping)

Benchmarkable asset types are: `equity`, `fx`, `metal`, `commodity`, `rates`. All other asset types are skipped. Every session of a STABLE benchmarkable feed must populate `benchmarkMapping`, including `OVER_NIGHT`. (Even though OVER_NIGHT validation against Datascope is replaced by publisher 32 peer comparison at runtime, the mapping still needs to be present in config.)
```

Also update the rule-table row at line 123:

```markdown
| E014 | STABLE benchmarkable feed missing `benchmarkMapping`                                                  | STABLE, benchmarkable asset types, non-OVERNIGHT                              |
```

becomes:

```markdown
| E014 | STABLE benchmarkable feed missing `benchmarkMapping`                                                  | STABLE, benchmarkable asset types, all sessions                               |
```

- [ ] **Step 3: Update the VS Code extension design doc — exit-code-2 claim**

Find `docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md:86`:

```markdown
The linter exits with code 0 (no errors), 1 (errors), or 2 (baseline file missing/unparseable). All three are valid; only spawn-level failures (`ENOENT`, timeout, malformed stdout) trigger error-handler diagnostics.
```

Replace with:

```markdown
The linter exits with code 0 (no errors) or 1 (errors, baseline file missing, or malformed input). Both are valid; only spawn-level failures (`ENOENT`, timeout, malformed stdout) trigger error-handler diagnostics.
```

- [ ] **Step 4: Update the VS Code extension plan — exit-code-2 claim**

Find `docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md:893`:

```typescript
    child.on("close", (code) => {
      // Linter exits 0 (no errors), 1 (errors), or 2 (baseline missing).
      // Stdout in all three cases should be a JSON array.
      try {
```

Replace with:

```typescript
    child.on("close", (code) => {
      // Linter exits 0 (no errors) or 1 (errors / baseline missing).
      // Stdout in both cases should be a JSON envelope
      // ({"findings": [...], "pre_existing_count": int | null}).
      try {
```

- [ ] **Step 5: Sanity-check the test suite still passes**

Run: `pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v && cd tools/vscode-extension && npm test`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files docs/config_linter.md docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md
git add docs/config_linter.md docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md
git commit -m "docs(linter): update E013/E014 scope and remove stale exit-code-2 claim

E013 now covers STABLE expired futures in addition to COMING_SOON.
E014 now applies to OVER_NIGHT. The VS Code extension spec/plan
previously documented an exit code 2 that the CLI never emitted; align
the docs with reality (0 or 1 only)."
```

---

## Final verification

After all seven tasks land:

- [ ] **Run the entire test suite one more time**

```bash
pytest tests/test_config_lint.py tests/test_config_linter_cli.py -v
cd tools/vscode-extension && npm test
```

Expected: all green.

- [ ] **Smoke-test against the live `after.json` in both modes**

```bash
python3 tools/config-linter/config_linter.py --config after.json --no-baseline
python3 tools/config-linter/config_linter.py --config after.json --no-baseline --format json | python3 -m json.tool > /dev/null
```

Expected: text mode prints findings (or "No issues found"). JSON mode round-trips through `json.tool` cleanly.

- [ ] **Confirm diff-mode is not surprised by E004's renamed message**

```bash
python3 tools/config-linter/config_linter.py --config after.json
```

Expected: any pre-existing E004 findings on `origin/main` should still be suppressed in diff mode (the comparison key excludes message text).

- [ ] **Confirm git log is clean**

```bash
git log --oneline -10
```

Expected: 7 task commits in order, each focused on its task. No unrelated changes mixed in.
