# `--remove-ric` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--remove-ric` operation to `edit_config.py` that clears every `datascope_ric` identifier value on targeted feeds back to the empty string (`""`), keeping the surrounding JSON structure intact.

**Architecture:** Mirror the existing one-dataclass-per-op pattern. A new `ClearRic` op walks each feed's `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[]` slots and emits `Change(location="datascope_ric_identifier", after="")` records — which the existing text-surgery applier already knows how to write, so **no applier changes are needed**. A `--remove-ric` CLI flag and a `remove_ric` YAML op wire it in with the standard `FilterSet` targeting used by the publisher/min-publisher ops.

**Tech Stack:** Python 3.12, `dataclasses`, `argparse`, `pytest`, YAML specs via `pyyaml`.

**Spec:** `docs/superpowers/specs/2026-06-15-remove-ric-mapping-design.md`

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `tools/edit-config/edit_config_lib/config_ops.py` | Operation classes (`apply(feed) -> (changes, warnings)`) | **Add** `ClearRic` |
| `tools/edit-config/edit_config_lib/config_editor.py` | Plan building (CLI args + YAML), simulation, text apply | **Modify**: register op in `_OP_FLAGS`, `_BOOL_OP_FLAGS`, `build_op_from_args`, YAML helpers; import `ClearRic` |
| `tools/edit-config/edit_config.py` | CLI wrapper: argparse, plan summary, per-op footers | **Modify**: add `--remove-ric` flag, `_remove_ric_summary_lines`, summary-loop branch, import |
| `docs/edit_config.md` | Per-script docs | **Modify**: ops table row + `--remove-ric` section + YAML example |
| `CLAUDE.md` | Repo guide Scripts table | **Modify**: edit_config.py description (add "clear RIC identifiers") |
| `tools/edit-config/tests/test_config_ops.py` | Op-level unit tests | **Add** `ClearRic` tests |
| `tools/edit-config/tests/test_config_editor.py` | Plan-building + YAML tests | **Add** `--remove-ric` / `remove_ric` tests |
| `tools/edit-config/tests/test_edit_config_cli.py` | End-to-end CLI tests | **Add** `--remove-ric` CLI tests |

**Test run convention:** all commands run from the repo root
`/Users/mariobernardi/Documents/GitHub/integration-benchmarking`. The
`tools/edit-config/tests/conftest.py` puts `tools/edit-config` on `sys.path`, so
`edit_config_lib` / `edit_config` import correctly when invoked as
`python3 -m pytest tools/edit-config/tests/...`.

---

