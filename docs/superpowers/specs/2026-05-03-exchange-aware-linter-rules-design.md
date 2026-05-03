# Config Linter — Exchange-Aware Rules

**Date:** 2026-05-03
**Branch:** `feat/exchange-aware-linter-rules`
**Scope:** `lib/config_lint.py`, new `lib/exchange_lint.py`, new `lib/schedule_format.py`, tests, `docs/config_linter.md`, `Config_Linter_Guide.md`

## Problem

`Exchange_Configuration_Guide.md` introduces a new top-level `exchanges[]` array in `after.json`, plus per-feed `exchangeId` and per-session `scheduleOverrides.holidayOverrides[]`. Feeds with `exchangeId` and no inline `marketSchedule` inherit their schedule from the named exchange.

The existing config linter has zero awareness of this feature. Verified by grep against `lib/config_lint.py`: no references to `exchange`, `exchangeId`, `scheduleOverrides`, `assetClass`, `assetSubclass`, `assetSector`, or `holidayOverrides`.

In `staging/after.json` the feature is in an early pilot stage:

| Metric                                                | Count                                                                   |
| ----------------------------------------------------- | ----------------------------------------------------------------------- |
| Total feeds                                           | 12,388                                                                  |
| Active (STABLE/COMING_SOON)                           | 12,189                                                                  |
| Defined exchanges                                     | 2 (`StressTest` id=10001, `TEST_EXCHANGE` id=60001 — both placeholders) |
| Feeds with `exchangeId`                               | 6                                                                       |
| Sessions inheriting from exchange                     | 7                                                                       |
| Sessions with `scheduleOverrides.holidayOverrides`    | 0                                                                       |
| Distinct REGULAR schedule strings across active feeds | 41                                                                      |
| Distinct REGULAR schedule templates (timezone+days)   | 23                                                                      |

The pilot is small now, but the rollout plan in the Guide explicitly steps from "subset of a subset" → "major schedule groups (start with US equities, ~1,400 feeds)" → "by asset class". Without linter coverage, malformed exchange configs and migration mistakes during the major-group migrations will pass review silently.

## Solution

Add 6 rules grouped as **Option B** of the brainstorming round (3 errors + 3 warnings, dropping the more expensive "schedule equivalence" and "diff-mode dependency" rules to a possible v2):

| Rule | Severity | Concern                                                                                            |
| ---- | -------- | -------------------------------------------------------------------------------------------------- |
| E019 | ERROR    | feed references `exchangeId` not defined in `exchanges[]`                                          |
| E020 | ERROR    | session has neither inline `marketSchedule` nor a resolvable inherited schedule                    |
| E021 | ERROR    | two exchanges share the same `(name, assetClass, assetSubclass, assetSector)` tuple                |
| W010 | WARNING  | feed session has both inline `marketSchedule` and `exchangeId` (inline silently shadows exchange)  |
| W011 | WARNING  | feed has `exchangeId` but every session has an inline `marketSchedule` (`exchangeId` is dead code) |
| E022 | ERROR    | invalid syntax in `scheduleOverrides.holidayOverrides[]` token                                     |

The rules are deliberately **structural** — they validate references, uniqueness, and syntax — not semantic ("this exchange should be NASDAQ" is out of scope; the canonical exchange list is still being defined elsewhere).

### Architecture

The existing `lib/config_lint.py` is 1,174 lines, already past the `coding-style.md` 800-line guidance. Rather than extend it further, exchange rules go into a new module. A small reusable helper handles the `holidayOverrides` token format.

```
lib/
  config_lint.py          ← orchestrator + existing rules; imports exchange_lint
  exchange_lint.py        ← NEW: 6 rules + internal exchange-index helper
  schedule_format.py      ← NEW: validate_holiday_token (reusable)
tests/
  test_exchange_lint.py   ← NEW: rule-by-rule coverage
  test_schedule_format.py ← NEW: token validator coverage
  test_config_lint.py     ← amended with one orchestrator integration test
docs/
  config_linter.md        ← updated rule tables (+ E019–E022, W010–W011)
Config_Linter_Guide.md    ← updated rule tables to match
```

### Public surfaces

`lib/schedule_format.py`:

```python
def validate_holiday_token(token: str) -> str | None:
    """Return None if token matches `MMDD/{C|O|HHMM-HHMM}`, else a short
    reason string ('unknown kind X', 'invalid month 13', 'Feb 30 not a real
    date', 'malformed time range', 'reversed time range')."""
```

