# Design: `--remove-ric` — clear RIC mappings in edit_config.py

**Date:** 2026-06-15
**Status:** Approved (pending implementation)
**Tool:** `tools/edit-config/edit_config.py`

## Problem

`edit_config.py` can *populate* `datascope_ric` identifiers (`--set-ric-mapping`
fills empty slots from a CSV; `--set-ric` resolves and overwrites by feed ID) but
has no way to *unset* one. When a feed is onboarded with a wrong RIC, or an asset
is delisted, there's no supported operation to remove its RIC mapping — it must be
hand-edited.

## Goal

Add an operation that clears `datascope_ric` identifier values back to the empty
string (`""`), keeping the surrounding structure intact, with dry-run-by-default
safety and visible blast radius.

## Decisions (from brainstorming)

| Decision           | Choice                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------- |
| Removal level      | **Clear value to `""`** — keep the `datascope_ric` / `identifiers[]` scaffold intact     |
| Slot selection     | **All identifier slots** on each targeted feed; no `--session` scoping for this op       |
| Flag name          | **`--remove-ric`** (YAML op: `remove_ric`)                                               |
| Targeting          | **Full `FilterSet`** — `--feed-id`, `--feed-ids-from`, `--symbol-pattern`, `--asset-class`, `--state` |
| Safety             | Warn per non-empty value cleared; extra warning on STABLE feeds; warn if feed has no slots |

### Why clear-to-empty (not delete the slot or block)

The text-surgery applier already supports writing a value into a
`datascope_ric_identifier` span — `_apply_one_change` replaces the span with
`f'"{change.after}"'` (`config_editor.py:485-495`). A `Change` with `after=""`
writes `""` with **zero new surgery code**. Deleting the slot dict or the whole
`datascope_ric` block would require new array/block-deletion surgery (with
trailing-comma handling) for no functional gain — a downstream consumer treats an
empty-string identifier as "no RIC" the same way it would a missing slot.

### Why full FilterSet (despite the destructive nature)

Clearing is destructive, and a broad `--symbol-pattern`/`--asset-class` can match
many feeds. That blast radius is accepted because the existing guardrails surface
it before any write: **dry-run is the default**, the plan prints the **matched
feed count**, the diff shows **every** cleared value, and the new per-value +
STABLE warnings fire in the dry-run. Restricting to feed-id only would buy
marginal safety at the cost of consistency with the publisher/min-publisher ops
and the bulk-cleanup use case (e.g. "wipe RICs for a delisted asset class").
`--set-ric` is feed-id-only for a *structural* reason (it must resolve each feed
by ID), not as a safety precedent.

## Design

### New op — `ClearRic` (`edit_config_lib/config_ops.py`)

A small `@dataclass` (mutable, like the other ops) mirroring the existing op
pattern (`apply(self, feed) -> (list[Change], list[Warning])`). No fields — its
behavior is fully determined by the targeted feed.

```python
@dataclass
class ClearRic:
    """Clear every datascope_ric identifier slot on a feed back to "".

    Per-slot semantics:
      - identifier == ""  -> NOOP (no Change).
      - identifier != ""  -> Change(after="") + Warning (value being wiped).

    Per-feed semantics:
      - no datascope_ric identifier slots -> Warning ("nothing to clear").
      - state == STABLE with >=1 non-empty slot -> extra Warning (live benchmark).
    """
```

Behavior:

1. Collect identifier slots in document order — walk
   `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[]`, keeping only
   `dict` entries that contain an `"identifier"` key. This is the **same walk
   order** used by `SetRicFromResolver` and `find_ric_identifier_spans`, so
   `Change.index` lines up with the applier's spans.
2. If no slots → return `[], [Warning(... "no datascope_ric identifier slots — nothing to clear")]`.
3. For each slot at index `i`:
   - `current == ""` → skip (NOOP).
   - `current != ""` →
     `Change(feed_id, symbol, location="datascope_ric_identifier", field="identifier", before=current, after="", index=i)`
     plus `Warning(... "clearing identifier slot {i} ({current!r} -> \"\")")`.
4. After the loop, if any slot was non-empty **and** `feed["state"] == "STABLE"`,
   append one extra `Warning(... "clearing RIC on STABLE feed — breaks live benchmark")`.

### Applier — no change

`_apply_one_change` for `location == "datascope_ric_identifier"` already does
`block[:start] + f'"{change.after}"' + block[end:]`. With `after=""` it writes
`""`. No edits to `config_text_surgery.py` or `config_editor.py`'s apply path.

### CLI wiring (`edit_config.py`)

- Add to the mutually-exclusive op group:
  ```python
  op_group.add_argument(
      "--remove-ric",
      action="store_true",
      help="Clear all datascope_ric identifier values to \"\" on targeted feeds.",
  )
  ```