## Task 1: `ClearRic` operation class

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_ops.py` (add after `SetRicFromResolver`, before the `_STATE_WARNINGS` block near line 624)
- Test: `tools/edit-config/tests/test_config_ops.py` (append at end of file)

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
# ---------------------------------------------------------------------------
# ClearRic
# ---------------------------------------------------------------------------
from edit_config_lib.config_ops import ClearRic


def _ric_feed(feed_id, symbol, sessions, state="STABLE"):
    """Build a feed with datascope_ric slots. `sessions` is [(session, ident)]."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": state,
        "marketSchedules": [
            {
                "session": name,
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {
                                "identifier": ident,
                                "validFrom": "1970-01-01T00:00:00.000000000Z",
                            }
                        ]
                    }
                },
            }
            for (name, ident) in sessions
        ],
    }


def test_clear_ric_clears_populated_slot():
    feed = _ric_feed(885, "Equity.HK.0883-HK/HKD", [("REGULAR", "STALE.HK")])
    op = ClearRic()
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    c = changes[0]
    assert c.feed_id == 885
    assert c.location == "datascope_ric_identifier"
    assert c.field == "identifier"
    assert c.before == "STALE.HK"
    assert c.after == ""
    assert c.index == 0
    # working copy updated in place
    ident = feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
        "identifiers"
    ][0]["identifier"]
    assert ident == ""
    # one churn warning naming the wiped value
    assert any("STALE.HK" in w.message and "clearing" in w.message for w in warnings)


def test_clear_ric_already_empty_is_noop():
    feed = _ric_feed(884, "Equity.HK.0700-HK/HKD", [("REGULAR", "")])
    op = ClearRic()
    changes, warnings = op.apply(feed)
    assert changes == []
    assert warnings == []


def test_clear_ric_mixed_slots_only_clears_populated():
    feed = {
        "feedId": 990,
        "symbol": "Equity.US.BITS/USD",
        "state": "STABLE",
        "marketSchedules": [
            {
                "session": "REGULAR",
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {"identifier": "BITS.O"},
                            {"identifier": ""},
                        ]
                    }
                },
            }
        ],
    }
    op = ClearRic()
    changes, _ = op.apply(feed)
    assert [c.index for c in changes] == [0]
    assert changes[0].before == "BITS.O"
    assert changes[0].after == ""


def test_clear_ric_stable_feed_extra_warning():
    feed = _ric_feed(990, "Equity.US.BITS/USD", [("REGULAR", "BITS.O")], state="STABLE")
    op = ClearRic()
    _, warnings = op.apply(feed)
    assert any("STABLE feed" in w.message for w in warnings)


def test_clear_ric_non_stable_no_extra_warning():
    feed = _ric_feed(
        884, "Equity.HK.0700-HK/HKD", [("REGULAR", "0700.HK")], state="COMING_SOON"
    )
    op = ClearRic()
    _, warnings = op.apply(feed)
    assert not any("STABLE feed" in w.message for w in warnings)


def test_clear_ric_no_slots_warns():
    feed = {
        "feedId": 1000,
        "symbol": "Crypto.BTC/USD",
        "state": "STABLE",
        "marketSchedules": [{"session": "REGULAR", "benchmarkMapping": {}}],
    }
    op = ClearRic()
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "nothing to clear" in warnings[0].message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py -k clear_ric -v`
Expected: FAIL — `ImportError: cannot import name 'ClearRic' from 'edit_config_lib.config_ops'`

- [ ] **Step 3: Implement `ClearRic`**

In `tools/edit-config/edit_config_lib/config_ops.py`, insert this class immediately
after the `SetRicFromResolver` class definition (i.e. just before the
`_STATE_WARNINGS = {` line):

```python
@dataclass
class ClearRic:
    """Clear every datascope_ric identifier slot on a feed back to "".

    The structural inverse of SetRicMapping: it keeps the datascope_ric /
    identifiers[] scaffold intact and only empties the value strings. Reuses the
    `datascope_ric_identifier` Change location (after=""), so the text-surgery
    applier needs no changes.

    Per-slot semantics:
      - identifier == ""  -> NOOP (no Change).
      - identifier != ""  -> Change(after="") + Warning naming the wiped value.

    Per-feed semantics:
      - no datascope_ric identifier slots -> Warning ("nothing to clear").
      - state == STABLE with >=1 non-empty slot -> extra Warning (live benchmark).
    """

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        # Walk slots in document order — matches SetRicFromResolver and
        # config_text_surgery.find_ric_identifier_spans, so Change.index lines up.
        slots: list[dict] = []
        for schedule in feed.get("marketSchedules", []):
            bm = schedule.get("benchmarkMapping", {})
            ds = bm.get("datascope_ric", {})
            for ident in ds.get("identifiers", []) or []:
                if isinstance(ident, dict) and "identifier" in ident:
                    slots.append(ident)

        if not slots:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: no datascope_ric identifier slots — "
                        f"nothing to clear"
                    ),
                )
            ]

        changes: list[Change] = []
        warnings: list[Warning] = []
        for i, slot in enumerate(slots):
            current = slot["identifier"]
            if current == "":
                continue
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location="datascope_ric_identifier",
                    field="identifier",
                    before=current,
                    after="",
                    index=i,
                )
            )
            slot["identifier"] = ""
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f'feed {feed_id}: clearing identifier slot {i} '
                        f'({current!r} -> "")'
                    ),
                )
            )

        if changes and feed.get("state") == "STABLE":
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: clearing RIC on STABLE feed — "
                        f"breaks live benchmark"
                    ),
                )
            )

        return changes, warnings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py -k clear_ric -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): add ClearRic op to clear datascope_ric identifiers"
```

