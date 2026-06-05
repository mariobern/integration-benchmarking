# Session-Only Publisher Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `lazer_dq/apply_allowed_to_config.py` and `tools/edit-config/` to the new Lazer config format, where publisher lists live only inside `marketSchedules` session entries (no feed-level `allowedPublisherIds`) and session-level `minPublishers` exists only on `Equity.US.*` feeds.

**Architecture:** Both tools keep their raw-text-surgery design (edits splice into the original JSON text, preserving formatting). A format guard rejects old-format configs at load. apply_allowed loses its hk/us split — session rows from the workbook drive everything; `overwrite_session`/`add_session` gain a `write_min` flag (US-equity only). edit-config's op classes lose their `top_level` publisher targets; the text applier becomes sequential (one change at a time, re-locating spans) so it can insert missing keys into session entries.

**Tech Stack:** Python 3 (stdlib + openpyxl + pytest). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-05-session-only-publisher-editing-design.md`

---

## Context for the engineer (read first)

- **Run everything from the repo root** (`/Users/mariobernardi/Documents/GitHub/integration-benchmarking`). `python` does not exist on this machine — always use `python3`.
- **Test commands:**
  - apply_allowed suite: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
  - edit-config suite: `python3 -m pytest tools/edit-config/tests -v` (its `conftest.py` puts `tools/edit-config` on `sys.path`)
- **Before every commit:** `pre-commit run --files <changed files>` (hooks: black, prettier, whitespace fixers). If a hook modifies a file, `git add` it again.
- **New-format facts** (verified against `lazer_update.json`): no feed in the new format has a feed-level `allowedPublisherIds`; every feed has a `REGULAR` session entry; every schedule entry has a `session` key; no session list is `null` or `[]`; session-level `minPublishers` appears only on `Equity.US.*` feeds; feed-level `minPublishers` exists on every feed.
- **Two separate text-surgery layers exist on purpose** (they are not shared): `lib/json_surgery.py` (used by apply_allowed) and `tools/edit-config/edit_config_lib/config_text_surgery.py`. Keep duplication; do not cross-import.
- **Field order inside a session entry is canonical:** `allowedPublisherIds`, `benchmarkMapping`, `marketSchedule`, `minPublishers`, `session`. Inserted `allowedPublisherIds` goes right after the opening `{`; inserted `minPublishers` goes on its own line just before the `"session"` key.
- **Known-red window:** Tasks 5–8 change `tools/edit-config` semantics in stages; the full edit-config suite is only green again at the end of Task 8. Specifically: Task 5's applier drops top-level publisher support while the ops (rewritten in Task 7) still emit top-level publisher changes, so `test_edit_config_cli.py`'s apply-path tests are red from Task 5 until Task 8. Each task's "Run" steps name exactly which test files must pass at that point — run only those, not the full suite.

## File structure

| File                                                                                                                                                   | Change                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| `lazer_dq/apply_allowed_to_config.py`                                                                                                                  | `write_min` param, format guard, unified session path, delete `set_top_level_allowed`/`--asset-class`        |
| `lazer_dq/tests/test_apply_allowed_to_config.py`                                                                                                       | migrate `_feed` helper to new format; rewrite flow assertions; new guard + hk tests                          |
| `tools/edit-config/edit_config_lib/config_text_surgery.py`                                                                                             | add `insert_field_after_open_brace`, `insert_field_before_session`, `find_marketschedules_end`               |
| `tools/edit-config/edit_config_lib/config_editor.py`                                                                                                   | sequential applier with insert support; format guard helper unchanged here (guard lives in `edit_config.py`) |
| `tools/edit-config/edit_config_lib/config_ops.py`                                                                                                      | rewrite AddPublisher/RemovePublisher/min-ops; add `is_us_equity`; delete `has_session_publishers`            |
| `tools/edit-config/edit_config_lib/config_diff.py`                                                                                                     | render `before=None` as `(absent)`                                                                           |
| `tools/edit-config/edit_config.py`                                                                                                                     | format guard in `main()`                                                                                     |
| `tools/edit-config/tests/fixtures/after_sample.json`                                                                                                   | rewrite to new format                                                                                        |
| `tools/edit-config/tests/fixtures/hk_sample.json`                                                                                                      | strip feed-level `allowedPublisherIds`                                                                       |
| `tools/edit-config/tests/fixtures/edits_basic.yaml`                                                                                                    | drop `session: NONE` from the publisher op                                                                   |
| `tools/edit-config/tests/test_config_text_surgery.py`, `test_config_ops.py`, `test_config_editor.py`, `test_config_diff.py`, `test_edit_config_cli.py` | new/updated tests                                                                                            |
| `docs/apply_allowed_to_config.md`, `docs/edit_config.md`, `CLAUDE.md`, `CHANGELOG.md`                                                                  | documentation                                                                                                |

---

## Part A — `lazer_dq/apply_allowed_to_config.py`

### Task 1: `write_min` parameter on `overwrite_session` / `add_session`

Session-level `minPublishers` is a us-equities-only concept. These two writers gain a `write_min: bool = True` keyword so non-US feeds never gain a session `minPublishers` key. Default `True` keeps current behavior, so this task is green standalone.

**Files:**

- Modify: `lazer_dq/apply_allowed_to_config.py` (functions `overwrite_session` ~line 261, `add_session` ~line 301)
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing tests**

Append after `test_add_session_into_empty_marketschedules` (~line 236):

```python
def test_overwrite_session_write_min_false_never_touches_min():
    # Non-US feeds take minPublishers at the feed level only; write_min=False
    # must neither insert nor update a session-level minPublishers.
    block = (
        '{ "marketSchedules": [ {\n'
        '          "allowedPublisherIds": [ 1, 2, 3 ],\n'
        '          "session": "REGULAR"\n'
        "        } ] }"
    )
    out = overwrite_session(block, "REGULAR", [24, 35, 42], write_min=False)
    reg = json.loads(out)["marketSchedules"][0]
    assert reg["allowedPublisherIds"] == [24, 35, 42]
    assert "minPublishers" not in reg


def test_overwrite_session_write_min_false_inserts_ids_only():
    # hk-equities COMING_SOON shape: REGULAR entry with neither field.
    block = (
        '{ "marketSchedules": [\n'
        "        {\n"
        '          "marketSchedule": "X",\n'
        '          "session": "REGULAR"\n'
        "        }\n"
        "      ] }"
    )
    out = overwrite_session(block, "REGULAR", [41, 69], write_min=False)
    reg = json.loads(out)["marketSchedules"][0]
    assert reg["allowedPublisherIds"] == [41, 69]
    assert "minPublishers" not in reg


def test_add_session_write_min_false_omits_min():
    block = '{ "marketSchedules": [] }'
    out = add_session(block, "REGULAR", [24, 35], None, write_min=False)
    sess = json.loads(out)["marketSchedules"][0]
    assert sess["allowedPublisherIds"] == [24, 35]
    assert "minPublishers" not in sess
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k write_min -v`
Expected: 3 FAILED with `TypeError: ... unexpected keyword argument 'write_min'`

- [ ] **Step 3: Implement**

In `overwrite_session`, change the signature and guard the minPublishers half:

```python
def overwrite_session(
    block: str, session: str, ids: list[int], write_min: bool = True
) -> str:
    """Within a feed block, set a session's allowedPublisherIds (and, when
    write_min is True, its minPublishers).

    Replaces each field in place when present; inserts it after the session's
    opening '{' when absent. Many COMING_SOON session entries ship without an
    allowedPublisherIds (and sometimes minPublishers) key, so the insert path
    is the common case on real configs.

    Session-level minPublishers is a us-equities-only concept in the new
    config format; callers pass write_min=False for every other asset class
    so the entry never gains (or changes) a minPublishers key.
    """
    bounds = find_session_block(block, session)
    if bounds is None:
        return block
    s, e = bounds
    sblock = block[s:e]

    pub_pat = r'"allowedPublisherIds":\s*(\[[^\]]*\]|null)'
    pub_repl = f'"allowedPublisherIds": {_ids_inline(ids)}'
    if re.search(pub_pat, sblock):
        sblock = re.sub(pub_pat, pub_repl, sblock, count=1)
    else:
        sblock = _insert_field_after_open_brace(sblock, pub_repl + ",")

    if write_min:
        min_pub = get_min_publishers(session, len(ids))
        min_pat = r'"minPublishers":\s*\d+'
        min_repl = f'"minPublishers": {min_pub}'
        if re.search(min_pat, sblock):
            sblock = re.sub(min_pat, min_repl, sblock, count=1)
        else:
            # Place a new minPublishers between marketSchedule and session,
            # matching the canonical entry order.
            sblock = _insert_field_before_session(sblock, min_repl + ",")

    return block[:s] + sblock + block[e:]
```

(The `min_pub = get_min_publishers(...)` line moves inside the `if write_min:` block; delete the old module-level computation at the top of the function.)

In `add_session`, change the signature and make the `minPublishers` entry conditional:

```python
def add_session(
    block: str,
    session: str,
    ids: list[int],
    benchmark_mapping,
    write_min: bool = True,
) -> str:
    """Insert a new session entry before the closing ']' of marketSchedules.

    benchmark_mapping is the dict copied from the feed's REGULAR session (or
    None). write_min=False (non-US-equity feeds) omits the session-level
    minPublishers key entirely.
    """
    base_indent = _detect_session_indent(block)
    entry: dict = {"allowedPublisherIds": ids}
    if benchmark_mapping is not None:
        entry["benchmarkMapping"] = benchmark_mapping
    entry["marketSchedule"] = SCHEDULE_TEMPLATES[session]
    if write_min:
        entry["minPublishers"] = get_min_publishers(session, len(ids))
    entry["session"] = session
```

(The rest of `add_session` is unchanged.)

- [ ] **Step 4: Run the whole file's tests**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: ALL PASS (default `write_min=True` preserves existing behavior)

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(apply-allowed): write_min flag on session writers (US-only session minPublishers)"
```

### Task 2: Unified session-only `apply_summary_to_config` + CLI

Delete the top-level roster write and the hk/us split. Migrate the test helper to the new format in the same task (the two cannot be separated and stay green).

**Files:**

- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Migrate the test helpers to the new format**

Replace the `_feed` helper (~line 248) with:

```python
def _feed(feed_id, state, sessions, symbol=None, session_min=True):
    """New-format feed: publishers live ONLY in session entries.

    sessions: list of (name, allowed_or_None); None omits the key (the real
    COMING_SOON shape). session_min=True adds a session minPublishers
    (the Equity.US.* shape); the default symbol is a US-equity symbol so
    session-min expectations hold unless a test overrides it.
    """
    ms = []
    for name, allowed in sessions:
        entry = {}
        if allowed is not None:
            entry["allowedPublisherIds"] = allowed
        entry["benchmarkMapping"] = _BENCH
        entry["marketSchedule"] = "TPL"
        if session_min:
            entry["minPublishers"] = 3
        entry["session"] = name
        ms.append(entry)
    return {
        "feedId": feed_id,
        "marketSchedules": ms,
        "minPublishers": 3,
        "state": state,
        "symbol": symbol or f"Equity.US.S{feed_id}/USD",
    }
```

Then update every `_feed(...)` call in the file: **delete the `top=[...]` argument** (it no longer exists). Affected calls: `test_apply_promotes_coming_soon_regular_only`, `test_apply_adds_missing_session_to_stable_feed`, `test_apply_leaves_existing_stable_session_untouched`, `test_apply_skips_no_data_feed`, `test_apply_warns_on_missing_feed`, `test_apply_filters_lazer_and_warns`, `test_apply_does_not_promote_when_all_publishers_filtered`, `test_apply_does_not_promote_fewer_than_three_publishers`, `test_apply_promotes_with_exactly_three_publishers`, `test_apply_min_promote_publishers_param_lowers_gate`, `_real_config`.

- [ ] **Step 2: Rewrite the flow-test assertions to session-only expectations**

In `test_apply_promotes_coming_soon_regular_only` delete the line
`assert feed["allowedPublisherIds"] == [24, 35, 42]` and add
`assert "allowedPublisherIds" not in feed` after the `minPublishers == 2` assert (the top-level min write is KEPT).

In `test_apply_adds_missing_session_to_stable_feed` replace

```python
    assert feed["allowedPublisherIds"] == [11, 12, 24, 35]  # folded union
    assert feed["minPublishers"] == 3  # top-level untouched on STABLE
```

with

```python
    assert "allowedPublisherIds" not in feed  # no feed-level roster created
    assert feed["minPublishers"] == 3  # top-level untouched on STABLE
```

In `test_apply_filters_lazer_and_warns` replace
`assert feed["allowedPublisherIds"] == [24, 35, 42]` with
`assert "allowedPublisherIds" not in feed`.

In `test_apply_promotes_with_exactly_three_publishers` replace
`assert feed["allowedPublisherIds"] == [24, 35, 42]` with
`assert feed["marketSchedules"][0]["allowedPublisherIds"] == [24, 35, 42]`.

In `test_apply_min_promote_publishers_param_lowers_gate` replace
`assert feed["allowedPublisherIds"] == [24, 35]` with
`assert feed["marketSchedules"][0]["allowedPublisherIds"] == [24, 35]`.

In `test_apply_promotion_drops_sessions_without_publishers` (bottom of file): rewrite the inline `feed` dict to new format — delete its `"allowedPublisherIds": [1, 2, 3],` feed-level line, and change the three extended-session entries from `"allowedPublisherIds": None` to entries WITHOUT the key:

```python
    feed = {
        "feedId": 2300,
        "marketSchedules": [
            {
                "allowedPublisherIds": [1],
                "benchmarkMapping": _BENCH,
                "minPublishers": 3,
                "session": "REGULAR",
            },
            {"minPublishers": 1, "session": "PRE_MARKET"},
            {"minPublishers": 1, "session": "POST_MARKET"},
            {"minPublishers": 1, "session": "OVER_NIGHT"},
        ],
        "minPublishers": 3,
        "state": "COMING_SOON",
        "symbol": "Equity.US.S2300/USD",
    }
```

and replace `assert f["allowedPublisherIds"] == [19, 41]` with `assert "allowedPublisherIds" not in f`.

In `test_cli_real_run_writes_and_backs_up` replace

```python
    assert feed["allowedPublisherIds"] == [24, 35, 42]
```

with

```python
    reg = next(s for s in feed["marketSchedules"] if s["session"] == "REGULAR")
    assert reg["allowedPublisherIds"] == [24, 35, 42]
```

- [ ] **Step 3: Replace the hk test, delete the dead-function test**

Delete `test_apply_write_session_fields_false_sets_top_level_only` and `test_set_top_level_allowed_replaces_array_before_marketschedules` entirely. In their place (where the hk test was) add:

```python
def test_apply_hk_promotion_writes_session_ids_feed_level_min_only():
    # hk-equities shape: COMING_SOON, REGULAR entry without allowedPublisherIds
    # or minPublishers; the symbol is NOT Equity.US.*, so session-level
    # minPublishers must never be written.
    feed = {
        "feedId": 884,
        "marketSchedules": [
            {
                "benchmarkMapping": _BENCH,
                "marketSchedule": "Asia/Hong_Kong;0930-1200,C",
                "session": "REGULAR",
            }
        ],
        "minPublishers": 3,
        "state": "COMING_SOON",
        "symbol": "Equity.HK.0700-HK/HKD",
    }
    raw = json.dumps({"feeds": [feed]}, indent=2)
    summary = {
        884: {
            "aggregate": [41, 69],
            "sessions": {
                "REGULAR": [41, 69],
                "PRE_MARKET": None,
                "POST_MARKET": None,
                "OVER_NIGHT": None,
            },
        }
    }

    out, stats = apply_summary_to_config(raw, summary, min_promote_publishers=2)
    f = {x["feedId"]: x for x in json.loads(out)["feeds"]}[884]

    assert f["state"] == "STABLE"
    assert f["minPublishers"] == 2  # feed-level minPublishers set on promotion
    reg = f["marketSchedules"][0]
    assert reg["allowedPublisherIds"] == [41, 69]  # session list written
    assert "minPublishers" not in reg  # session min NEVER written for non-US
    assert "allowedPublisherIds" not in f  # no feed-level roster created
    assert stats["promoted"] == 1


def test_apply_us_promotion_writes_session_min():
    # Equity.US.* counterpart: session minPublishers IS written.
    raw = _config_with(
        [_feed(110, "COMING_SOON", [("REGULAR", None)], session_min=False)]
    )
    summary = {
        110: {
            "aggregate": [24, 35, 42],
            "sessions": {
                "REGULAR": [24, 35, 42],
                "PRE_MARKET": None,
                "POST_MARKET": None,
                "OVER_NIGHT": None,
            },
        }
    }
    out, _stats = apply_summary_to_config(raw, summary)
    f = {x["feedId"]: x for x in json.loads(out)["feeds"]}[110]
    reg = f["marketSchedules"][0]
    assert reg["allowedPublisherIds"] == [24, 35, 42]
    assert reg["minPublishers"] == 2  # 3 pubs => REGULAR low-count rule
```

Also update the import block at ~line 105: remove `set_top_level_allowed` from the `from lazer_dq.apply_allowed_to_config import (...)` list (keep `set_top_level_min_publishers`, `overwrite_session`, `add_session`, `SCHEDULE_TEMPLATES`).

In `test_set_top_level_min_publishers_targets_field_after_marketschedules`, delete the `'{\n      "allowedPublisherIds": [ 1 ],\n'` line from the block literal (new-format block has no feed-level list); the rest of the test is unchanged.

- [ ] **Step 4: Run to verify the expected failures**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: the rewritten flow tests FAIL (production code still writes the top-level roster, still has `write_session_fields`); helper/unit tests PASS.

- [ ] **Step 5: Rewrite the production code**

In `lazer_dq/apply_allowed_to_config.py`:

1. Delete the constants `SESSION_LEVEL_ASSET_CLASSES` and `KNOWN_ASSET_CLASSES` (~lines 49–59) and the function `set_top_level_allowed` (~lines 169–187). Add in their place:

```python
# Session-level minPublishers is a us-equities-only concept in the new config
# format; every other asset class takes minPublishers at the feed level only.
US_EQUITY_SYMBOL_PREFIX = "Equity.US."
```

2. Replace `apply_summary_to_config` with:

```python
def apply_summary_to_config(
    raw: str,
    summary: dict[int, dict],
    log=None,
    min_promote_publishers: int = MIN_PROMOTE_PUBLISHERS,
) -> tuple[str, dict]:
    """Apply the parsed summary to the raw config text.

    Returns (new_raw, stats). `log` is an optional callable(str) for per-feed
    lines; defaults to a no-op. `min_promote_publishers` is the redundancy gate:
    a COMING_SOON feed is promoted only if at least this many publishers survive
    filtering.

    Publisher lists are written ONLY into marketSchedules session entries —
    the new config format has no feed-level allowedPublisherIds. Session-level
    minPublishers is written only for Equity.US.* feeds; every other asset
    class takes minPublishers at the feed level only. The feed-level
    minPublishers is still set to 2 on promotion.

    Implements the spec decision matrix.
    """
    if log is None:
        log = lambda _msg: None  # noqa: E731

    data = json.loads(raw)
    feed_index = {f["feedId"]: f for f in data["feeds"]}

    stats = {
        "promoted": 0,
        "sessions_added": 0,
        "sessions_removed": 0,
        "skipped_no_data": 0,
        "skipped_too_few_publishers": 0,
        "skipped_stable_no_change": 0,
        "skipped_state": 0,
        "not_found": [],
        "filtered_any": False,
    }

    for feed_id, fa in summary.items():
        if not fa["aggregate"]:
            stats["skipped_no_data"] += 1
            log(f"  SKIP (no data): feedId={feed_id}")
            continue

        feed = feed_index.get(feed_id)
        if feed is None:
            stats["not_found"].append(feed_id)
            log(f"  WARNING (not found): feedId={feed_id}")
            continue

        state = feed.get("state")
        if state not in ("COMING_SOON", "STABLE"):
            stats["skipped_state"] += 1
            log(f"  SKIP (state={state}): feedId={feed_id}")
            continue

        bounds = find_feed_block(raw, feed_id)
        if bounds is None:
            stats["not_found"].append(feed_id)
            log(f"  WARNING (block not found): feedId={feed_id}")
            continue

        start, end = bounds
        block = raw[start:end]
        existing_sessions = {s.get("session") for s in feed.get("marketSchedules", [])}
        bench = _regular_benchmark_mapping(feed)
        write_min = feed.get("symbol", "").startswith(US_EQUITY_SYMBOL_PREFIX)

        if state == "COMING_SOON":
            # First pass: compute filtered per-session lists + union. No edits yet,
            # so a feed rejected by the redundancy gate below leaves `block`
            # untouched and never over-counts sessions_added.
            session_kept: dict[str, list[int]] = {}
            top_union: set[int] = set()
            for session in SESSION_ORDER:
                raw_ids = fa["sessions"].get(session)
                if not raw_ids:
                    continue
                kept, removed = filter_publishers(raw_ids)
                if removed:
                    stats["filtered_any"] = True
                    log(f"    filtered {removed} from {feed_id}/{session}")
                if not kept:
                    continue
                session_kept[session] = kept
                top_union.update(kept)

            if len(top_union) < min_promote_publishers:
                # Too few publishers survive filtering for adequate redundancy.
                # Leave the feed COMING_SOON rather than promote it.
                stats["skipped_too_few_publishers"] += 1
                log(
                    f"  SKIP (<{min_promote_publishers} publishers): "
                    f"feedId={feed_id}, have={sorted(top_union)}"
                )
                continue

            # Second pass: apply edits now that the feed clears the gate.
            block = re.sub(
                r'"state":\s*"COMING_SOON"', '"state": "STABLE"', block, count=1
            )
            for session in SESSION_ORDER:
                if session in session_kept:
                    # Session has publishers: write it (overwrite or add).
                    if session in existing_sessions:
                        block = overwrite_session(
                            block, session, session_kept[session], write_min=write_min
                        )
                    else:
                        block = add_session(
                            block, session, session_kept[session], bench,
                            write_min=write_min,
                        )
                        stats["sessions_added"] += 1
                elif session in existing_sessions:
                    # Session present in the feed but has NO publishers in the
                    # summary: drop it so the promoted STABLE feed never carries
                    # an unpriceable (publisher-less) session.
                    block = remove_session(block, session)
                    stats["sessions_removed"] += 1
                    log(
                        f"  REMOVE-SESSION (no publishers): feedId={feed_id}/{session}"
                    )
            block = set_top_level_min_publishers(block, 2)
            stats["promoted"] += 1
            log(f"  PROMOTE: feedId={feed_id} -> STABLE, union={sorted(top_union)}")
        else:  # STABLE — additive only
            added_any = False
            for session in SESSION_ORDER:
                raw_ids = fa["sessions"].get(session)
                if not raw_ids:
                    continue
                if session in existing_sessions:
                    log(f"  SKIP (live): feedId={feed_id}/{session}")
                    continue
                kept, removed = filter_publishers(raw_ids)
                if removed:
                    stats["filtered_any"] = True
                    log(f"    filtered {removed} from {feed_id}/{session}")
                if not kept:
                    continue
                block = add_session(block, session, kept, bench, write_min=write_min)
                added_any = True
                stats["sessions_added"] += 1
                log(f"  ADD-SESSION: feedId={feed_id}/{session}={kept}")
            if not added_any:
                # STABLE feed whose only data was for sessions already live:
                # nothing to add, nothing changed. Counted so the summary
                # reconciles to the input feed count.
                stats["skipped_stable_no_change"] += 1
                log(f"  SKIP (STABLE, no new sessions): feedId={feed_id}")

        raw = raw[:start] + block + raw[end:]

    return raw, stats
```

3. In `main()`: delete the `--asset-class` argument block entirely, and change the apply call to:

```python
    raw = config_path.read_text()
    new_raw, stats = apply_summary_to_config(
        raw,
        summary,
        log=print,
        min_promote_publishers=args.min_publishers,
    )
```

4. Update the module docstring (top of file): replace the sentence about per-(feed, session) promotion with a note that the tool targets the new (session-only) config format and that session-level `minPublishers` is written only for `Equity.US.*` feeds.

- [ ] **Step 6: Run the full file**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(apply-allowed): session-only publisher writes, unified hk/us path"
```

### Task 3: Format guard in apply_allowed

**Files:**

- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_rejects_old_format_config():
    feed = _feed(900, "COMING_SOON", [("REGULAR", [1, 2, 3])])
    feed["allowedPublisherIds"] = [1, 2, 3]  # old-format marker
    raw = _config_with([feed])
    summary = {
        900: {
            "aggregate": [24, 35, 42],
            "sessions": {
                "REGULAR": [24, 35, 42],
                "PRE_MARKET": None,
                "POST_MARKET": None,
                "OVER_NIGHT": None,
            },
        }
    }
    with pytest.raises(ValueError, match="old format"):
        apply_summary_to_config(raw, summary)


def test_cli_old_format_config_exits_1(tmp_path):
    xlsx = _real_workbook(tmp_path)
    feed = _feed(100, "COMING_SOON", [("REGULAR", [1, 2, 3])])
    feed["allowedPublisherIds"] = [1, 2, 3]
    cfg = tmp_path / "old_format.json"
    cfg.write_text(_config_with([feed]))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lazer_dq.apply_allowed_to_config",
            "--xlsx",
            str(xlsx),
            "--config",
            str(cfg),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 1
    assert "old format" in (result.stdout + result.stderr)
```

(Put the first next to the other `apply_*` tests, the second next to the existing CLI tests. `pytest` is already imported at the top of the file.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k old_format -v`
Expected: 2 FAILED (no guard yet — the old-format feed is processed normally / exit code 0)

- [ ] **Step 3: Implement the guard**

Add below `US_EQUITY_SYMBOL_PREFIX`:

```python
def check_new_format(data: dict) -> None:
    """Reject old-format configs that still carry feed-level allowedPublisherIds.

    The new config format (lazer_update.json era) keeps publisher lists only
    inside marketSchedules session entries; running this tool against an
    old-format file would leave stale feed-level rosters inconsistent with the
    session edits.
    """
    offenders = [
        f["feedId"] for f in data.get("feeds", []) if "allowedPublisherIds" in f
    ]
    if offenders:
        raise ValueError(
            f"config contains feed-level allowedPublisherIds (old format) on "
            f"{len(offenders)} feed(s), e.g. {offenders[:5]}. This tool now "
            f"supports only the session-level format (lazer_update.json era)."
        )
```

In `apply_summary_to_config`, right after `data = json.loads(raw)`, add:

```python
    check_new_format(data)
```

In `main()`, wrap the apply call:

```python
    raw = config_path.read_text()
    try:
        new_raw, stats = apply_summary_to_config(
            raw,
            summary,
            log=print,
            min_promote_publishers=args.min_publishers,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
```

- [ ] **Step 4: Run the full file**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(apply-allowed): reject old-format configs with feed-level publisher lists"
```

---

## Part B — `tools/edit-config/`

### Task 4: Text-surgery insert helpers

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_text_surgery.py`
- Test: `tools/edit-config/tests/test_config_text_surgery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_text_surgery.py`:

```python
import json

from edit_config_lib.config_text_surgery import (
    insert_field_after_open_brace,
    insert_field_before_session,
    find_marketschedules_end,
)


class TestInsertHelpers:
    SESSION_BLOCK = (
        "{\n"
        '          "marketSchedule": "X",\n'
        '          "session": "REGULAR"\n'
        "        }"
    )

    def test_insert_after_open_brace_leads_the_entry(self):
        out = insert_field_after_open_brace(
            self.SESSION_BLOCK, '"allowedPublisherIds": [ 80 ],'
        )
        data = json.loads(out)
        assert data["allowedPublisherIds"] == [80]
        assert list(data.keys())[0] == "allowedPublisherIds"

    def test_insert_after_open_brace_matches_indent(self):
        out = insert_field_after_open_brace(
            self.SESSION_BLOCK, '"allowedPublisherIds": [ 80 ],'
        )
        assert '\n          "allowedPublisherIds": [ 80 ],\n' in out

    def test_insert_before_session_canonical_position(self):
        out = insert_field_before_session(self.SESSION_BLOCK, '"minPublishers": 3,')
        data = json.loads(out)
        assert list(data.keys()) == ["marketSchedule", "minPublishers", "session"]

    def test_insert_before_session_falls_back_without_session_key(self):
        block = '{\n  "foo": 1\n}'
        out = insert_field_before_session(block, '"minPublishers": 3,')
        assert json.loads(out)["minPublishers"] == 3


class TestFindMarketschedulesEnd:
    def test_end_points_past_closing_bracket(self):
        block = (
            '{ "marketSchedules": [ { "minPublishers": 2, "session": "REGULAR" } ],'
            ' "minPublishers": 3 }'
        )
        end = find_marketschedules_end(block)
        assert block[end - 1] == "]"
        assert '"minPublishers": 3' in block[end:]

    def test_absent_array_returns_zero(self):
        assert find_marketschedules_end('{ "foo": 1 }') == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py -v`
Expected: ImportError (`insert_field_after_open_brace` does not exist)

- [ ] **Step 3: Implement**

Append to `tools/edit-config/edit_config_lib/config_text_surgery.py`:

```python
def insert_field_after_open_brace(block: str, field_text: str) -> str:
    """Insert `field_text` (e.g. '"allowedPublisherIds": [ 80 ],') as a new
    line right after the block's opening '{', indented to match the block's
    existing fields.

    `field_text` must carry its own trailing comma; a session entry always has
    at least the "session" field after the insertion point, so the comma is
    always valid.
    """
    brace = block.index("{")
    m = re.search(r'\n(\s*)"', block)
    if m:
        indent = m.group(1)
        nl = block.index("\n", brace)
        return block[: nl + 1] + indent + field_text + "\n" + block[nl + 1 :]
    # single-line fallback: '{ <field> ...'
    return block[: brace + 1] + " " + field_text + block[brace + 1 :]


def insert_field_before_session(block: str, field_text: str) -> str:
    """Insert `field_text` (e.g. '"minPublishers": 3,') on its own line just
    before the block's "session" key — the canonical position for
    minPublishers (...marketSchedule, minPublishers, session). Falls back to
    insert_field_after_open_brace when no "session" key exists.
    """
    m = re.search(r'\n(\s*)"session"\s*:', block)
    if m is None:
        return insert_field_after_open_brace(block, field_text)
    indent = m.group(1)
    pos = m.start() + 1  # just after the newline preceding the "session" line
    return block[:pos] + indent + field_text + "\n" + block[pos:]


def find_marketschedules_end(block: str) -> int:
    """Return the offset just past the marketSchedules array's closing ']',
    or 0 when the block has no marketSchedules array. Used to scope feed-level
    minPublishers lookups to the tail of a feed block (the feed-level value
    sits AFTER marketSchedules in the canonical layout)."""
    idx = block.find('"marketSchedules":')
    if idx < 0:
        return 0
    open_idx = block.find("[", idx)
    if open_idx < 0:
        return 0
    close = find_matching_close(block, open_idx)
    return 0 if close is None else close + 1
```

- [ ] **Step 4: Run**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
pre-commit run --files tools/edit-config/edit_config_lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git add tools/edit-config/edit_config_lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): text-surgery insert helpers for missing session fields"
```

### Task 5: Sequential applier with insert support

Rewrite `_apply_changes_to_feed_block` to apply one change at a time (re-locating spans after every splice — required for whole-line inserts and for two inserts hitting the same session entry). Top-level publisher changes are no longer supported (`state` and feed-level `minPublishers` remain).

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Test: `tools/edit-config/tests/test_config_editor.py`

- [ ] **Step 1: Write the failing tests**

In `tools/edit-config/tests/test_config_editor.py`, DELETE `TestApplyChanges.test_publisher_top_level_change` (feed-level publisher lists no longer exist as an edit target). In `test_multiple_changes_same_feed`, replace the first Change (the long top-level publisher one) with a session-scoped pair so the test reads:

```python
    def test_multiple_changes_same_feed(self):
        changes = [
            Change(
                feed_id=922,
                symbol="X",
                location="REGULAR",
                field="allowedPublisherIds",
                before=[
                    12, 14, 19, 20, 21, 22, 26, 29, 35, 41, 42, 45, 48, 54, 55,
                    59, 64, 65, 69, 71,
                ],
                after=[
                    12, 14, 19, 20, 21, 22, 26, 29, 35, 41, 42, 45, 48, 54, 55,
                    59, 64, 65, 69, 71, 80,
                ],
            ),
            Change(
                feed_id=922,
                symbol="X",
                location="REGULAR",
                field="minPublishers",
                before=3,
                after=4,
            ),
        ]
        new_raw = apply_changes(self.raw, changes)
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        regular = next(s for s in f["marketSchedules"] if s["session"] == "REGULAR")
        assert 80 in regular["allowedPublisherIds"]
        assert regular["minPublishers"] == 4
```

Then append a new test class:

```python
class TestApplyChangesInserts:
    """Insert-when-absent: the new config format ships session entries without
    allowedPublisherIds / minPublishers keys; the applier must create them."""

    RAW = """{
  "feeds": [
    {
      "feedId": 5000,
      "symbol": "Crypto.NEW/USD",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
          "session": "REGULAR"
        }
      ],
      "minPublishers": 3,
      "state": "COMING_SOON"
    }
  ]
}"""

    def test_inserts_session_publisher_list(self):
        change = Change(
            feed_id=5000,
            symbol="Crypto.NEW/USD",
            location="REGULAR",
            field="allowedPublisherIds",
            before=None,
            after=[80],
        )
        out = apply_changes(self.RAW, [change])
        reg = json.loads(out)["feeds"][0]["marketSchedules"][0]
        assert reg["allowedPublisherIds"] == [80]
        assert reg["session"] == "REGULAR"  # entry still intact

    def test_inserts_session_min_publishers_before_session_key(self):
        change = Change(
            feed_id=5000,
            symbol="Crypto.NEW/USD",
            location="REGULAR",
            field="minPublishers",
            before=None,
            after=2,
        )
        out = apply_changes(self.RAW, [change])
        reg = json.loads(out)["feeds"][0]["marketSchedules"][0]
        assert reg["minPublishers"] == 2
        keys = list(reg.keys())
        assert keys.index("minPublishers") == keys.index("session") - 1

    def test_two_inserts_into_same_session_entry(self):
        # e.g. a YAML spec with add_publisher + set_min_publishers in one run.
        changes = [
            Change(
                feed_id=5000,
                symbol="Crypto.NEW/USD",
                location="REGULAR",
                field="allowedPublisherIds",
                before=None,
                after=[80, 81],
            ),
            Change(
                feed_id=5000,
                symbol="Crypto.NEW/USD",
                location="REGULAR",
                field="minPublishers",
                before=None,
                after=2,
            ),
        ]
        out = apply_changes(self.RAW, changes)
        reg = json.loads(out)["feeds"][0]["marketSchedules"][0]
        assert reg["allowedPublisherIds"] == [80, 81]
        assert reg["minPublishers"] == 2

    def test_replaces_null_session_publishers(self):
        raw = self.RAW.replace(
            '"marketSchedule": "America/New_York;O,O,O,O,O,O,O;",',
            '"allowedPublisherIds": null,\n          '
            '"marketSchedule": "America/New_York;O,O,O,O,O,O,O;",',
        )
        change = Change(
            feed_id=5000,
            symbol="Crypto.NEW/USD",
            location="REGULAR",
            field="allowedPublisherIds",
            before=None,
            after=[1, 2],
        )
        out = apply_changes(raw, [change])
        reg = json.loads(out)["feeds"][0]["marketSchedules"][0]
        assert reg["allowedPublisherIds"] == [1, 2]
        assert "null" not in out

    def test_feed_level_min_publishers_still_works_after_sessions(self):
        # Feed-level minPublishers sits AFTER marketSchedules; the lookup must
        # not match the session's value.
        raw = self.RAW.replace(
            '"session": "REGULAR"',
            '"minPublishers": 1,\n          "session": "REGULAR"',
        )
        change = Change(
            feed_id=5000,
            symbol="Crypto.NEW/USD",
            location="top_level",
            field="minPublishers",
            before=3,
            after=2,
        )
        out = apply_changes(raw, [change])
        feed = json.loads(out)["feeds"][0]
        assert feed["minPublishers"] == 2
        assert feed["marketSchedules"][0]["minPublishers"] == 1  # untouched
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k "Insert or multiple_changes_same_feed" -v`
Expected: insert tests FAIL with `RuntimeError: allowedPublisherIds not found in REGULAR` / `minPublishers not found in REGULAR`; `test_multiple_changes_same_feed` PASSES (already supported)

- [ ] **Step 3: Rewrite the applier**

In `tools/edit-config/edit_config_lib/config_editor.py`, extend the surgery import (~line 442) to:

```python
from edit_config_lib.config_text_surgery import (
    find_feed_block,
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
    find_matching_close,
    find_ric_identifier_spans,
    find_marketschedules_end,
    insert_field_after_open_brace,
    insert_field_before_session,
)
```

Then replace the whole `_apply_changes_to_feed_block` function with:

```python
import re


def _set_session_publishers(sblock: str, ids: list[int]) -> str:
    """Set (or insert) a session entry's allowedPublisherIds list."""
    span = find_publisher_array_span(sblock)
    if span is not None:
        return sblock[: span[0]] + _format_publisher_list(ids) + sblock[span[1] :]
    null_m = re.search(r'"allowedPublisherIds":\s*null', sblock)
    if null_m is not None:
        repl = f'"allowedPublisherIds": {_format_publisher_list(ids)}'
        return sblock[: null_m.start()] + repl + sblock[null_m.end() :]
    field = f'"allowedPublisherIds": {_format_publisher_list(ids)},'
    return insert_field_after_open_brace(sblock, field)


def _set_session_min_publishers(sblock: str, value: int) -> str:
    """Set (or insert, in canonical position) a session entry's minPublishers."""
    span = find_int_field_span(sblock, "minPublishers")
    if span is not None:
        return sblock[: span[0]] + str(value) + sblock[span[1] :]
    return insert_field_before_session(sblock, f'"minPublishers": {value},')


def _apply_one_change(block: str, change: Change) -> str:
    """Apply a single Change to a feed's raw text block."""
    if change.location == "datascope_ric_identifier":
        ric_spans = find_ric_identifier_spans(block)
        if change.index is None:
            raise RuntimeError("datascope_ric_identifier change missing index")
        if change.index >= len(ric_spans):
            raise RuntimeError(
                f"identifier slot index {change.index} out of range "
                f"({len(ric_spans)} slots)"
            )
        start, end, _current = ric_spans[change.index]
        return block[:start] + f'"{change.after}"' + block[end:]

    if change.location == "top_level":
        if change.field == "state":
            span = find_string_field_span(block, "state")
            if span is None:
                raise RuntimeError("state field not found in feed block")
            return block[: span[0]] + f'"{change.after}"' + block[span[1] :]
        if change.field == "minPublishers":
            # The feed-level minPublishers sits AFTER the marketSchedules
            # array, so scope the lookup to the tail to avoid matching a
            # session's value.
            tail_start = find_marketschedules_end(block)
            m = re.search(r'"minPublishers":\s*(-?\d+)', block[tail_start:])
            if m is None:
                raise RuntimeError("feed-level minPublishers not found")
            s, e = tail_start + m.start(1), tail_start + m.end(1)
            return block[:s] + str(change.after) + block[e:]
        raise RuntimeError(
            f"unsupported top-level field {change.field!r} — the new config "
            f"format keeps publisher lists only in session entries"
        )

    # Session-scoped change.
    sb = find_session_block(block, change.location)
    if sb is None:
        raise RuntimeError(
            f"session block {change.location!r} not found in feed block"
        )
    sblock = block[sb[0] : sb[1]]
    if change.field == "allowedPublisherIds":
        new_sblock = _set_session_publishers(sblock, change.after)
    elif change.field == "minPublishers":
        new_sblock = _set_session_min_publishers(sblock, change.after)
    else:
        raise RuntimeError(f"unsupported session field {change.field!r}")
    return block[: sb[0]] + new_sblock + block[sb[1] :]


def _apply_changes_to_feed_block(block: str, changes: list[Change]) -> str:
    """Apply all changes for a single feed, one at a time.

    Each change re-locates its span in the CURRENT block text, so a prior
    splice — including whole-line inserts that shift everything after them —
    can never invalidate a later change's offsets.
    """
    for change in changes:
        block = _apply_one_change(block, change)
    return block
```

(Move the `import re` to the top of the file with the other imports if black complains; the module previously had no `re` import.)

`apply_changes` itself is unchanged.

- [ ] **Step 4: Run the file**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run the unit-level test files (NOT the CLI file)**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/test_config_text_surgery.py tools/edit-config/tests/test_config_ops.py tools/edit-config/tests/test_config_diff.py -v`
Expected: ALL PASS

Do NOT run `test_edit_config_cli.py` here: its apply-path tests (e.g. `test_apply_writes_changes`) drive the OLD ops, which still emit top-level publisher changes that this applier intentionally no longer supports. They are red by design until the ops are rewritten (Task 7) and the tests migrated (Task 8).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): sequential text applier with session-field inserts (WIP: CLI apply tests red until ops rewrite)"
```

### Task 6: Diff rendering for inserts

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_diff.py`
- Test: `tools/edit-config/tests/test_config_diff.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_diff.py`:

```python
def test_insert_renders_absent_before_line_for_publishers():
    c = Change(
        feed_id=5000,
        symbol="Crypto.NEW/USD",
        location="REGULAR",
        field="allowedPublisherIds",
        before=None,
        after=[80],
    )
    out = render_diff([c])
    assert "-      (absent)" in out
    assert '+      "allowedPublisherIds": [ 80 ],' in out


def test_insert_renders_absent_before_line_for_min_publishers():
    c = Change(
        feed_id=5000,
        symbol="Crypto.NEW/USD",
        location="REGULAR",
        field="minPublishers",
        before=None,
        after=2,
    )
    out = render_diff([c])
    assert "-      (absent)" in out
    assert '+      "minPublishers": 2,' in out
```

(Match the import style already used at the top of that test file — it imports `Change` and `render_diff`.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_diff.py -v`
Expected: 2 FAILED (`before=None` currently renders as `[ ]` / `None`)

- [ ] **Step 3: Implement**

In `_value_lines` in `config_diff.py`, add at the top of the function:

```python
def _value_lines(change: Change) -> tuple[str, str]:
    """Return (before_line, after_line) formatted as JSON-ish text."""
    if change.before is None and change.field in (
        "allowedPublisherIds",
        "minPublishers",
    ):
        # Insert: the field did not exist in the session entry before.
        b = "      (absent)"
        if change.field == "allowedPublisherIds":
            a = (
                f'      "allowedPublisherIds": '
                f"{_format_publisher_list(change.after)},"
            )
        else:
            a = f'      "minPublishers": {change.after},'
        return b, a
```

(then the existing `if/elif` chain continues unchanged).

- [ ] **Step 4: Run**

Run: `python3 -m pytest tools/edit-config/tests/test_config_diff.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
pre-commit run --files tools/edit-config/edit_config_lib/config_diff.py tools/edit-config/tests/test_config_diff.py
git add tools/edit-config/edit_config_lib/config_diff.py tools/edit-config/tests/test_config_diff.py
git commit -m "feat(edit-config): render field inserts as (absent) in diffs"
```

### Task 7: Rewrite the op classes (flag day for `config_ops.py`)

This task rewrites the fixture and all four publisher/min ops together — they cannot be separated and stay meaningful. At the end of this task `test_config_ops.py` is green; `test_config_editor.py` / `test_edit_config_cli.py` go red and are fixed in Task 8. **Do not run the full suite between Tasks 7 and 8.**

**Files:**

- Rewrite: `tools/edit-config/tests/fixtures/after_sample.json`
- Modify: `tools/edit-config/edit_config_lib/config_ops.py`
- Modify: `tools/edit-config/tests/fixtures/edits_basic.yaml`
- Test: `tools/edit-config/tests/test_config_ops.py`

- [ ] **Step 1: Rewrite the fixture to the new format**

Replace the entire content of `tools/edit-config/tests/fixtures/after_sample.json` with:

```json
{
  "featureFlags": [],
  "feeds": [
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [1, 3, 7, 11],
          "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "crypto",
        "name": "BTCUSD",
        "symbol": "Crypto.BTC/USD"
      },
      "minPublishers": 3,
      "state": "STABLE",
      "symbol": "Crypto.BTC/USD"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 100,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [19, 22, 41, 42, 45, 54, 55, 59, 65],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "fx",
        "name": "EURUSD",
        "symbol": "FX.EUR/USD"
      },
      "minPublishers": 3,
      "state": "STABLE",
      "symbol": "FX.EUR/USD"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 922,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [
            12, 14, 19, 20, 21, 22, 26, 29, 35, 41, 42, 45, 48, 54, 55, 59, 64,
            65, 69, 71
          ],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 3,
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [19, 20, 22, 41, 42, 45, 55, 59, 65],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "PRE_MARKET"
        },
        {
          "allowedPublisherIds": [19, 22, 41, 42, 45, 54, 55, 59, 65],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "POST_MARKET"
        },
        {
          "allowedPublisherIds": [32, 41, 42],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "OVER_NIGHT"
        }
      ],
      "metadata": {
        "asset_type": "equity",
        "name": "AAPL",
        "symbol": "Equity.US.AAPL/USD"
      },
      "minPublishers": 1,
      "state": "STABLE",
      "symbol": "Equity.US.AAPL/USD"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1023,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [22, 41, 54, 55],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "equity",
        "name": "SMLC",
        "symbol": "Equity.US.SMLC/USD"
      },
      "minPublishers": 2,
      "state": "STABLE",
      "symbol": "Equity.US.SMLC/USD"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 5000,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "crypto",
        "name": "NEWCOIN",
        "symbol": "Crypto.NEW/USD"
      },
      "minPublishers": 3,
      "state": "COMING_SOON",
      "symbol": "Crypto.NEW/USD"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 6000,
      "isEnabledInShard": false,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [19, 22],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "fx",
        "name": "OLDPAIR",
        "symbol": "FX.OLD/USD"
      },
      "minPublishers": 1,
      "state": "INACTIVE",
      "symbol": "FX.OLD/USD"
    }
  ]
}
```

Fixture intents: feed 1/100/6000 = non-US, list moved into REGULAR, no session min; feed 922 = US 4-session, unchanged sessions, feed-level list dropped; feed 1023 = US single-session WITHOUT session min (exercises min-insert on a US feed); feed 5000 = COMING_SOON crypto whose REGULAR has NO list (exercises publisher-insert).

- [ ] **Step 2: Update `edits_basic.yaml`**

In `tools/edit-config/tests/fixtures/edits_basic.yaml`, the last operation uses `session: NONE` on `add_publisher` (now invalid). Delete that `session: NONE` line so the op defaults to REGULAR:

```yaml
- op: add_publisher
  publisher_id: 90
  feed_id: [1, "100-101", 5000]
```

- [ ] **Step 3: Rewrite `config_ops.py` (helpers + four ops)**

In `tools/edit-config/edit_config_lib/config_ops.py`:

1. Below `SESSION_NAMES`, add:

```python
# Session-level minPublishers is a us-equities-only concept in the new config
# format; every other asset class takes minPublishers at the feed level only.
US_EQUITY_SYMBOL_PREFIX = "Equity.US."
```

2. DELETE `has_session_publishers` (no longer used). Keep `get_session`.

3. Below `get_session`, add:

```python
def is_us_equity(feed: dict) -> bool:
    """True for feeds that may carry session-level minPublishers."""
    return feed.get("symbol", "").startswith(US_EQUITY_SYMBOL_PREFIX)


def _session_publisher_union(feed: dict) -> list[int]:
    """Union of every session's allowedPublisherIds — the effective feed
    roster, now that no feed-level allowedPublisherIds exists."""
    ids: set[int] = set()
    for s in feed.get("marketSchedules", []):
        ids.update(s.get("allowedPublisherIds") or [])
    return sorted(ids)


def _resolve_publisher_sessions(feed: dict, session: str | None) -> list[str]:
    """Session names a publisher op targets.

    Publisher lists live ONLY in marketSchedules entries in the new config
    format; there is no feed-level roster, so session=NONE is invalid here.
    """
    feed_id = feed["feedId"]
    if session is None:
        return ["REGULAR"]
    if session == "ALL":
        return [s["session"] for s in feed.get("marketSchedules", [])]
    if session == "NONE":
        raise OpError(
            f"feed {feed_id}: session=NONE is invalid for publisher ops — "
            f"the new config format has no feed-level allowedPublisherIds"
        )
    if session in SESSION_NAMES:
        return [session]
    raise OpError(f"unknown session value: {session!r}")
```

4. Replace `AddPublisher` with:

```python
@dataclass
class AddPublisher:
    publisher_id: int
    session: str | None = None  # None|REGULAR|PRE_MARKET|POST_MARKET|OVER_NIGHT|ALL

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        for name in _resolve_publisher_sessions(feed, self.session):
            sess = get_session(feed, name)
            if sess is None:
                raise OpError(
                    f"feed {feed_id}: session {name!r} does not exist on this feed"
                )
            if "allowedPublisherIds" not in sess or sess["allowedPublisherIds"] is None:
                # Missing (or null) list: create it. before=None marks
                # "field absent — insert" for the diff and the text applier.
                sess["allowedPublisherIds"] = [self.publisher_id]
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=name,
                        field="allowedPublisherIds",
                        before=None,
                        after=[self.publisher_id],
                    )
                )
                continue
            result = _add_publisher_to_list(
                sess["allowedPublisherIds"], self.publisher_id
            )
            if result is None:
                continue
            before, after = result
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=name,
                    field="allowedPublisherIds",
                    before=before,
                    after=after,
                )
            )

        return changes, []
```

5. Replace `RemovePublisher` with:

```python
@dataclass
class RemovePublisher:
    publisher_id: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        names = _resolve_publisher_sessions(feed, self.session)
        explicit = self.session in SESSION_NAMES
        feed_min = feed.get("minPublishers")

        for name in names:
            sess = get_session(feed, name)
            if sess is None:
                if explicit:
                    raise OpError(
                        f"feed {feed_id}: session {name!r} does not exist "
                        f"on this feed"
                    )
                continue
            ref = sess.get("allowedPublisherIds")
            if not ref:
                continue  # nothing to remove from a missing/empty list
            result = _remove_from_list(ref, self.publisher_id)
            if result is None:
                continue
            before, after = result
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=name,
                    field="allowedPublisherIds",
                    before=before,
                    after=after,
                )
            )
            # Headroom check: session minPublishers when present, else the
            # feed-level value (still enforced in the new format).
            warn = _check_at_floor(
                feed_id, symbol, name, after, sess.get("minPublishers", feed_min)
            )
            if warn is not None:
                warnings.append(warn)

        return changes, warnings
```

6. Replace `_resolve_min_pub_targets` and `_list_for_target` with:

```python
def _resolve_min_pub_targets(
    feed: dict,
    session: str | None,
) -> list[tuple[str, dict, str]]:
    """Return list of (location, container, key) tuples for minPublishers ops.

    Feed-level minPublishers exists on every feed and stays editable.
    Session-level minPublishers is a us-equities-only concept: non-US feeds
    never get session targets, and explicitly asking for one is an error.
    Session targets are limited to entries that already have a publisher list
    (a publisher-less session has nothing to satisfy a floor against).
    """
    feed_id = feed["feedId"]
    us = is_us_equity(feed)
    targets: list[tuple[str, dict, str]] = []

    if session is None:
        targets.append(("top_level", feed, "minPublishers"))
        if us:
            regular = get_session(feed, "REGULAR")
            if regular is not None and regular.get("allowedPublisherIds"):
                targets.append(("REGULAR", regular, "minPublishers"))
    elif session == "NONE":
        targets.append(("top_level", feed, "minPublishers"))
    elif session == "ALL":
        targets.append(("top_level", feed, "minPublishers"))
        if us:
            for s in feed.get("marketSchedules", []):
                if s.get("allowedPublisherIds"):
                    targets.append((s["session"], s, "minPublishers"))
    elif session in SESSION_NAMES:
        if not us:
            raise OpError(
                f"feed {feed_id} ({feed.get('symbol', '')}): session-level "
                f"minPublishers is a us-equities-only concept; this feed "
                f"takes minPublishers at the feed level (omit --session or "
                f"use --session NONE)"
            )
        sess = get_session(feed, session)
        if sess is None:
            raise OpError(
                f"feed {feed_id}: session {session!r} does not exist on this feed"
            )
        targets.append((session, sess, "minPublishers"))
    else:
        raise OpError(f"unknown session value: {session!r}")

    return targets


def _list_for_target(feed: dict, location: str) -> list[int]:
    if location == "top_level":
        # No feed-level roster exists in the new format; validate against the
        # union of all session lists.
        return _session_publisher_union(feed)
    sess = get_session(feed, location)
    return (sess.get("allowedPublisherIds") or []) if sess else []
```

7. In `BumpMinPublishers.apply`, change both loops' first two lines from

```python
            old = container.get(key, 0)
            new = max(1, old + self.delta)
```

to

```python
            old = container.get(key)
            new = max(1, (old or 0) + self.delta)
```

(in the mutation loop the `if new == old: continue` and `Change(before=old, ...)` lines stay — `before=None` now correctly marks an insert). `SetMinPublishers` needs no change: `container.get(key)` already yields `None` for a missing key, producing an insert-style Change.

- [ ] **Step 4: Rewrite the affected tests in `test_config_ops.py`**

Update the import at the top: remove `has_session_publishers`; the rest stays. Delete the three `has_session_publishers` tests in `TestSessionHelpers` (keep `test_session_names_constant`, `test_get_session_returns_dict`, `test_get_session_missing_returns_none`).

Replace `TestAddPublisher` entirely with:

```python
class TestAddPublisher:
    def test_default_targets_regular_only(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto: publishers in REGULAR entry
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        regular = get_session(feed, "REGULAR")
        assert regular["allowedPublisherIds"] == [1, 3, 7, 11, 80]
        assert len(changes) == 1
        assert changes[0].location == "REGULAR"
        assert changes[0].field == "allowedPublisherIds"
        assert changes[0].before == [1, 3, 7, 11]
        assert changes[0].after == [1, 3, 7, 11, 80]
        assert warns == []

    def test_default_on_us_equity_touches_regular_not_extended(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80)
        changes, _ = op.apply(feed)
        assert 80 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert 80 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["REGULAR"]

    def test_explicit_pre_market_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 80 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 80 not in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_session_all_touches_every_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        for sname in SESSION_NAMES:
            assert 80 in get_session(feed, sname)["allowedPublisherIds"]
        assert len(changes) == 4  # sessions only — no top_level anymore

    def test_session_all_on_single_session_feed(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto: REGULAR only
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        assert len(changes) == 1
        assert changes[0].location == "REGULAR"

    def test_session_none_raises(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="NONE")
        with pytest.raises(OpError, match="NONE is invalid for publisher ops"):
            op.apply(feed)

    def test_explicit_session_missing_on_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no PRE_MARKET entry
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        with pytest.raises(OpError, match="does not exist"):
            op.apply(feed)

    def test_inserts_list_when_session_lacks_key(self, feeds):
        # Feed 5000's REGULAR entry has NO allowedPublisherIds (COMING_SOON
        # shape) — the op must create it, flagged as an insert (before=None).
        feed = feed_by_id(feeds, 5000)
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert get_session(feed, "REGULAR")["allowedPublisherIds"] == [80]
        assert len(changes) == 1
        assert changes[0].before is None
        assert changes[0].after == [80]
        assert warns == []

    def test_noop_when_already_present(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=3)  # 3 already in REGULAR [1, 3, 7, 11]
        changes, _ = op.apply(feed)
        assert changes == []

    def test_lists_deduped_and_sorted(self, feeds):
        feed = feed_by_id(feeds, 1)
        get_session(feed, "REGULAR")["allowedPublisherIds"] = [11, 1, 7, 3]
        op = AddPublisher(publisher_id=5)
        op.apply(feed)
        assert get_session(feed, "REGULAR")["allowedPublisherIds"] == [
            1, 3, 5, 7, 11
        ]
```

Replace `TestRemovePublisher` entirely with:

```python
class TestRemovePublisher:
    def test_default_removes_from_regular_only(self, feeds):
        feed = feed_by_id(feeds, 922)
        # publisher 22 is in REGULAR + PRE_MARKET + POST_MARKET
        op = RemovePublisher(publisher_id=22)
        changes, _ = op.apply(feed)
        assert 22 not in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert 22 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "POST_MARKET")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["REGULAR"]

    def test_session_all_removes_everywhere(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="ALL")
        changes, _ = op.apply(feed)
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            assert 22 not in (sess.get("allowedPublisherIds") or [])
        # REGULAR + PRE_MARKET + POST_MARKET had 22; OVER_NIGHT did not.
        assert sorted(c.location for c in changes) == [
            "POST_MARKET", "PRE_MARKET", "REGULAR",
        ]

    def test_explicit_session_removes_only_that_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 22 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_session_none_raises(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="NONE")
        with pytest.raises(OpError, match="NONE is invalid for publisher ops"):
            op.apply(feed)

    def test_explicit_session_missing_on_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=1, session="PRE_MARKET")
        with pytest.raises(OpError, match="does not exist"):
            op.apply(feed)

    def test_noop_when_absent(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=999)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_noop_when_session_lacks_key(self, feeds):
        # Feed 5000's REGULAR entry has no allowedPublisherIds at all.
        feed = feed_by_id(feeds, 5000)
        op = RemovePublisher(publisher_id=1)
        changes, warns = op.apply(feed)
        assert changes == []
        assert warns == []

    def test_warns_when_at_or_below_session_min(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has [32, 41, 42] with session minPublishers=2.
        # Remove 32 -> [41, 42] with min=2 -> at-floor warning.
        op = RemovePublisher(publisher_id=32, session="OVER_NIGHT")
        _, warns = op.apply(feed)
        assert any(
            "OVER_NIGHT" in w.message and "headroom" in w.message.lower()
            for w in warns
        )

    def test_headroom_falls_back_to_feed_level_min(self, feeds):
        # Feed 6000: REGULAR [19, 22] with NO session minPublishers;
        # feed-level minPublishers=1. Remove 19 -> [22] vs min=1 -> warning.
        feed = feed_by_id(feeds, 6000)
        op = RemovePublisher(publisher_id=19)
        _, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)
```

Replace `TestSetMinPublishers` entirely with:

```python
class TestSetMinPublishers:
    def test_default_non_us_writes_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 1)  # Crypto.BTC/USD
        op = SetMinPublishers(value=2)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert "minPublishers" not in get_session(feed, "REGULAR")
        assert [c.location for c in changes] == ["top_level"]

    def test_default_us_writes_feed_level_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 4
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 2  # untouched
        assert sorted(c.location for c in changes) == ["REGULAR", "top_level"]

    def test_default_us_inserts_missing_regular_min(self, feeds):
        # Feed 1023 is Equity.US.* with a REGULAR list but NO session min.
        feed = feed_by_id(feeds, 1023)
        op = SetMinPublishers(value=3)
        changes, _ = op.apply(feed)
        assert get_session(feed, "REGULAR")["minPublishers"] == 3
        regular_change = next(c for c in changes if c.location == "REGULAR")
        assert regular_change.before is None  # insert

    def test_explicit_session_on_us_feed(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 3
        assert feed["minPublishers"] == 1  # untouched
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_explicit_session_on_non_us_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto
        op = SetMinPublishers(value=2, session="REGULAR")
        with pytest.raises(OpError, match="us-equities-only"):
            op.apply(feed)

    def test_session_all_on_non_us_feed_is_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 100)  # fx
        op = SetMinPublishers(value=2, session="ALL")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert "minPublishers" not in get_session(feed, "REGULAR")
        assert [c.location for c in changes] == ["top_level"]

    def test_session_none_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4, session="NONE")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 3  # untouched
        assert [c.location for c in changes] == ["top_level"]

    def test_feed_level_validated_against_session_union(self, feeds):
        # Feed 1's union is [1, 3, 7, 11] (4 publishers): value 5 must error.
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=5)
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_unsatisfiable_on_feed_without_any_publishers(self, feeds):
        # Feed 5000 has no publisher lists at all -> union is empty.
        feed = feed_by_id(feeds, 5000)
        op = SetMinPublishers(value=2)
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_session_value_validated_against_session_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers: min=5 is unsatisfiable.
        op = SetMinPublishers(value=5, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_warning_at_floor(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="OVER_NIGHT")
        _, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)

    def test_warning_when_one_on_stable(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=1)
        _, warns = op.apply(feed)
        assert any("STABLE" in w.message and "1" in w.message for w in warns)

    def test_noop_when_unchanged(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=3)  # already 3
        changes, _ = op.apply(feed)
        assert changes == []
```

Replace `TestBumpMinPublishers` entirely with:

```python
class TestBumpMinPublishers:
    def test_bump_up_feed_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3, union has 4 publishers
        op = BumpMinPublishers(delta=+1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert changes[0].before == 3 and changes[0].after == 4

    def test_bump_down(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = BumpMinPublishers(delta=-1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2

    def test_clamped_at_one(self, feeds):
        feed = feed_by_id(feeds, 6000)  # min=1
        op = BumpMinPublishers(delta=-5)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 1
        assert changes == []  # NOOP since value didn't change

    def test_zero_delta_is_noop(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = BumpMinPublishers(delta=0)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_hard_error_when_exceeding_session_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT min=2, count=3. Bump +2 -> 4 -> exceeds.
        op = BumpMinPublishers(delta=+2, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_hard_error_against_union_at_feed_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3, union of 4
        op = BumpMinPublishers(delta=+2)  # -> 5 > 4
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_explicit_session_on_non_us_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 100)  # fx
        op = BumpMinPublishers(delta=+1, session="REGULAR")
        with pytest.raises(OpError, match="us-equities-only"):
            op.apply(feed)
```

`TestSetState`, `SetRicMapping` tests, and `SetRicFromResolver` tests are unchanged.

- [ ] **Step 5: Run the ops tests**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit (known-red note)**

`test_config_editor.py` / `test_edit_config_cli.py` are red until Task 8 — that is expected; do NOT run the full suite as a gate here.

```bash
pre-commit run --files tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py tools/edit-config/tests/fixtures/after_sample.json tools/edit-config/tests/fixtures/edits_basic.yaml
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py tools/edit-config/tests/fixtures/after_sample.json tools/edit-config/tests/fixtures/edits_basic.yaml
git commit -m "feat(edit-config): session-only publisher ops, US-only session minPublishers (WIP: editor/cli tests updated next)"
```

### Task 8: Format guard in `edit_config.py` + editor/CLI test migration

**Files:**

- Modify: `tools/edit-config/edit_config.py`
- Modify: `tools/edit-config/tests/fixtures/hk_sample.json`
- Test: `tools/edit-config/tests/test_config_editor.py`, `tools/edit-config/tests/test_edit_config_cli.py`

- [ ] **Step 1: Add the format guard to `main()`**

In `tools/edit-config/edit_config.py`, right after `feeds = data["feeds"]` (~line 191), insert:

```python
    old_format = [f["feedId"] for f in feeds if "allowedPublisherIds" in f]
    if old_format:
        print(
            f"ERROR: config contains feed-level allowedPublisherIds (old "
            f"format) on {len(old_format)} feed(s), e.g. {old_format[:5]}.\n"
            f"This tool now supports only the session-level format "
            f"(lazer_update.json era).",
            file=sys.stderr,
        )
        return 1
```

- [ ] **Step 2: Migrate `hk_sample.json`**

`tools/edit-config/tests/fixtures/hk_sample.json` carries feed-level `allowedPublisherIds` on its 4 feeds, which the guard now rejects. Delete the `"allowedPublisherIds": [...],` line from every feed object in that file (the RIC ops never touch publisher lists, so nothing else changes). Verify with:

Run: `grep -c allowedPublisherIds tools/edit-config/tests/fixtures/hk_sample.json`
Expected: `0`

- [ ] **Step 3: Update `test_edit_config_cli.py`**

Add a module-level helper after the `run_cli` definition:

```python
def _regular_ids(feed: dict) -> list[int]:
    reg = next(s for s in feed["marketSchedules"] if s["session"] == "REGULAR")
    return reg.get("allowedPublisherIds", [])
```

Then update every assertion that reads a feed-level publisher list (the fixture no longer has one). Four tests change:

- `TestCli.test_dry_run_default`: `assert 80 not in f["allowedPublisherIds"]` → `assert 80 not in _regular_ids(f)`
- `TestCli.test_apply_writes_changes`: `assert 80 in f["allowedPublisherIds"]` → `assert 80 in _regular_ids(f)`
- `TestCli.test_yaml_spec`: `assert 80 in f["allowedPublisherIds"]` → `assert 80 in _regular_ids(f)`
- `TestCli.test_feed_ids_from_file`: both asserts → `assert 80 in _regular_ids(f1)` and `assert 80 in _regular_ids(f100)`

Append two guard tests (one subprocess, one in-process inside `TestCliInProcess`):

```python
    def test_old_format_config_rejected(self, tmp_path):
        old = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "Crypto.BTC/USD",
                    "state": "STABLE",
                    "allowedPublisherIds": [1, 3],
                    "minPublishers": 1,
                    "marketSchedules": [{"session": "REGULAR"}],
                }
            ]
        }
        cfg = tmp_path / "after.json"
        cfg.write_text(json.dumps(old, indent=2), encoding="utf-8")
        result = run_cli(
            ["--config", str(cfg), "--add-publisher", "80", "--feed-id", "1"]
        )
        assert result.returncode == 1
        assert "old format" in result.stderr
```

(add this inside `TestCli`), and inside `TestCliInProcess`:

```python
    def test_old_format_config_rejected_in_process(self, tmp_path, capsys):
        old = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "Crypto.BTC/USD",
                    "state": "STABLE",
                    "allowedPublisherIds": [1, 3],
                    "minPublishers": 1,
                    "marketSchedules": [{"session": "REGULAR"}],
                }
            ]
        }
        cfg = tmp_path / "after.json"
        cfg.write_text(json.dumps(old, indent=2), encoding="utf-8")
        m = self._import_main()
        rc = m.main(["--config", str(cfg), "--add-publisher", "80", "--feed-id", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "old format" in err
```

- [ ] **Step 4: Update `test_config_editor.py`**

With the new fixture and ops, only one already-passing area needs review; verify these specific expectations still hold and fix if not:

- `TestSimulatePlan.test_single_op_succeeds`: still passes — feed 1's REGULAR list is `[1, 3, 7, 11]`, so `changes[0].after == [1, 3, 7, 11, 80]` is unchanged (location is now `REGULAR`, which the test does not assert).
- `TestSimulatePlan.test_op_error_recorded`: still passes (PRE_MARKET on crypto still raises).
- `TestRunLinter.test_runs_existing_linter_on_fixture`: only asserts types — passes regardless of linter findings on the new-format fixture.
- All `TestApplyChanges*` tests were already migrated in Task 5.

- [ ] **Step 5: Run the FULL edit-config suite**

Run: `python3 -m pytest tools/edit-config/tests -v`
Expected: ALL PASS (this closes the known-red window opened in Task 7)

- [ ] **Step 6: Commit**

```bash
pre-commit run --files tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/fixtures/hk_sample.json
git add tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/fixtures/hk_sample.json
git commit -m "feat(edit-config): reject old-format configs; migrate CLI/editor tests to new format"
```

### Task 9: Real-data sanity runs

No code changes — verification against the real `lazer_update.json` before touching docs.

- [ ] **Step 1: edit-config dry-run on a US-equity feed**

```bash
cp lazer_update.json /tmp/lu_test.json
python3 tools/edit-config/edit_config.py --config /tmp/lu_test.json --add-publisher 99 --feed-id 922
```

Expected: exit 0, `[DRY RUN]`, exactly one hunk `@@ feedId 922 (Equity.US.AAPL/USD), session REGULAR @@` — no `top_level` hunk.

- [ ] **Step 2: edit-config apply + insert on a COMING_SOON feed**

Feed 122 (`Crypto.GLM/USD`) has a REGULAR list; pick an insert case dynamically:

```bash
python3 -c "
import json
d = json.load(open('/tmp/lu_test.json'))
for f in d['feeds']:
    reg = next(s for s in f['marketSchedules'] if s['session'] == 'REGULAR')
    if 'allowedPublisherIds' not in reg:
        print(f['feedId'], f['symbol']); break
"
```

Then with the printed feed id `<FID>`:

```bash
python3 tools/edit-config/edit_config.py --config /tmp/lu_test.json --add-publisher 99 --feed-id <FID> --apply --no-backup
python3 -c "
import json
d = json.load(open('/tmp/lu_test.json'))
f = next(x for x in d['feeds'] if x['feedId'] == <FID>)
reg = next(s for s in f['marketSchedules'] if s['session'] == 'REGULAR')
assert reg['allowedPublisherIds'] == [99], reg
print('insert OK; file still valid JSON')
"
```

Expected: `insert OK; file still valid JSON`

- [ ] **Step 3: Guard rejects the old-format `after.json`**

```bash
python3 tools/edit-config/edit_config.py --config after.json --add-publisher 99 --feed-id 922; echo "exit=$?"
```

Expected: `ERROR: config contains feed-level allowedPublisherIds (old format)...`, `exit=1`

- [ ] **Step 4: apply_allowed dry-run on real data**

```bash
cp lazer_update.json /tmp/lu_apply.json
python3 -m lazer_dq.apply_allowed_to_config --xlsx dq_summary_lazer-prod_2026-06-01.xlsx --config /tmp/lu_apply.json --dry-run
```

Expected: exit 0, summary table printed, no traceback. Also confirm the guard:

```bash
python3 -m lazer_dq.apply_allowed_to_config --xlsx dq_summary_lazer-prod_2026-06-01.xlsx --config after.json --dry-run; echo "exit=$?"
```

Expected: `ERROR: ... old format ...`, `exit=1`. (If the workbook's feeds aren't in `lazer_update.json`, the run reports them as not-found — that is fine; the point is no crash and a clean summary.)

- [ ] **Step 5: Clean up**

```bash
rm -f /tmp/lu_test.json /tmp/lu_apply.json
```

---

## Part C — Documentation & wrap-up

### Task 10: Documentation

**Files:**

- Modify: `docs/apply_allowed_to_config.md`, `docs/edit_config.md`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: `docs/apply_allowed_to_config.md`**

Read the doc, then: delete every mention of `--asset-class`, `KNOWN_ASSET_CLASSES`, `SESSION_LEVEL_ASSET_CLASSES`, and top-level/feed-level `allowedPublisherIds` writes. Add a section near the top:

```markdown
## Config format (new format only)

This tool targets the session-level config format (`lazer_update.json` era):
publisher lists live ONLY inside `marketSchedules` session entries — there is
no feed-level `allowedPublisherIds`. The tool refuses to run against
old-format files (clear error at startup).

- Promotion writes per-session `allowedPublisherIds` and sets the feed-level
  `minPublishers` to 2.
- Session-level `minPublishers` is written only for `Equity.US.*` feeds
  (us-equities is the only asset class that carries it). hk-equities and all
  other classes get the session publisher list plus the feed-level
  `minPublishers` — their session entries never gain a `minPublishers` key.
- There is no `--asset-class` flag anymore: the workbook's session rows drive
  which sessions are written (hk workbooks emit only REGULAR rows), and
  US-equity detection is automatic by symbol prefix.
```

- [ ] **Step 2: `docs/edit_config.md`**

Read the doc, then update the `--session` scope documentation to the two tables from the spec (publisher ops vs min-publishers ops — copy them from `docs/superpowers/specs/2026-06-05-session-only-publisher-editing-design.md` section 3), and add:

```markdown
## Config format (new format only)

The editor targets the session-level config format (`lazer_update.json` era)
and refuses to run against configs that still carry feed-level
`allowedPublisherIds` (old format).

- Publisher ops edit session lists only. Default scope is the REGULAR
  session; `--session ALL` covers every session entry on the feed;
  `--session NONE` is an error for publisher ops.
- If a targeted session entry has no `allowedPublisherIds` key (common on
  COMING_SOON feeds), `--add-publisher` inserts it. The dry-run diff shows
  inserts as `(absent) -> [ ... ]`.
- minPublishers ops still edit the feed-level value. Session-level
  minPublishers is us-equities-only: non-US feeds take feed-level only
  (default and `--session ALL` degrade to feed-level; an explicit
  `--session REGULAR` etc. on a non-US feed is an error).
```

- [ ] **Step 3: `CLAUDE.md`**

In the Key Gotchas section, replace the `apply_allowed_to_config vs update_config_from_summary` bullet's last sentence-block with an updated one and add the format note. The bullet becomes:

```markdown
- **`apply_allowed_to_config` vs `update_config_from_summary`** — `lazer_dq/apply_allowed_to_config.py` consumes the `dq_summary` `.xlsx` "allowed" sheet (from `summarize_feeds.py`); `update_config_from_summary.py` consumes the `feed_readiness.py` CSV. The former only ever changes state on `COMING_SOON` feeds and never overwrites a live (`STABLE`) session — it only adds missing sessions to STABLE feeds. Both share `lib/json_surgery.py` for raw-text block surgery.
- **New config format (session-only publishers)** — `lazer_update.json`-era configs have NO feed-level `allowedPublisherIds`; publisher lists live only in `marketSchedules` session entries, and session-level `minPublishers` exists only on `Equity.US.*` feeds. `apply_allowed_to_config.py` and `tools/edit-config/edit_config.py` support ONLY this format and error out on old-format files (e.g. `after.json`). Other config tools (`update_config_from_summary.py`, `update_min_publishers.py`, the linter) still assume the old format.
```

Also update the Scripts-table row for `lazer_dq/apply_allowed_to_config.py`: change the example to drop nothing (it never showed `--asset-class`) but fix the description to "Apply dq_summary "allowed" sheet to a session-only config (promote COMING_SOON→STABLE + add sessions)".

- [ ] **Step 4: `CHANGELOG.md`**

Add an entry at the top following the file's existing format:

```markdown
### Changed

- `lazer_dq/apply_allowed_to_config.py` and `tools/edit-config/edit_config.py` now target the new session-only config format (`lazer_update.json` era): publisher lists are written only into `marketSchedules` session entries (no feed-level `allowedPublisherIds`), session-level `minPublishers` is written only for `Equity.US.*` feeds, and both tools refuse to run against old-format configs. `apply_allowed_to_config` loses its `--asset-class` flag (hk-equities flows through the same session path); `edit_config` publisher ops default to the REGULAR session (`--session NONE` is now valid only for min-publishers ops) and insert missing `allowedPublisherIds`/`minPublishers` keys.
```

- [ ] **Step 5: Commit**

```bash
pre-commit run --files docs/apply_allowed_to_config.md docs/edit_config.md CLAUDE.md CHANGELOG.md
git add docs/apply_allowed_to_config.md docs/edit_config.md CLAUDE.md CHANGELOG.md
git commit -m "docs: session-only publisher editing (new config format) for apply-allowed + edit-config"
```

### Task 11: Final verification

- [ ] **Step 1: Run all three test trees**

```bash
python3 -m pytest lazer_dq/tests -v
python3 -m pytest tools/edit-config/tests -v
python3 -m pytest tests/ -q
```

Expected: lazer_dq and edit-config suites ALL PASS. `tests/` must show no NEW failures versus `main` (it covers out-of-scope tools; if anything in it fails, confirm it also fails on `main` before proceeding — `git stash && python3 -m pytest tests/ -q && git stash pop`).

- [ ] **Step 2: Sanity-check no stragglers reference deleted symbols**

```bash
grep -rn "set_top_level_allowed\|write_session_fields\|SESSION_LEVEL_ASSET_CLASSES\|KNOWN_ASSET_CLASSES" --include="*.py" . | grep -v ".bak"
grep -rn "has_session_publishers" tools/ lazer_dq/ lib/ --include="*.py"
```

Expected: no matches (or matches only inside `docs/`/spec files).

- [ ] **Step 3: Commit any remaining cleanup**

```bash
git status --short
```

If clean, done. If not, review, `pre-commit run`, and commit with `chore(session-only): final cleanup`.

---

## Self-review checklist (already applied)

- Every spec section maps to a task: format guard → Tasks 3, 8; apply_allowed unification → Tasks 1–2; edit-config scope semantics → Task 7; inserts → Tasks 4, 5, 7; diff rendering → Task 6; us-equities-only session min → Tasks 1, 2, 7; hk fixture/test coverage → Tasks 2, 8; real-data sanity → Task 9; docs → Task 10.
- `--session` argparse choices in `edit_config.py` are intentionally UNCHANGED (NONE stays — it is valid for min ops; publisher ops reject it at op level with `OpError`).
- `SetState`, `--set-ric-mapping`, `--set-ric`, `FilterSet`, YAML parsing, and `lib/json_surgery.py` are intentionally untouched.