Pure function. No exceptions. Reason strings are embedded into the linter finding message.

`lib/exchange_lint.py`:

```python
def check_exchanges(
    feeds: list[dict],
    exchanges: list[dict],
) -> list[LintFinding]:
    """Run E019, E020, E021, W010, W011, E022. Returns unordered findings."""
```

Single entry point. Internally builds `exchange_by_id: dict[Any, dict]` and `session_set_by_id: dict[Any, set[str]]` once, reuses across rules. `Any` keying (rather than `int`) so type-mismatched ids surface naturally as dangling references in E019.

Orchestrator change in `lib/config_lint.py` (~3 lines):

```python
from lib.exchange_lint import check_exchanges
# ... inside lint_config(...) and lint_config_diff_with_count(...):
findings.extend(check_exchanges(feeds, config.get("exchanges", []) or []))
```

`exchanges` is optional. Configs without the key produce an empty list and exchange-defining rules (E021) become no-ops. Feed-keyed rules (E019, W010, W011) still run — a feed with `exchangeId` set when there is no `exchanges[]` array correctly fires E019.

## Per-rule specifications

Throughout this section, "feed has a **resolvable** `exchangeId`" means: `feed.exchangeId` is set, and is a value present in `{e["exchangeId"] for e in exchanges}` — i.e., E019 did not fire for this feed. This is shorthand for the precondition shared by E020 case 2, W010, and W011.

### E019 — dangling `exchangeId` reference

- **Trigger** (per feed): `feed.exchangeId` is set (any non-null value) **and** is not present in `{e["exchangeId"] for e in exchanges}`.
- **Message**: `feed references exchangeId {eid!r} which is not defined in exchanges[]`
- **Fields**: `feed_id`, `symbol`. Value of `eid` is rendered with `repr()` so `"1"` (string) and `1` (int) produce distinguishable messages, surfacing type errors as a side effect.
- **Suppression effect**: when E019 fires for a feed, **E020 and W010 are skipped on that feed**. Reporting downstream effects of a broken reference is noise; E019 names the root cause.

### E020 — session has no schedule source

- **Trigger** (per session, only if E019 did not fire for the feed): session has no non-empty `marketSchedule` value, **and** one of:
  - **Case 1**: feed has no `exchangeId`
  - **Case 2**: feed has `exchangeId` resolving to a defined exchange, but that exchange has no session entry whose `session` field equals this session's `session` field
- **Messages**:
  - Case 1: `feed session {session} has no marketSchedule and feed has no exchangeId — no schedule source`
  - Case 2: `feed session {session} has no marketSchedule and exchange {eid} does not define a {session} session`
- **Fields**: `feed_id`, `symbol`. Empty string `""` for `marketSchedule` is treated as missing (Python falsy check).

### E021 — duplicate exchange tuple

- **Trigger** (across `exchanges[]`): two or more entries share the same 4-tuple `(name, assetClass, assetSubclass, assetSector)` after normalizing missing keys to their `…UNSPECIFIED` sentinel:
  - `assetClass` defaults to `EXCHANGE_ASSET_CLASS_UNSPECIFIED`
  - `assetSubclass` defaults to `EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED`
  - `assetSector` defaults to `EXCHANGE_ASSET_SECTOR_UNSPECIFIED`
  - `name` has no default; if `name` is missing on an entry, that entry is **excluded** from E021 (a separate rule could flag missing required exchange fields, but that is out of scope here).
- **Message**: `duplicate exchange tuple (name={name}, class={class}, subclass={subclass}, sector={sector}) on exchangeIds [{ids…}]`
- **Fields**: `feed_id=None`, `symbol=None` (this is an exchange-array rule).
- **Cardinality**: one finding **per duplicate group**, not per pair. A 3-way duplicate emits one finding listing all three `exchangeId`s.

### W010 — inline `marketSchedule` shadows exchange

- **Trigger** (per session): feed has a resolvable `exchangeId` (E019 did not fire) **and** session has a non-empty inline `marketSchedule` **and** the referenced exchange defines a session with the matching `session` name.
- **Message**: `feed session {session} has both inline marketSchedule and exchangeId {eid}; inline takes priority — exchange schedule unused for this session`
- **Fields**: `feed_id`, `symbol`.
- **Suppression effect**: skipped on a feed where W011 fires (W011 is the cleaner summary).