---

## Task 2: Wire `--remove-ric` into plan building (CLI args)

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_editor.py` (imports ~line 45-54; `_OP_FLAGS` ~line 65; `_BOOL_OP_FLAGS` ~line 103; `build_op_from_args` ~line 214-228)
- Test: `tools/edit-config/tests/test_config_editor.py` (append in the `TestBuildOpFromArgs` area)

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_editor.py` (end of file):

```python
# ---------------------------------------------------------------------------
# build_op_from_args: --remove-ric
# ---------------------------------------------------------------------------
from edit_config_lib.config_ops import ClearRic as _ClearRic


def test_build_remove_ric_targets_feed_ids():
    args = make_args(remove_ric=True, feed_id="884,885")
    ops = build_op_from_args(args)
    assert len(ops) == 1
    assert isinstance(ops[0].op, _ClearRic)
    assert ops[0].filters.feed_ids == {884, 885}


def test_build_remove_ric_by_symbol_pattern():
    args = make_args(remove_ric=True, symbol_pattern="Equity.HK.*")
    ops = build_op_from_args(args)
    assert isinstance(ops[0].op, _ClearRic)
    assert ops[0].filters.symbol_pattern == "Equity.HK.*"


def test_build_remove_ric_requires_targeting():
    args = make_args(remove_ric=True)
    with pytest.raises(ValueError, match="at least one"):
        build_op_from_args(args)
```

Also extend the `make_args` defaults in this file (the `defaults = dict(...)`
block near line 91) so the new flag is present. Add this line inside that dict:

```python
        remove_ric=False,
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k remove_ric -v`
Expected: FAIL — `build_op_from_args` raises `ValueError("no operation specified ...")` because `remove_ric` is not yet a recognized op flag (the import of `ClearRic` succeeds since Task 1 added it).

- [ ] **Step 3: Register the op**

In `tools/edit-config/edit_config_lib/config_editor.py`:

(a) Add `ClearRic` to the `config_ops` import block (the `from
edit_config_lib.config_ops import (...)` near line 45):

```python
from edit_config_lib.config_ops import (
    AddPublisher,
    RemovePublisher,
    SetMinPublishers,
    BumpMinPublishers,
    SetState,
    SetRicMapping,
    SetRicFromResolver,
    ResolvedRic,
    ClearRic,
)
```

(b) Add `"remove_ric"` to the `_OP_FLAGS` tuple (near line 65):

```python
_OP_FLAGS = (
    "add_publisher",
    "remove_publisher",
    "set_min_publishers",
    "bump_min_publishers",
    "set_state",
    "set_ric_mapping",
    "set_ric",
    "remove_ric",
)
```

(c) Add `"remove_ric"` to `_BOOL_OP_FLAGS` (near line 103):

```python
_BOOL_OP_FLAGS = frozenset({"set_ric_mapping", "set_ric", "remove_ric"})
```

(d) In `build_op_from_args`, add a branch in the trailing FilterSet-based
if/elif chain (the block starting `if name == "add_publisher":` near line 216).
Add this branch (e.g. right after the `set_state` branch, before the final
`else: raise AssertionError`):

```python
    elif name == "remove_ric":
        op = ClearRic()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k remove_ric -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full editor test file to check no regressions**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -v`
Expected: PASS (all existing tests still green)

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): wire --remove-ric into CLI plan building"
```

---

## Task 3: YAML spec support (`remove_ric`)

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_editor.py` (`_OP_REQUIRED_FIELDS` ~line 236; `_build_op_from_yaml_entry` ~line 310-342)
- Test: `tools/edit-config/tests/test_config_editor.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
def test_yaml_remove_ric_parses(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "version: 1\n"
        "operations:\n"
        "  - op: remove_ric\n"
        "    feed_id: \"884,885\"\n",
        encoding="utf-8",
    )
    ops = parse_yaml_spec(str(spec))
    assert len(ops) == 1
    assert isinstance(ops[0].op, _ClearRic)
    assert ops[0].filters.feed_ids == {884, 885}


def test_yaml_remove_ric_requires_targeting(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "operations:\n  - op: remove_ric\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="at least one"):
        parse_yaml_spec(str(spec))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k "yaml_remove_ric" -v`
