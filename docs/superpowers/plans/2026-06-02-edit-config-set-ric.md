# edit-config `--set-ric` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--set-ric` operation to `edit_config.py` that resolves each targeted feed id through `generate_ric_mapping`'s `RICResolver` and overwrites its per-session `datascope_ric` identifier slots (day sessions → `TICKER.<exch>`, OVER_NIGHT → `TICKER.BLUE`), following the feed 922 pattern.

**Architecture:** Three layers, mirroring the existing `--set-ric-mapping` (HK) path. (1) A pure op `SetRicFromResolver` in `config_ops.py` that takes a plain `feed_id → ResolvedRic` map and emits `datascope_ric_identifier` Changes through the existing text-surgery applier — no network, fully unit-testable. (2) A `resolve_rics_for_feed_ids` helper in `config_editor.py` that lazily imports `RICResolver` and builds that map. (3) CLI wiring + summary output in `edit_config.py`. The op only _replaces_ existing identifier slots; it never inserts new sessions.

**Tech Stack:** Python 3.11+, pytest. Reuses `generate_ric_mapping.RICResolver` / `ticker_to_ric_base`, and the existing `edit_config_lib` modules (`config_ops`, `config_editor`, `config_text_surgery`).

---

## Reference: resolver convention (from `generate_ric_mapping.py`)

`RICResolver(symbols_path).resolve_by_id(feed_id)` returns a `RICResult` with `.ric`, `.display_ticker`, `.confidence`, `.warnings`. US-equity RICs:

- NASDAQ-listed → `{base}.O`
- IEX (`V`) → `{base}.K`
- Other US-consolidated (NYSE `N`, Arca `P`, American `A`, Cboe `Z`, unknown) → `{base}.K` when the ticker root is ≥ 4 chars, else **bare**. Examples: `CTRA` → `CTRA.K`; `XLF` → `XLF`; `RIO` → `RIO`; `O` → `O`.

Overnight RIC = `{ticker_to_ric_base(display_ticker)}.BLUE`.

## File Structure

- **Modify** `tools/edit-config/edit_config_lib/config_ops.py` — add `ResolvedRic` dataclass + `SetRicFromResolver` op.
- **Modify** `tools/edit-config/edit_config_lib/config_editor.py` — add `resolve_rics_for_feed_ids` helper; register `set_ric` in `_OP_FLAGS` / `_BOOL_OP_FLAGS`; handle it in `build_op_from_args`.
- **Modify** `tools/edit-config/edit_config.py` — add `--set-ric`, `--symbols`, `--force-refresh` flags; add `_set_ric_summary_lines`; print it in the per-op summary loop.
- **Modify** `tools/edit-config/tests/test_config_ops.py` — unit tests for `SetRicFromResolver`.
- **Modify** `tools/edit-config/tests/test_config_editor.py` — unit test for `resolve_rics_for_feed_ids` (injected fake resolver).
- **Modify** `tools/edit-config/tests/test_edit_config_cli.py` — in-process `main()` test with patched resolver (no network).
- **Modify** `docs/edit_config.md` and `CLAUDE.md` — document the new operation.

---

