# Config Linter — Per-Session Comparison Refinement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Replace whole-feed-tuple schedule comparison in `check_schedules` with per-session bucketing, fixing the false-positive E011/W003 storm on Equity.US feeds with mixed session sets.

**Architecture:** For each feed, push one entry per `marketSchedules[]` row into a `session_groups` dict keyed by `group_key + (session,)`. Both rules iterate buckets; comparison is bucket-local. Old `_get_schedule_signature` and the unified `group_signatures` are removed.

**Tech Stack:** Python 3, pytest, stdlib only. Pre-commit (black, prettier).

**Reference:** Addendum section in `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-design.md`.

---

## File Structure

| File                                                                                       | Role                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/config_lint.py` (modify)                                                              | Replace `group_signatures` with `session_groups` keyed by `(group_key, session)`. Drop `_get_schedule_signature`. Update E011 / W003 message format. Add private `_format_group_label(group_key)` helper used by both rules. |
| `tests/test_config_lint.py` (modify)                                                       | Add 3 new tests for per-session-set behavior.                                                                                                                                                                                |
| `docs/config_linter.md` (modify)                                                           | Refresh example output, "E011 vs W003" section, finding-message format.                                                                                                                                                      |
| `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md` (replace) | Re-run smoke test; replace file contents with the new finding counts and triage.                                                                                                                                             |

---

## Task 1: Add failing tests for per-session-set behavior

**Files:** Modify `tests/test_config_lint.py`.

- [ ] **Step 1: Append a new test class**

After the existing `class TestW003ExpandedScope`, append:

```python
class TestPerSessionSchedule:
    """Per-session refinement: schedules are compared bucket-by-bucket
    (group_key, session). A feed missing a session is not penalized for
    the omission; it simply doesn't appear in that bucket.
    Refinement addendum to spec 2026-04-28."""

    def test_e011_silent_when_session_sets_differ_but_per_session_agrees(self):
        """A REGULAR-only feed and a REGULAR+OVER_NIGHT feed that agree on
        their REGULAR schedule must NOT trip E011. Their session SETS
        differ but their REGULAR schedules match."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_overnight = {
            "marketSchedule": "America/New_York;2000-2400;",
            "session": "OVER_NIGHT",
        }
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular],
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_overnight],
            ),
            _make_feed(
                3, symbol="Equity.US.GOOG/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_fires_per_session_within_us(self):
        """Per-session drift on REGULAR (with extended sessions also present)
        must fire exactly one E011 tagged with the offending session."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_regular_wrong = {
            "marketSchedule": "America/New_York;0800-1500;",
            "session": "REGULAR",
        }
        nyc_pre = {
            "marketSchedule": "America/New_York;0400-0930;",
            "session": "PRE_MARKET",
        }
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_pre],
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_pre],
            ),
            _make_feed(
                3, symbol="Equity.US.GOOG/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular_wrong, nyc_pre],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
        assert "REGULAR" in errors[0].message

    def test_e011_fires_on_extended_session_drift(self):
        """REGULAR matches across all 3 STABLE feeds, but one feed's
        OVER_NIGHT schedule disagrees with the other two's. E011 fires
        only on OVER_NIGHT, not on REGULAR."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_overnight_a = {
            "marketSchedule": "America/New_York;2000-2400;",
            "session": "OVER_NIGHT",
        }
        nyc_overnight_b = {
            "marketSchedule": "America/New_York;0000-0400;",
            "session": "OVER_NIGHT",
        }
        feeds = [
            _make_feed(
                1, symbol="Equity.US.AAPL/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_overnight_a],
            ),
            _make_feed(
                2, symbol="Equity.US.MSFT/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_overnight_a],
            ),
            _make_feed(
                3, symbol="Equity.US.GOOG/USD", asset_type="equity",
                state="STABLE", schedules=[nyc_regular, nyc_overnight_b],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
        assert "OVER_NIGHT" in errors[0].message
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
source venv/bin/activate
pytest tests/test_config_lint.py::TestPerSessionSchedule -v
```

Expected: 2 of 3 fail (`test_e011_silent_when_session_sets_differ_but_per_session_agrees` and `test_e011_fires_on_extended_session_drift`). The middle one (`test_e011_fires_per_session_within_us`) may pass or fail depending on whether the existing message string contains "REGULAR" — likely fails because today's message is whole-tuple, not per-session.

- [ ] **Step 3: Commit failing tests**

```bash
pre-commit run --files tests/test_config_lint.py
git add tests/test_config_lint.py
git commit -m "test: add failing tests for per-session schedule comparison"
```

---

## Task 2: Refactor `check_schedules` to per-session bucketing

**Files:** Modify `lib/config_lint.py`. Modify `docs/config_linter.md` (small example-output update at the end).

- [ ] **Step 1: Replace the body of `check_schedules`**

Locate the current `check_schedules` function in `lib/config_lint.py` (starts at the line `def check_schedules(feeds: list[dict]) -> list[LintFinding]:`). Replace the entire function with:

```python
def _format_group_label(group_key: tuple) -> str:
    """Render a group key for a finding message.

    Single-part keys read naturally ("commodity"); multi-part keys like
    ("equity", "US") are parenthesized to avoid awkward "X, Y majority"
    phrasing.
    """
    if len(group_key) == 1:
        return str(group_key[0])
    return "(" + ", ".join(str(k) for k in group_key) + ")"


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006, E010, E011, W001, W002, W003: schedule validation rules.

    E011 fires on STABLE feeds only (CI blocker).
    W003 fires on STABLE + COMING_SOON feeds (advisory).
    Both rules use a single session_groups dict keyed by:
        bucket_key = group_key + (session,)
    where group_key is one of:
        - ("equity", listing_prefix)             for equity spot feeds
        - ("equity", listing_prefix, futures_root) for equity futures
        - (asset_type, futures_root)             for non-equity futures
        - (asset_type,)                          for non-equity spot feeds

    A feed contributes one entry per (session, marketSchedule) row in its
    marketSchedules list. A feed missing a session is not penalized; it
    simply does not participate in that bucket.
    """
    findings: list[LintFinding] = []

    # bucket_key (group_key + (session,)) -> list of (fid, sym, schedule_str, state)
    session_groups: dict[tuple, list[tuple[int, str, str, str]]] = {}

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

        # Build the group key for E011 / W003 (without session).
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

        # Push one bucket entry per (session, marketSchedule) row.
        for sched in schedules:
            session = sched.get("session", "")
            sched_str = sched.get("marketSchedule", "")
            bucket_key = group_key + (session,)
            session_groups.setdefault(bucket_key, []).append(
                (fid, sym, sched_str, state)
            )

        # STABLE-only single-feed schedule rules (W001, W002 unchanged)
        if state == "STABLE":
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
                        break

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

    # W003: per-session schedule deviation across STABLE + COMING_SOON.
    for bucket_key, entries in session_groups.items():
        active_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st in ("STABLE", "COMING_SOON")
        ]
        if len(active_entries) <= 1:
            continue

        counts: Counter[str] = Counter(
            sched_str for _, _, sched_str in active_entries
        )
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

    return findings