Expected: FAIL — `parse_yaml_spec` raises `ValueError("unknown op 'remove_ric'")`

- [ ] **Step 3: Add YAML wiring**

In `tools/edit-config/edit_config_lib/config_editor.py`:

(a) Add an entry to `_OP_REQUIRED_FIELDS` (near line 236). `remove_ric` needs no
op-specific fields beyond targeting, so map it to an empty set:

```python
_OP_REQUIRED_FIELDS = {
    "add_publisher": {"publisher_id"},
    "remove_publisher": {"publisher_id"},
    "set_min_publishers": {"value"},
    "bump_min_publishers": {"delta"},
    "set_state": {"value"},
    "set_ric_mapping": {"from_csv"},
    "remove_ric": set(),
}
```

(b) In `_build_op_from_yaml_entry`, add a branch returning the op (e.g. right
before the final `raise AssertionError(f"unhandled op {op_name}")`):

```python
    if op_name == "remove_ric":
        return ClearRic()
```

Note: `parse_yaml_spec`'s filter logic already routes every op except
`set_ric_mapping` through `_filters_from_yaml_entry`, which enforces the
≥1-targeting-key requirement — so `remove_ric` gets targeting validation for free.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k "yaml_remove_ric" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): support remove_ric in YAML specs"
```

---

## Task 4: CLI flag, summary footer, and end-to-end tests

**Files:**
- Modify: `tools/edit-config/edit_config.py` (imports ~line 25-30; argparse op group ~line 114-122; per-op summary loop ~line 271-282; add `_remove_ric_summary_lines` near the other summary helpers ~line 60-87)
- Test: `tools/edit-config/tests/test_edit_config_cli.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_edit_config_cli.py`:

```python
# ---------------------------------------------------------------------------
# --remove-ric (uses the hk_sample.json fixture: 885 = STALE.HK populated,
# 884/886 = empty, 1000 = no datascope_ric slots)
# ---------------------------------------------------------------------------
def test_cli_remove_ric_dry_run_does_not_write(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    before = config.read_text()
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "885"]
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "[DRY RUN]" in out
    assert "RIC removal summary" in out
    assert "STALE.HK" in out  # the value being wiped is shown
    assert config.read_text() == before  # nothing written


def test_cli_remove_ric_apply_clears_value(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "885", "--apply"]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(config.read_text())
    feeds_by_id = {f["feedId"]: f for f in data["feeds"]}
    cleared = feeds_by_id[885]["marketSchedules"][0]["benchmarkMapping"][
        "datascope_ric"
    ]["identifiers"][0]["identifier"]
    assert cleared == ""


def test_cli_remove_ric_already_empty_no_changes(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    # Feed 884 already has an empty identifier -> nothing to clear.
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "884", "--apply"]
    )
    assert result.returncode == 0, result.stderr
    assert "No changes to write." in (result.stdout + result.stderr)


def test_cli_remove_ric_no_slots_warns(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    # Feed 1000 (Crypto.BTC) has empty marketSchedules -> no slots warning.
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "1000"]
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "nothing to clear" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py -k remove_ric -v`
Expected: FAIL — argparse rejects the unknown flag (`error: unrecognized arguments: --remove-ric`), so the CLI exits non-zero.

- [ ] **Step 3: Add the argparse flag**

In `tools/edit-config/edit_config.py`, add to the mutually-exclusive `op_group`
(right after the `--set-ric` argument block, near line 122):

```python
    op_group.add_argument(
        "--remove-ric",
        action="store_true",
        help=(
            'Clear all datascope_ric identifier values to "" on targeted feeds '
            "(inverse of --set-ric-mapping). Target with the usual filters."
        ),
    )