## Task 1: `ResolvedRic` + `SetRicFromResolver` op (pure, no network)

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_ops.py` (append after the `SetRicMapping` class, before `_STATE_WARNINGS`)
- Test: `tools/edit-config/tests/test_config_ops.py` (append at end)

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
# ---------------------------------------------------------------------------
# SetRicFromResolver
# ---------------------------------------------------------------------------
from edit_config_lib.config_ops import ResolvedRic, SetRicFromResolver


def _us_feed(feed_id: int, ticker: str, sessions: list[tuple[str, str]]) -> dict:
    """Build a US-equity feed. `sessions` is [(session_name, identifier_value)]."""
    return {
        "feedId": feed_id,
        "symbol": f"Equity.US.{ticker}/USD",
        "state": "STABLE",
        "metadata": {"name": ticker, "asset_type": "equity"},
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


def test_set_ric_rewrites_bare_day_sessions_overnight_noop():
    feed = _us_feed(
        990,
        "BITS",
        [
            ("REGULAR", "BITS"),
            ("PRE_MARKET", "BITS"),
            ("POST_MARKET", "BITS"),
            ("OVER_NIGHT", "BITS.BLUE"),
        ],
    )
    op = SetRicFromResolver(
        rics={990: ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert [c.index for c in changes] == [0, 1, 2]  # 3 day slots, overnight NOOP
    assert all(c.after == "BITS.O" for c in changes)
    assert all(c.before == "BITS" for c in changes)
    assert len(warnings) == 3  # overwriting non-empty -> churn warning each
    assert all("overwriting identifier slot" in w.message for w in warnings)


def test_set_ric_fills_empty_slot_no_warning():
    feed = _us_feed(1703, "IWDA", [("REGULAR", "")])
    op = SetRicFromResolver(
        rics={1703: ResolvedRic(day_ric="IWDA.O", overnight_ric="IWDA.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].before == ""
    assert changes[0].after == "IWDA.O"
    assert changes[0].index == 0
    assert warnings == []  # filling empty is not churn


def test_set_ric_rewrites_wrong_suffix_with_churn_warning():
    feed = _us_feed(1059, "CTRA", [("REGULAR", "CTRA.N")])
    op = SetRicFromResolver(
        rics={1059: ResolvedRic(day_ric="CTRA.K", overnight_ric="CTRA.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].before == "CTRA.N"
    assert changes[0].after == "CTRA.K"
    assert len(warnings) == 1
    assert "CTRA.N" in warnings[0].message and "CTRA.K" in warnings[0].message


def test_set_ric_all_correct_is_noop():
    feed = _us_feed(
        922, "AAPL", [("REGULAR", "AAPL.O"), ("OVER_NIGHT", "AAPL.BLUE")]
    )
    op = SetRicFromResolver(
        rics={922: ResolvedRic(day_ric="AAPL.O", overnight_ric="AAPL.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert changes == []
    assert warnings == []


def test_set_ric_overnight_slot_rewritten_when_wrong():
    feed = _us_feed(990, "BITS", [("OVER_NIGHT", "WRONG")])
    op = SetRicFromResolver(
        rics={990: ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].after == "BITS.BLUE"


def test_set_ric_no_identifier_slots_warns():
    feed = {
        "feedId": 999,
        "symbol": "Equity.US.FOO/USD",
        "state": "STABLE",
        "marketSchedules": [{"session": "REGULAR", "benchmarkMapping": {}}],
    }
    op = SetRicFromResolver(
        rics={999: ResolvedRic(day_ric="FOO.O", overnight_ric="FOO.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no datascope_ric identifier slots" in warnings[0].message


def test_set_ric_unresolved_feed_warns():
    feed = _us_feed(990, "BITS", [("REGULAR", "BITS")])
    # empty day_ric == resolver could not resolve
    op = SetRicFromResolver(rics={990: ResolvedRic(day_ric="", overnight_ric="")})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no RIC resolved" in warnings[0].message


def test_set_ric_feed_absent_from_map_warns():
    feed = _us_feed(990, "BITS", [("REGULAR", "BITS")])
    op = SetRicFromResolver(rics={})  # 990 not present
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no RIC resolved" in warnings[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_ops.py -k set_ric_ -v`
Expected: FAIL — `ImportError: cannot import name 'ResolvedRic'` (and `SetRicFromResolver`).

- [ ] **Step 3: Implement `ResolvedRic` + `SetRicFromResolver`**

In `tools/edit-config/edit_config_lib/config_ops.py`, insert immediately after the `SetRicMapping` class (after its final `return changes, warnings`, before the `_STATE_WARNINGS = {` line):