```

- [ ] **Step 2: Remove the now-unused `_get_schedule_signature` helper**

Locate `_get_schedule_signature` (just above `_extract_timezone`) in `lib/config_lint.py` and delete the entire function. Confirm no other module imports it (`grep -rn "_get_schedule_signature" lib/ tests/` should return zero hits after deletion).

- [ ] **Step 3: Run the new test class and verify it passes**

```bash
source venv/bin/activate
pytest tests/test_config_lint.py::TestPerSessionSchedule -v
```

Expected: all 3 green.

- [ ] **Step 4: Run the full `tests/test_config_lint.py`**

```bash
pytest tests/test_config_lint.py -v
```

Expected: all 118 tests green (115 prior + 3 new).

- [ ] **Step 5: Run the full project test suite**

```bash
pytest tests/ -v
```

Expected: 893 + 3 = 896 tests, all green. No regressions outside `test_config_lint.py`.

- [ ] **Step 6: Update `docs/config_linter.md` example output**

The example output shown in the `## Output Formats > Text` section currently reads:

```
W003  Feed 1775 (Equity.US.XLK/USD): schedule deviates from (equity, US) majority
```

Update to include a session prefix, e.g.:

```
W003  Feed 1775 (Equity.US.XLK/USD): REGULAR schedule deviates from (equity, US) majority
```

