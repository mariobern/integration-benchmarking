# Session-Only Publisher Editing — Design

**Date:** 2026-06-05
**Scope:** `lazer_dq/apply_allowed_to_config.py`, `tools/edit-config/` (only these two tools)
**Status:** Approved

## Background

The Lazer config format changed. In the old format (`lazer_state.json`,
`after.json` era), each feed carried a feed-level (top-level)
`allowedPublisherIds` roster plus optional per-session lists inside
`marketSchedules` entries. In the new format (`lazer_update.json` era and all
future exports):

- The feed-level `allowedPublisherIds` key is **gone** (0 of 3,378 feeds).
- Every feed has **at least one** `marketSchedules` entry; single-session
  asset classes (crypto, fx, metals, …) carry one `REGULAR` entry that now
  holds the `allowedPublisherIds`. Every feed has a `REGULAR` session.
- Publisher membership is **exclusively per-session**. 1,640 session entries
  (mostly on COMING_SOON feeds) have no `allowedPublisherIds` key at all.
- Feed-level `minPublishers` **still exists** on every feed; session-level
  `minPublishers` appears only on some equity sessions.

Both tools assume the old format: `apply_allowed_to_config.py` writes the
top-level roster on every promotion (and _only_ the top level for
hk-equities), and `edit_config.py`'s publisher/minPublishers ops default to
top-level targets.

## Decisions

1. **New format only.** All top-level `allowedPublisherIds` handling is
   removed. Old-format files (e.g. `after.json`) are no longer valid targets.
2. **Format guard.** Both tools refuse to run (clear error) if any feed in
   the config has a feed-level `allowedPublisherIds` key, preventing
   accidental half-edits of legacy files.
3. **Default scope = REGULAR.** `--add-publisher`, `--remove-publisher`,
   `--set-min-publishers`, and `--bump-min-publishers` without `--session`
   target only the REGULAR session entry (always present in the new format).
   This includes remove: pulling a publisher from all sessions requires
   `--session ALL`.
4. **Insert missing keys.** Ops targeting a session entry that lacks the
   field (`allowedPublisherIds` or `minPublishers`) insert it rather than
   warn/error.
5. **hk-equities unifies into the session path.** The DQ-vetted list is
   written into the feed's REGULAR session entry. The hk/us split
   (`--asset-class`, `write_session_fields`) is deleted; the allowed sheet's
   session rows drive everything (hk workbooks already emit `REGULAR` rows).
6. **minPublishers writes are session-only too.** Neither tool writes the
   feed-level `minPublishers` anymore (apply_allowed previously set it to 2
   on promotion). It may still be _read_ (see headroom warning below).
7. **Out of scope:** `update_config_from_summary.py`,
   `update_min_publishers.py`, `config_linter.py`, `update_lazer_symbols.py`
   and any other config-touching tool. They are updated later if/when run
   against new-format files.

## Design

### 1. Shared format guard

Immediately after loading the config, if **any** feed has a feed-level
`allowedPublisherIds` key, abort:

```
ERROR: config contains feed-level allowedPublisherIds (old format).
This tool now supports only the session-level format (lazer_update.json era).
```

- `apply_allowed_to_config.py`: `apply_summary_to_config()` raises
  `ValueError` (so library callers and tests get it); `main()` catches and
  exits 1 with the message.
- `edit_config.py`: checked in `main()` right after `json.loads`, before
  building the plan; prints the error and returns 1.

No shared module — ~10 lines each, duplicated deliberately (the two tools do
not import from each other today).

### 2. `apply_allowed_to_config.py` — one unified session-level path

**Deleted:**

- `set_top_level_allowed()`, `set_top_level_min_publishers()`
- `SESSION_LEVEL_ASSET_CLASSES`, `KNOWN_ASSET_CLASSES`
- the `--asset-class` CLI flag
- the `write_session_fields` parameter of `apply_summary_to_config()`

**Unchanged:**

- Sheet parsing (`parse_allowed_sheet`), including the `(aggregate)` row,
  which remains the no-data skip signal.
- Publisher filtering (`EXCLUDED_PUBLISHERS`).
- The promotion redundancy gate: union of per-session survivors must be
  ≥ `--min-publishers` or the feed stays COMING_SOON.