```python
@dataclass(frozen=True)
class ResolvedRic:
    """A feed's resolved Datascope RICs, consumed by SetRicFromResolver.

    `day_ric` applies to REGULAR/PRE_MARKET/POST_MARKET sessions; `overnight_ric`
    (the `TICKER.BLUE` form) applies to OVER_NIGHT. An empty `day_ric` means the
    resolver could not derive a RIC for the feed.
    """

    day_ric: str
    overnight_ric: str
    confidence: str = ""
    warnings: tuple[str, ...] = ()


@dataclass
class SetRicFromResolver:
    """Overwrite `datascope_ric` identifier slots from pre-resolved RICs.

    `rics` maps feedId -> ResolvedRic. Per identifier slot the target value is
    `overnight_ric` when the slot's session is OVER_NIGHT, else `day_ric`. Slots
    already equal to the target are NOOPs; differing slots (empty, bare, or
    wrong) are overwritten. Overwriting a non-empty value also emits a Warning so
    the dry-run diff surfaces churn (e.g. CTRA.N -> CTRA.K). Reuses the
    `datascope_ric_identifier` Change location, so the text-surgery applier needs
    no changes.

    Per-feed semantics:
      - feedId absent from `rics`, or `day_ric` empty -> Warning (unresolved).
      - feed has no datascope_ric identifier slots -> Warning (cannot insert).
    """

    rics: dict[int, ResolvedRic]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        resolved = self.rics.get(feed_id)
        if resolved is None or not resolved.day_ric:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=f"feed {feed_id}: no RIC resolved — skipped",
                )
            ]

        # (session, identifier-dict) pairs in document order. Order matches
        # config_text_surgery.find_ric_identifier_spans, so Change.index lines up.
        slots: list[tuple[str, dict]] = []
        for schedule in feed.get("marketSchedules", []):
            session = schedule.get("session", "")
            bm = schedule.get("benchmarkMapping", {})
            ds = bm.get("datascope_ric", {})
            for ident in ds.get("identifiers", []) or []:
                if isinstance(ident, dict) and "identifier" in ident:
                    slots.append((session, ident))

        if not slots:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: no datascope_ric identifier slots — skipped"
                    ),
                )
            ]

        changes: list[Change] = []
        warnings: list[Warning] = []
        for i, (session, slot) in enumerate(slots):
            target = (
                resolved.overnight_ric
                if session == "OVER_NIGHT"
                else resolved.day_ric
            )
            current = slot["identifier"]
            if current == target:
                continue
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location="datascope_ric_identifier",
                    field="identifier",
                    before=current,
                    after=target,
                    index=i,
                )
            )
            slot["identifier"] = target
            if current != "":
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: overwriting identifier slot {i} "
                            f"({current!r} -> {target!r})"
                        ),
                    )
                )
        return changes, warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_ops.py -k set_ric_ -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): add SetRicFromResolver op + ResolvedRic"
```

---

## Task 2: `resolve_rics_for_feed_ids` helper

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py` (add helper near the other `config_ops` imports; update the `config_ops` import line)
- Test: `tools/edit-config/tests/test_config_editor.py` (append at end)

- [ ] **Step 1: Write the failing test**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
# ---------------------------------------------------------------------------
# resolve_rics_for_feed_ids
# ---------------------------------------------------------------------------
from dataclasses import dataclass as _dc
from edit_config_lib.config_editor import resolve_rics_for_feed_ids


@_dc
class _FakeResult:
    ric: str
    display_ticker: str
    confidence: str = "medium"
    warnings: tuple = ()


class _FakeResolver:
    def __init__(self, mapping):
        self._mapping = mapping  # feed_id -> _FakeResult

    def resolve_by_id(self, fid):
        return self._mapping.get(fid, _FakeResult(ric="", display_ticker=str(fid)))


def test_resolve_rics_builds_day_and_overnight():
    fake = _FakeResolver(
        {
            922: _FakeResult(ric="AAPL.O", display_ticker="AAPL"),
            1059: _FakeResult(ric="CTRA.K", display_ticker="CTRA"),
        }
    )
    out = resolve_rics_for_feed_ids(
        [922, 1059], symbols_path="unused.json", resolver=fake
    )
    assert out[922].day_ric == "AAPL.O"
    assert out[922].overnight_ric == "AAPL.BLUE"
    assert out[1059].day_ric == "CTRA.K"
    assert out[1059].overnight_ric == "CTRA.BLUE"


def test_resolve_rics_unresolved_has_empty_day_ric():
    fake = _FakeResolver({})  # nothing resolves
    out = resolve_rics_for_feed_ids([990], symbols_path="unused.json", resolver=fake)
    assert out[990].day_ric == ""
    assert out[990].overnight_ric == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -k resolve_rics -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_rics_for_feed_ids'`.

- [ ] **Step 3: Implement the helper**