```

- [ ] **Step 4: Add the summary-footer helper**

In `tools/edit-config/edit_config.py`, add this function next to the other
summary helpers (after `_set_ric_summary_lines`, near line 88):

```python
def _remove_ric_summary_lines(
    op: "ClearRic",
    changes: list[Change],
    warnings: list[Warning],
) -> list[str]:
    """Return extra summary lines for a ClearRic operation.

    `op` is accepted for call-site parity with the other summary helpers; the
    stats are derived from `changes` and `warnings`.
    """
    cleared = sum(1 for c in changes if c.location == "datascope_ric_identifier")
    no_slots = sum(1 for w in warnings if "nothing to clear" in w.message)
    stable = sum(1 for w in warnings if "STABLE feed" in w.message)
    return [
        "",
        "RIC removal summary:",
        f"  identifiers cleared:    {cleared}",
        f"  feeds with no slots:    {no_slots}",
        f"  STABLE feeds affected:  {stable}",
    ]
```

- [ ] **Step 5: Import `ClearRic` and add the summary-loop branch**

(a) Add `ClearRic` to the `config_ops` import in `edit_config.py` (near line 25):

```python
from edit_config_lib.config_ops import (  # noqa: E402
    Change,
    SetRicMapping,
    SetRicFromResolver,
    ClearRic,
    Warning,
)
```

(b) In `main`, extend the per-op summary loop (near line 272) with a `ClearRic`
branch:

```python
    for planned in plan:
        if isinstance(planned.op, SetRicMapping):
            for line in _set_ric_mapping_summary_lines(
                planned.op, result.changes, result.warnings
            ):
                print(line)
        elif isinstance(planned.op, SetRicFromResolver):
            for line in _set_ric_summary_lines(
                planned.op, result.changes, result.warnings
            ):
                print(line)
        elif isinstance(planned.op, ClearRic):
            for line in _remove_ric_summary_lines(
                planned.op, result.changes, result.warnings
            ):
                print(line)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py -k remove_ric -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Run the entire edit-config test suite**

Run: `python3 -m pytest tools/edit-config/tests/ -v`
Expected: PASS (all tests green — new + pre-existing)

- [ ] **Step 8: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat(edit-config): add --remove-ric CLI flag and summary footer"
```

---

## Task 5: Documentation

**Files:**
- Modify: `docs/edit_config.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the operations-table row in `docs/edit_config.md`**

In the "Operations (exactly one per CLI invocation)" table (near line 39-47),
add a row after the `--set-ric-mapping` row:

```markdown
| `--remove-ric`                              | Clear all `datascope_ric` identifier values to `""`      |
```

- [ ] **Step 2: Add a `--remove-ric` section in `docs/edit_config.md`**

Insert this section after the `### --set-ric-mapping ...` section (after the YAML
spec form block near line 190, before `## YAML spec format`):

```markdown
### `--remove-ric` — clear `datascope_ric` identifiers

The structural inverse of `--set-ric-mapping`: clears **every**
`datascope_ric.identifiers[].identifier` value on each targeted feed back to the
empty string (`""`), leaving the `datascope_ric` / `identifiers[]` scaffold in
place. Use it when a feed was onboarded with a wrong RIC, or an asset is delisted
and its mapping should be removed.

```bash
# dry-run (default)
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --remove-ric --feed-id 885

# write
python3 tools/edit-config/edit_config.py --config lazer_update.json \
    --remove-ric --feed-id 885 --apply