- `overwrite_session` / `add_session` / `remove_session` text-surgery
  mechanics, and per-session `minPublishers` defaults via
  `get_min_publishers()`.

**Changed flows:**

- **COMING_SOON promotion:** state → STABLE plus per-session
  overwrite/add/remove, exactly as today, minus the two top-level writes
  (roster union and `minPublishers: 2`). The feed's existing top-level
  `minPublishers` is left untouched.
- **STABLE additive:** adds missing sessions only; the "union new publishers
  into the top-level roster" step is deleted. `skipped_stable_no_change`
  now simply means "no sessions added".
- All asset classes flow through the same per-session loop; for hk-equities
  the sheet contains only REGULAR rows, so only REGULAR is written.

### 3. `edit_config.py` — ops lose the top level

**Scope semantics** (applies to AddPublisher, RemovePublisher,
SetMinPublishers, BumpMinPublishers):

| `--session` value                                       | Meaning                                                   |
| ------------------------------------------------------- | --------------------------------------------------------- |
| _(omitted)_                                             | REGULAR session entry only                                |
| `REGULAR` / `PRE_MARKET` / `POST_MARKET` / `OVER_NIGHT` | that session entry; `OpError` if the feed doesn't have it |
| `ALL`                                                   | every session entry present on the feed                   |
| `NONE`                                                  | **removed** from CLI choices and the YAML spec schema     |

**Per-op behavior:**

- `AddPublisher`: session lists only. If the targeted session entry lacks
  `allowedPublisherIds`, the op inserts it; the Change record carries
  `before=None` meaning "field absent — insert".
- `RemovePublisher`: session lists only; default REGULAR (narrower than the
  old "everywhere" default — use `--session ALL` for that). Missing key =
  NOOP. The old `session=NONE` drift warning is deleted. The "no headroom"
  warning compares against the session's `minPublishers` when present, else
  falls back to the feed-level `minPublishers` (read-only).
- `SetMinPublishers` / `BumpMinPublishers`: session entries only. A missing
  session `minPublishers` key is inserted (placed on its own line just
  before the `"session"` key, matching canonical field order). Validation
  counts the session's `allowedPublisherIds` length; an absent key counts
  as 0 publishers, so setting a positive value there is an unsatisfiable
  error.
- `SetState`, `--set-ric-mapping`, `--set-ric`: untouched. `state` is still
  a feed-level field; the `top_level` Change location survives only for it.

**Text surgery** (`config_text_surgery.py` + `config_editor.py` applier):

- `_apply_changes_to_feed_block`'s session branch learns to insert when
  `change.before is None`: two small helpers mirroring apply_allowed's
  `_insert_field_after_open_brace` (for `allowedPublisherIds`) and
  `_insert_field_before_session` (for `minPublishers`), duplicated rather
  than cross-imported between the two tool packages.
- The `top_level` branch keeps only the `state` field path; the
  marketSchedules-tail scoping for top-level `minPublishers` is deleted.
- `config_diff.py` renders inserts as `(absent) → [ … ]`.

### 4. Testing

- Migrate fixtures in `lazer_dq/tests/test_apply_allowed_to_config.py` and
  `tools/edit-config/tests/` to the new format (drop feed-level
  `allowedPublisherIds`); rewrite assertions that expect top-level writes.
- New cases: format-guard rejection (both tools); insert-missing-key for
  publishers and minPublishers; REGULAR default scope; ALL scope;
  hk-equities flowing through the session path; remove-publisher NOOP on a
  session without the key.
- Sanity runs against real data: `apply_allowed_to_config --dry-run` on a
  copy of `lazer_update.json` with a real dq_summary workbook;
  `edit_config --add-publisher … --dry-run` likewise; `json.loads`
  round-trip on applied output.

### 5. Documentation

- `docs/apply_allowed_to_config.md`: remove `--asset-class`, describe the
  unified session path and the format guard.
- `docs/edit_config.md`: new scope table, removed `NONE`, insert behavior,
  format guard.
- `CLAUDE.md`: update the `apply_allowed_to_config` gotcha bullet and the
  edit-config row in the Scripts table where they mention top-level
  behavior.
- `CHANGELOG.md` entry.