In `tools/edit-config/edit_config_lib/config_editor.py`, update the `config_ops` import (around line 44-51) to also import `ResolvedRic` and `SetRicFromResolver`:

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
)
```

Then add this function immediately after that import block (before `from edit_config_lib.config_selector import ...`, or right after the `PlannedOp` dataclass — anywhere at module scope above `build_op_from_args`):

```python
def resolve_rics_for_feed_ids(
    feed_ids: list[int],
    symbols_path: str,
    force_refresh: bool = False,
    resolver=None,
) -> dict[int, ResolvedRic]:
    """Resolve each feed id to its Datascope RICs via generate_ric_mapping.

    day_ric is the resolver RIC (e.g. AAPL.O); overnight_ric is
    `{ticker_to_ric_base(display_ticker)}.BLUE`. `generate_ric_mapping` lives at
    the repo root and is imported lazily (with the repo root added to sys.path)
    so config_editor carries no hard dependency on it until --set-ric is used.
    Importing the module has no network side effects — the NASDAQ-Trader fetch
    only happens when RICResolver actually resolves an equity.

    `resolver` is an injection point for tests; production passes None.
    """
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from generate_ric_mapping import RICResolver, ticker_to_ric_base

    if resolver is None:
        resolver = RICResolver(
            symbols_path=Path(symbols_path), force_refresh=force_refresh
        )

    out: dict[int, ResolvedRic] = {}
    for fid in feed_ids:
        result = resolver.resolve_by_id(fid)
        day_ric = result.ric or ""
        display = result.display_ticker or ""
        overnight_ric = (
            f"{ticker_to_ric_base(display)}.BLUE" if day_ric and display else ""
        )
        out[fid] = ResolvedRic(
            day_ric=day_ric,
            overnight_ric=overnight_ric,
            confidence=result.confidence or "",
            warnings=tuple(result.warnings or ()),
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -k resolve_rics -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): add resolve_rics_for_feed_ids helper"
```

---

## Task 3: Wire `set_ric` into `build_op_from_args`

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py:62-69` (`_OP_FLAGS`), `:99` (`_BOOL_OP_FLAGS`), and `build_op_from_args` (`:109-160`)
- Test: `tools/edit-config/tests/test_config_editor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
# ---------------------------------------------------------------------------
# build_op_from_args: --set-ric
# ---------------------------------------------------------------------------
import argparse as _argparse
from edit_config_lib import config_editor as _ce
from edit_config_lib.config_editor import build_op_from_args
from edit_config_lib.config_ops import SetRicFromResolver as _SetRicFromResolver


def _ric_args(**overrides):
    base = dict(
        config="after.json",
        add_publisher=None,
        remove_publisher=None,
        set_min_publishers=None,
        bump_min_publishers=None,
        set_state=None,
        from_spec=None,
        set_ric_mapping=False,
        set_ric=False,
        from_csv=None,
        feed_id=None,
        feed_ids_from=None,
        symbol_pattern=None,
        asset_class=None,
        state=None,
        session=None,
        symbols=None,
        force_refresh=False,
    )
    base.update(overrides)
    return _argparse.Namespace(**base)


def test_build_set_ric_requires_feed_id(monkeypatch):
    monkeypatch.setattr(
        _ce, "resolve_rics_for_feed_ids", lambda *a, **k: {}
    )
    args = _ric_args(set_ric=True, symbol_pattern="Equity.US.*")
    with pytest.raises(ValueError, match="requires --feed-id"):
        build_op_from_args(args)


def test_build_set_ric_resolves_targeted_ids(monkeypatch):
    captured = {}

    def fake_resolve(feed_ids, symbols_path, force_refresh=False, resolver=None):
        captured["feed_ids"] = feed_ids
        captured["symbols_path"] = symbols_path
        from edit_config_lib.config_ops import ResolvedRic

        return {fid: ResolvedRic(day_ric="X.O", overnight_ric="X.BLUE") for fid in feed_ids}

    monkeypatch.setattr(_ce, "resolve_rics_for_feed_ids", fake_resolve)
    args = _ric_args(set_ric=True, feed_id="990,1059", config="my_after.json")
    plan = build_op_from_args(args)
    assert len(plan) == 1
    assert isinstance(plan[0].op, _SetRicFromResolver)
    assert plan[0].filters.feed_ids == {990, 1059}
    assert captured["feed_ids"] == [990, 1059]  # sorted
    assert captured["symbols_path"] == "my_after.json"  # defaults to --config
```