### W011 — `exchangeId` is dead code

- **Trigger** (per feed): feed has a resolvable `exchangeId` (E019 did not fire) **and** the feed has at least one session **and** every session has a non-empty inline `marketSchedule`.
- **Message**: `feed has exchangeId {eid} but every session has an inline marketSchedule — exchangeId is unused`
- **Fields**: `feed_id`, `symbol`.
- **Edge case**: a feed with `exchangeId` and zero sessions does **not** fire W011 (vacuous truth). Other existing rules cover empty-`marketSchedules` cases.

### E022 — invalid `holidayOverrides` syntax

- **Trigger** (per token): a session's `scheduleOverrides.holidayOverrides[]` contains a token for which `validate_holiday_token` returns a non-`None` reason string.
- **Message**: `holidayOverrides entry {token!r} has invalid syntax: {reason}`
- **Fields**: `feed_id`, `symbol`.
- **Cardinality**: one finding **per bad token** (a session with three typos produces three findings — pinpoints each).
- **Edge cases**:
  - `scheduleOverrides` present but `holidayOverrides` missing or `null` or empty list → no finding.
  - `holidayOverrides` is not a list (e.g. a string or dict) → one E022 with message `holidayOverrides must be a list of strings, got {type}`.
  - Tokens are validated even when the session has an inline `marketSchedule` (a v2 rule could flag "overrides will be ignored because inline takes priority"; out of scope here — typos are typos regardless).

### Suppression order summary

```
E019 (dangling)  →  suppresses E020 + W010 on the same feed
W011 (dead code) →  suppresses W010 on the same feed
```

All other interactions are independent. A single feed can simultaneously emit, for example, one E019 + one E022 + one W011 — none overlap.

## `lib/schedule_format.py` token grammar

`validate_holiday_token` accepts strings of the form:

```
MMDD/<kind>
where:
  MM = 01..12
  DD = a real day number for that month (01..28/29/30/31; 0229 always
       considered valid since it is a known holiday format that may
       apply on leap years)
  <kind> = "C" | "O" | "HHMM-HHMM"

For the time-range form:
  start: HHMM with HH in 00..23 and MM in 00..59
  end:   HHMM with HH in 00..24 and MM in 00..59;
         if HH=24 then MM must be 00 (24:00 represents end-of-day,
         matching the boundary used in feed-level marketSchedule strings
         like "1700-2400" or "2000-2400")
  end > start as 4-digit integer; equal or reversed ranges fail with
  "reversed time range"
```

Reason strings (used in E022 messages):

| Reason                            | Triggered by                                         |
| --------------------------------- | ---------------------------------------------------- |
| `expected MMDD/{C\|O\|HHMM-HHMM}` | shape doesn't match the basic regex                  |
| `unknown kind {kind!r}`           | kind is not `C`, `O`, or a time-range                |
| `invalid month {mm}`              | month not in 01..12                                  |
| `invalid day {dd} for month {mm}` | day out of range for the month (e.g. `0230`, `0431`) |
| `malformed time range {range!r}`  | time range portion fails sub-regex                   |
| `reversed time range {range!r}`   | end ≤ start                                          |

The function does no I/O and raises no exceptions. It is intentionally easy to call from tests (table-driven parametrization).

## Testing strategy

Per global rule (`testing.md`): TDD, ≥80% coverage, unit + integration tests.

### `tests/test_schedule_format.py`

Table-driven `pytest.mark.parametrize` against `validate_holiday_token`.

- **Valid tokens** (assert `result is None`): `0101/C`, `0619/O`, `0703/0930-1300`, `1225/C`, `0229/C`.
- **Invalid kind**: `0101/X`, `0101/Z`, `0101/`.
- **Invalid month**: `1340/C`, `0001/C`, `1301/C`.
- **Invalid day**: `0230/C`, `0431/C`, `0532/C`, `0100/C`.
- **Malformed shape**: `315/C` (3-digit MMDD), `01015/C` (5-digit), `0101` (no kind), `0101C` (no slash), `''`.
- **Time range edge cases**: `0703/0930-1300` (valid), `0703/2400-0000` (reversed), `0703/0930-0930` (zero-length), `0703/0930-1` (malformed), `0703/0930-2500` (invalid hour).