```

Per-slot rules:

- Non-empty `identifier` → cleared to `""`, with a warning naming the wiped value.
- Already-empty `identifier` → NOOP (no change, no warning).
- Feed with no `datascope_ric` identifier slots → "nothing to clear" warning.

Safety:

- **Dry-run is the default** — review the diff and the RIC removal summary before
  re-running with `--apply`.
- A targeted **STABLE** feed with a populated RIC triggers an extra warning
  (clearing it breaks a live benchmark).
- INACTIVE feeds are skipped (reactivate via `--set-state` first).

Targeting uses the full filter set (`--feed-id`, `--feed-ids-from`,
`--symbol-pattern`, `--asset-class`, `--state`) — the same model as the
publisher/min-publisher ops. A broad `--symbol-pattern` / `--asset-class` can
match many feeds, so the matched-feed count, full diff, and per-value warnings
in the dry-run are your blast-radius check.

YAML spec form:

```yaml
version: 1
operations:
  - op: remove_ric
    feed_id: "884,885"
```
```

- [ ] **Step 3: Update the `CLAUDE.md` Scripts-table description**

In `CLAUDE.md`, the `tools/edit-config/edit_config.py` row currently ends with
"set RIC identifiers". Update that clause to include clearing:

Find:

```
| `tools/edit-config/edit_config.py`     | Surgical editor: add/remove publishers, set minPublishers, set state, set RIC identifiers              |
```

Replace with:

```
| `tools/edit-config/edit_config.py`     | Surgical editor: add/remove publishers, set minPublishers, set state, set/clear RIC identifiers        |
```

- [ ] **Step 4: Run pre-commit on the changed docs**

Run:
```bash
pre-commit run --files docs/edit_config.md CLAUDE.md
```
Expected: hooks pass (prettier may reformat the Markdown tables — if it modifies
files, re-stage them and re-run until clean).

- [ ] **Step 5: Commit**

```bash
git add docs/edit_config.md CLAUDE.md
git commit -m "docs: document --remove-ric in edit_config.py"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run the full edit-config test suite once more**

Run: `python3 -m pytest tools/edit-config/tests/ -v`
Expected: PASS (all tests green)

- [ ] **Step 2: Run pre-commit across all changed files**

Run:
```bash
pre-commit run --files \
  tools/edit-config/edit_config.py \
  tools/edit-config/edit_config_lib/config_ops.py \
  tools/edit-config/edit_config_lib/config_editor.py \
  tools/edit-config/tests/test_config_ops.py \
  tools/edit-config/tests/test_config_editor.py \
  tools/edit-config/tests/test_edit_config_cli.py \
  docs/edit_config.md \
  CLAUDE.md
```
Expected: black / prettier / trailing-whitespace / end-of-file hooks all pass.
If any hook reformats a file, re-stage and amend the relevant commit (or add a
fixup commit).

- [ ] **Step 3: Manual smoke test against the real config**

Run (dry-run only — no `--apply`):
```bash
python3 tools/edit-config/edit_config.py --config after.json --remove-ric --feed-id 885 2>&1 | head -40
```
Note: `after.json` is the OLD config format and the tool will reject it with an
"old format" error — that's expected and confirms the guard still fires. To smoke
the happy path, point `--config` at a session-only (`lazer_update.json`-era)
config if one is available, otherwise rely on the CLI tests from Task 4.

- [ ] **Step 4: Confirm clean working tree**

Run: `git status`
Expected: all changes committed; no stray modified files.

---

## Self-Review Notes

- **Spec coverage:** `ClearRic` op (Task 1) → spec "New op — ClearRic". CLI flag +
  footer (Task 4) → spec "CLI". Op-flag registration (Task 2) → spec "Op-flag
  registration". YAML (Task 3) → spec "YAML spec support". Docs (Task 5) → spec
  "Docs". No applier changes — matches spec "Applier — no change". INACTIVE skip is
  inherited from `simulate_plan` (spec "INACTIVE feeds"); covered indirectly, no new
  code needed.
- **Type consistency:** the op is named `ClearRic` everywhere (op class, imports in
  `config_editor.py` and `edit_config.py`, `_build_op_from_yaml_entry`, summary
  helper type hint). CLI/YAML names are `--remove-ric` / `remove_ric`. `Change`
  uses `location="datascope_ric_identifier"`, `field="identifier"`, `after=""`,
  `index=<global slot index>` — identical to `SetRicMapping`/`SetRicFromResolver`.
- **No placeholders:** every code/step block contains the actual content.
```