- A `_remove_ric_summary_lines(op, changes, warnings)` footer printed from `main`'s
  per-op summary loop (alongside the existing `_set_ric_mapping_summary_lines` /
  `_set_ric_summary_lines`):
  ```
  RIC removal summary:
    identifiers cleared:    N
    feeds with no slots:    M
    STABLE feeds affected:  K
  ```
  Counts derived from `changes` (cleared = count of `datascope_ric_identifier`
  changes) and `warnings` (no-slots / STABLE messages).

### Op-flag registration (`edit_config_lib/config_editor.py`)

- Add `"remove_ric"` to `_OP_FLAGS` and to `_BOOL_OP_FLAGS` (store_true).
- In `build_op_from_args`, handle `name == "remove_ric"`:
  build the standard `FilterSet` via `_build_filters_from_args(args)` (enforces the
  ≥1-filter requirement) and return `[PlannedOp(op=ClearRic(), filters=filters)]`.
- Import `ClearRic` in `config_editor.py`.

### Plan summary (`edit_config.py`)

`ClearRic` uses a normal `FilterSet`, so the existing
`matched = result.matched_counts[i-1]` branch already prints
`ClearRic → N feed(s) matched`. No special-casing like `SetRicMapping` needs.

### YAML spec support (`config_editor.py`)

- `_OP_REQUIRED_FIELDS["remove_ric"] = set()` (no required fields beyond targeting).
- In `_build_op_from_yaml_entry`, `if op_name == "remove_ric": return ClearRic()`.
- Targeting comes from `_filters_from_yaml_entry` (the default branch), so a
  `remove_ric` entry requires at least one targeting key like the other ops.

```yaml
version: 1
operations:
  - op: remove_ric
    feed_id: "922,1000-1005"
```

### INACTIVE feeds

Handled by existing logic in `simulate_plan`: non-`SetState` ops skip
`state == "INACTIVE"` feeds and increment `skipped_inactive`. `ClearRic` inherits
this for free — no special handling.

### Docs (`docs/edit_config.md`)

- Add a row to the operations table:
  `| --remove-ric | Clear all datascope_ric identifier values to "" |`
- Add a `### --remove-ric — clear datascope_ric identifiers` section describing
  per-slot semantics, the three warnings, full-FilterSet targeting, dry-run
  default, and that it is the inverse of `--set-ric-mapping`. Add a `remove_ric`
  entry to the YAML spec example.
- Update the top-level `CLAUDE.md` Scripts-table description for edit_config.py if
  it enumerates ops (it lists "set RIC identifiers" — add "clear RIC identifiers").

## Testing (`tools/edit-config/tests/`)

Op-level (`test_config_ops.py`):
- Clears a feed with populated slots → one Change per non-empty slot, `after=""`,
  one warning per cleared value.
- Already-empty slot → NOOP (no Change, no warning).
- Mixed populated/empty slots → only populated ones produce Changes.
- STABLE feed with a non-empty slot → extra STABLE warning present.
- Feed with no `datascope_ric` slots → single "nothing to clear" warning, no Changes.

Editor-level (`test_config_editor.py`):
- `build_op_from_args` with `--remove-ric` + `--feed-id` → `ClearRic` op, correct FilterSet.
- `--remove-ric` with no targeting filter → `ValueError`.
- `--symbol-pattern` targeting matches multiple feeds.
- YAML `remove_ric` op parses; missing targeting raises.
- INACTIVE feed is skipped (counted in `skipped_inactive`).

Apply round-trip (`test_config_editor.py` or `test_config_text_surgery.py`):
- End-to-end `apply_changes` on raw fixture text → the identifier renders as `""`
  in the output and the JSON re-parses; surrounding formatting unchanged.

CLI (`test_edit_config_cli.py`):
- Dry-run prints the RIC removal summary footer and exits without writing.
- `--apply` writes and the on-disk identifier is `""`.

## Out of scope

- Deleting identifier slots or the `datascope_ric`/`benchmarkMapping` block
  (structural removal) — explicitly deferred; clear-to-empty is sufficient.
- `--session` scoping for `--remove-ric` — always all slots.
- Value-matched clearing (`--remove-ric AAPL.O`) — not needed for current cases.

## Files touched

- `tools/edit-config/edit_config_lib/config_ops.py` — add `ClearRic`.
- `tools/edit-config/edit_config_lib/config_editor.py` — register op, CLI build, YAML.
- `tools/edit-config/edit_config.py` — `--remove-ric` flag + summary footer.
- `docs/edit_config.md` — operations table + section + YAML example.
- `CLAUDE.md` — Scripts-table description tweak.
- `tools/edit-config/tests/` — op, editor, apply, CLI tests.