Note: `pytest` is already imported at the top of `test_config_editor.py`. If not, add `import pytest`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -k set_ric -v`
Expected: FAIL — `set_ric` not in `_OP_FLAGS`, so `build_op_from_args` raises "no operation specified".

- [ ] **Step 3: Register and handle `set_ric`**

In `config_editor.py`, add `"set_ric"` to `_OP_FLAGS`:

```python
_OP_FLAGS = (
    "add_publisher",
    "remove_publisher",
    "set_min_publishers",
    "bump_min_publishers",
    "set_state",
    "set_ric_mapping",
    "set_ric",
)
```

Add `"set_ric"` to `_BOOL_OP_FLAGS`:

```python
_BOOL_OP_FLAGS = frozenset({"set_ric_mapping", "set_ric"})
```

In `build_op_from_args`, add a branch immediately after the existing `if name == "set_ric_mapping":` block returns (i.e. right before the `filters = _build_filters_from_args(args)` line near the end of the function):

```python
    if name == "set_ric":
        filters = _build_filters_from_args(args)
        if not filters.feed_ids:
            raise ValueError(
                "--set-ric requires --feed-id or --feed-ids-from targeting"
            )
        symbols_path = getattr(args, "symbols", None) or args.config
        force_refresh = getattr(args, "force_refresh", False)
        rics = resolve_rics_for_feed_ids(
            sorted(filters.feed_ids),
            symbols_path=symbols_path,
            force_refresh=force_refresh,
        )
        op = SetRicFromResolver(rics=rics)
        return [PlannedOp(op=op, filters=filters)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -k set_ric -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): wire --set-ric into build_op_from_args"
```

---

## Task 4: CLI flags + summary output

**Files:**

- Modify: `tools/edit-config/edit_config.py` (`_build_parser`, the `config_ops` import at line 25, and the per-op summary loop at lines 210-215; add `_set_ric_summary_lines`)
- Test: `tools/edit-config/tests/test_edit_config_cli.py` (append; runs `main()` in-process with a patched resolver — no network)

- [ ] **Step 1: Write the failing test**

Append to `tools/edit-config/tests/test_edit_config_cli.py`:

```python
# ---------------------------------------------------------------------------
# --set-ric (in-process, patched resolver — no network)
# ---------------------------------------------------------------------------
import edit_config

from edit_config_lib import config_editor as _ce
from edit_config_lib.config_ops import ResolvedRic as _ResolvedRic