Also update the "E011 vs W003" subsection to mention per-session granularity. Find the bullet starting `- **E011 (ERROR)**` and append at the end of its sentence: `Comparison is per-session within a group; a feed missing a session is not penalized.`. Make the equivalent addition to the W003 bullet.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/config_lint.py docs/config_linter.md
git add lib/config_lint.py docs/config_linter.md
git commit -m "feat: per-session schedule comparison for E011/W003

Replaces whole-feed-tuple comparison with per-session bucketing keyed
by (group_key, session). A feed missing a session no longer disagrees
with peers that have it; only same-session schedule strings are
compared. Removes the false-positive E011 storm on Equity.US feeds
with mixed session sets (REGULAR-only vs REGULAR+OVER_NIGHT, etc.)."
```

---

## Task 3: Re-run smoke test and rewrite rollout notes

**Files:** Replace `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md`.

- [ ] **Step 1: Capture the post-refinement finding counts**

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

Capture the counts.

- [ ] **Step 2: Capture per-symbol E011 / W003 findings**

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

Capture the per-symbol output.

- [ ] **Step 3: Replace the rollout-notes file**

Open `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md` and replace its contents with this template, filling in the bracketed `<...>` placeholders from the captured output:

```markdown
# Config Linter Intl Equities — Rollout Notes (2026-04-28, post-refinement)

Captured after `feat/config-linter-intl-equities` merged, including the per-session refinement (addendum in the design doc dated 2026-04-28).

## Finding counts on `after.json`

| Rule                                                                 | Count |
| -------------------------------------------------------------------- | ----- |
| <fill in one row per rule observed in step 1, sorted alphabetically> |

Total findings: <fill in>

## Surviving E011 findings

<paste the E011 list from step 2; one bullet per finding in the form:

- feed `<feedId>` (`<symbol>`): <message excerpt>
  or write "None." if there are zero.>

## Surviving W003 findings

<same format for W003>

## Comparison to pre-refinement smoke test

Pre-refinement finding counts (from the original smoke test, prior to per-session refactor):

- E011: 141 (122 of which were Equity.US cross-session-set tuples)
- W003: 162 (131 of which were Equity.US cross-session-set tuples)

Post-refinement counts: <fill in from step 1>

## Triage decisions

<for each remaining finding (or each cluster of related findings) add a short note: "legit drift — split into sub-feed", "config bug — fix in next config patch", "accept as-is", "needs human triage", etc.>
```

- [ ] **Step 4: Commit**

```bash
pre-commit run --files docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md
git add docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md
git commit -m "docs: rerun smoke test with per-session refinement, rewrite rollout notes"
```

---

## Verification Checklist

- [ ] `pytest tests/ -v` is fully green.
- [ ] `python3 config_linter.py --config after.json` exits 0, OR remaining E011s are documented as legit/needs-triage in the rollout notes.
- [ ] `_get_schedule_signature` is gone from `lib/config_lint.py` and not referenced anywhere.
- [ ] `pre-commit run --all-files` is clean.
- [ ] Branch shows distinct commits for spec addendum, plan, the 3 refinement commits, and the rollout-notes refresh.