### `tests/test_exchange_lint.py`

One `class Test{Rule}` per rule, matching the existing `tests/test_config_lint.py` style (dict-literal fixtures inline, no JSON files).

For each rule:

1. **Happy path** — rule does not fire on a clean config.
2. **Each trigger branch**:
   - E020: Case 1 (no exchangeId) and Case 2 (exchange missing session).
   - E022: list of strings with bad tokens; non-list `holidayOverrides`; empty list / null / missing key.
3. **Suppression interactions** (dedicated tests):
   - E019 on a feed suppresses E020 and W010 for that same feed.
   - W011 on a feed suppresses W010 on that same feed.
4. **Cardinality**:
   - E021 with a 3-way duplicate group emits one finding listing all three `exchangeId`s.
   - E022 session with three bad tokens emits three findings.
5. **Edge cases from the per-rule sections**:
   - W011 with zero sessions does not fire.
   - E020 treats `marketSchedule: ""` as missing.
   - E021 normalizes missing classification keys to `…UNSPECIFIED` (`{name}` vs `{name, …UNSPECIFIED}` is a duplicate).
   - E019 on a string `exchangeId` (`"1"`) renders the message with `repr()` so the type mistake is visible.

### Integration test in `tests/test_config_lint.py`

One ~15-line test confirming that `lint_config(config)` on a config that triggers (say) E019 returns a findings list containing that rule_id — i.e. the orchestrator wiring is in place. Existing 159 tests must still pass; legacy fixtures have neither `exchanges[]` nor `exchangeId` so the new rules see empty inputs and stay silent.

### TDD ordering

1. `test_schedule_format.py` → implement `lib/schedule_format.py`.
2. For each of E019, E020, E021, W010, W011, E022 (in that order): write tests in `test_exchange_lint.py` → implement that rule in `lib/exchange_lint.py`.
3. Wire orchestrator in `lib/config_lint.py` → add integration test in `test_config_lint.py`.

## Documentation updates

- `docs/config_linter.md` — extend the rule reference tables (errors and warnings sections) with E019–E022 and W010–W011 entries, matching the existing column structure (ID / Rule / Scope).
- `Config_Linter_Guide.md` — extend the rule tables in the "Errors" and "Warnings" sections to mirror.
- A short narrative paragraph in `Config_Linter_Guide.md` introducing the exchange-aware rules block, with a one-line description of each rule and a reference to `Exchange_Configuration_Guide.md`.

No new top-level documentation file. Keep the linter rules documented in the existing two locations.

## Out of scope (deferred to potential v2)

The brainstorming round considered and explicitly excluded these from v1:

- **W012**: exchange tuple uses `…UNSPECIFIED` for all three classifications (likely a placeholder forgotten by the author). Not a correctness issue, just style.
- **W013**: feed migrated from inline-with-content to inheritance — resolved schedule differs from prior inline content (catches accidental schedule drift). Requires a schedule-string parser/resolver, which is non-trivial; deferred until inline schedules are validated at a structural level too.
- **E023**: full `marketSchedule` string parse validation (timezone, day spec, holiday list inside the schedule string). The existing linter treats the full string as opaque; introducing structural validation has cross-cutting consequences for E011 / W003 grouping and merits its own design round.
- **E024 (diff-mode)**: exchange removed from `exchanges[]` while feeds still reference it. Requires before+after baseline awareness; the existing diff orchestrator (`lint_config_diff_with_count`) supports this in principle but the rule itself wants explicit baseline-vs-after comparison logic that is heavier than the within-config rules above.
- **W014**: feed has `scheduleOverrides` on a session that also has an inline `marketSchedule` (overrides ignored at runtime). E022 already validates the syntax of those tokens regardless; flagging "ignored at runtime" is an interaction warning that mirrors W010 thematically but addresses a different surface.

These are listed so future work can pick them up without re-discovery; v1 ships only the six rules in the Solution table.

## References

- `Exchange_Configuration_Guide.md` — feature description, schema, rollout plan.
- `Config_Linter_Guide.md` — current rule reference; will be updated to include the new rules.
- `docs/config_linter.md` — rule documentation; will be updated.
- `lib/config_lint.py` — orchestrator and existing rules.
- `staging/after.json` — pilot snapshot used to confirm the rules don't false-positive on current data.