def _write_us_config(path):
    cfg = {
        "feeds": [
            {
                "feedId": 990,
                "symbol": "Equity.US.BITS/USD",
                "state": "STABLE",
                "metadata": {"name": "BITS", "asset_type": "equity"},
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "benchmarkMapping": {
                            "datascope_ric": {
                                "identifiers": [{"identifier": "BITS"}]
                            }
                        },
                    },
                    {
                        "session": "OVER_NIGHT",
                        "benchmarkMapping": {
                            "datascope_ric": {
                                "identifiers": [{"identifier": "BITS.BLUE"}]
                            }
                        },
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def test_cli_set_ric_apply_in_process(tmp_path, monkeypatch):
    config = tmp_path / "after.json"
    _write_us_config(config)

    def fake_resolve(feed_ids, symbols_path, force_refresh=False, resolver=None):
        return {990: _ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}

    monkeypatch.setattr(_ce, "resolve_rics_for_feed_ids", fake_resolve)

    rc = edit_config.main(
        ["--config", str(config), "--set-ric", "--feed-id", "990", "--apply"]
    )
    assert rc == 0
    data = json.loads(config.read_text())
    feed = data["feeds"][0]
    reg = feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
        "identifiers"
    ][0]["identifier"]
    ovn = feed["marketSchedules"][1]["benchmarkMapping"]["datascope_ric"][
        "identifiers"
    ][0]["identifier"]
    assert reg == "BITS.O"  # bare day RIC rewritten
    assert ovn == "BITS.BLUE"  # overnight unchanged


def test_cli_set_ric_dry_run_does_not_write(tmp_path, monkeypatch):
    config = tmp_path / "after.json"
    _write_us_config(config)
    before = config.read_text()

    def fake_resolve(feed_ids, symbols_path, force_refresh=False, resolver=None):
        return {990: _ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}

    monkeypatch.setattr(_ce, "resolve_rics_for_feed_ids", fake_resolve)

    rc = edit_config.main(["--config", str(config), "--set-ric", "--feed-id", "990"])
    assert rc == 0
    assert config.read_text() == before  # dry-run default, nothing written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/edit-config && python3 -m pytest tests/test_edit_config_cli.py -k set_ric -v`
Expected: FAIL — argparse rejects unknown argument `--set-ric` (SystemExit / nonzero), so `main` never returns 0.

- [ ] **Step 3: Add CLI flags + summary**

In `edit_config.py`, update the import at line 25:

```python
from edit_config_lib.config_ops import (  # noqa: E402
    Change,
    SetRicMapping,
    SetRicFromResolver,
    Warning,
)
```

In `_build_parser`, add to the mutually-exclusive `op_group` (after `--set-ric-mapping`):

```python
    op_group.add_argument(
        "--set-ric",
        action="store_true",
        help=(
            "Resolve each targeted feed's RIC via generate_ric_mapping and "
            "overwrite its datascope_ric identifiers (day=TICKER.<exch>, "
            "overnight=TICKER.BLUE). Target with --feed-id/--feed-ids-from."
        ),
    )
```

And add two general flags (place them near `--from-csv`, before the targeting block):

```python
    p.add_argument(
        "--symbols",
        type=str,
        help="Reference file for --set-ric RIC resolution (default: --config).",
    )
    p.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the NASDAQ-Trader cache during --set-ric resolution.",
    )
```

Add the summary helper near `_set_ric_mapping_summary_lines` (after it, top-level):

```python
def _set_ric_summary_lines(
    op: SetRicFromResolver,
    changes: list[Change],
    warnings: list[Warning],
) -> list[str]:
    """Return extra summary lines for a SetRicFromResolver operation."""
    overwritten = sum(
        1 for c in changes if c.location == "datascope_ric_identifier"
    )
    unresolved = sorted(fid for fid, r in op.rics.items() if not r.day_ric)
    low_conf = sorted(
        f"{fid}={r.day_ric}({r.confidence})"
        for fid, r in op.rics.items()
        if r.day_ric and r.confidence and r.confidence != "high"
    )
    unresolved_detail = (
        f"  ({', '.join(str(f) for f in unresolved)})" if unresolved else ""
    )
    low_conf_detail = f"  ({', '.join(low_conf)})" if low_conf else ""
    return [
        "",
        "RIC resolution summary:",
        f"  identifiers overwritten: {overwritten}",
        f"  feeds unresolved:        {len(unresolved)}{unresolved_detail}",
        f"  low-confidence RICs:     {len(low_conf)}{low_conf_detail}",
    ]
```

In `main()`, extend the per-op supplementary summary loop (currently lines ~210-215):

```python
    # Per-op supplementary summaries.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/edit-config && python3 -m pytest tests/test_edit_config_cli.py -k set_ric -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat(edit-config): add --set-ric CLI flag + resolution summary"
```

---

## Task 5: Full suite + real dry-run verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole edit-config test suite**

Run: `cd tools/edit-config && python3 -m pytest tests/ -v`
Expected: PASS (all pre-existing tests plus the 14 new ones; 0 failures).

- [ ] **Step 2: Run pre-commit on every changed file**

Run:

```bash
pre-commit run --files \
  tools/edit-config/edit_config.py \
  tools/edit-config/edit_config_lib/config_ops.py \
  tools/edit-config/edit_config_lib/config_editor.py \
  tools/edit-config/tests/test_config_ops.py \
  tools/edit-config/tests/test_config_editor.py \
  tools/edit-config/tests/test_edit_config_cli.py
```

Expected: all hooks Pass.

- [ ] **Step 3: Real dry-run against after.json (network — resolves real RICs)**

Run (from repo root, with venv active):

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --set-ric --feed-ids-from feed_ids.txt
```

Expected: a dry-run plan + diff showing bare day-session RICs gaining suffixes (e.g. `"BITS" -> "BITS.O"`), `.N` feeds rewritten (e.g. `CTRA.N -> CTRA.K`), the empty IWDA slot filled, and a "RIC resolution summary" footer. The already-correct SSK/BLSH feeds should show no changes. Nothing is written (dry-run). Confirm `git status` shows `after.json` unchanged.

- [ ] **Step 4: Commit nothing (verification step)**

No commit — this task only confirms behavior. If the dry-run reveals a bug, return to the relevant task.

---

## Task 6: Documentation

**Files:**

- Modify: `docs/edit_config.md`
- Modify: `CLAUDE.md` (the `edit_config.py` row note in the Scripts table / Key Gotchas as appropriate)

- [ ] **Step 1: Document `--set-ric` in `docs/edit_config.md`**

Add a section (match the existing doc's heading style — read the file first to mirror its format) covering:

```markdown
### `--set-ric` — resolve & overwrite Datascope RICs

Resolves each targeted feed id through `generate_ric_mapping`'s `RICResolver`
and overwrites its `datascope_ric` identifier slots to match the feed 922
pattern: REGULAR/PRE_MARKET/POST_MARKET get the resolved day RIC
(`TICKER.<exch>`, e.g. `AAPL.O` / `CTRA.K` / bare `XLF`), and OVER_NIGHT gets
`TICKER.BLUE`.

    python3 tools/edit-config/edit_config.py --config after.json \
        --set-ric --feed-ids-from feed_ids.txt        # dry-run
    python3 tools/edit-config/edit_config.py --config after.json \
        --set-ric --feed-ids-from feed_ids.txt --apply # write

- Requires `--feed-id` or `--feed-ids-from` targeting (resolution is by feed id).
- Overwrites any slot whose value differs from the resolved RIC; slots already
  correct are NOOPs. Overwriting a non-empty value prints a churn warning.
- Only _replaces_ existing session slots — it will not add missing PRE/POST/
  OVERNIGHT sessions to a feed.
- `--symbols PATH` overrides the resolver reference file (default: `--config`).
  `--force-refresh` bypasses the NASDAQ-Trader cache.
- Low-confidence / defaulted RICs are written but listed in the "RIC resolution
  summary" so you can review them in the dry-run before `--apply`.

Distinct from `--set-ric-mapping`, which is HK-only, matches by symbol prefix,
writes one RIC to every slot, and only fills empty slots.
```

- [ ] **Step 2: Note the operation in `CLAUDE.md`**

In the Scripts table row for `tools/edit-config/edit_config.py`, extend the Purpose cell to mention `--set-ric` (e.g. append ", set RIC identifiers"). Keep the edit minimal and within the existing table formatting.

- [ ] **Step 3: Run pre-commit on the docs**

Run: `pre-commit run --files docs/edit_config.md CLAUDE.md`
Expected: all hooks Pass (prettier may reformat tables — re-stage if it does).

- [ ] **Step 4: Commit**

```bash
git add docs/edit_config.md CLAUDE.md
git commit -m "docs(edit-config): document --set-ric operation"
```

---

## Self-Review notes

- **Spec coverage:** CLI surface (Task 4) ✓; inline resolution via `RICResolver` (Task 2) ✓; `SetRicFromResolver` overwrite-if-differs + per-session day/overnight + NOOP + churn/unresolved/no-slot warnings (Task 1) ✓; summary with overwritten/unresolved/low-confidence (Task 4) ✓; tests pure + network-free CLI (Tasks 1-4) ✓; docs (Task 6) ✓; non-goals (no session insertion, no engine change) respected by design.
- **Type consistency:** `ResolvedRic(day_ric, overnight_ric, confidence, warnings)` and `SetRicFromResolver(rics=dict[int, ResolvedRic])` are used identically across config_ops, config_editor, edit_config, and all tests. `resolve_rics_for_feed_ids(feed_ids, symbols_path, force_refresh=False, resolver=None)` signature matches every call site and test.
- **No placeholders:** every code/test/command step is concrete.
