# edit_config.py: exchangeId add/remove with schedule inheritance

**Date:** 2026-06-09
**Status:** Approved design — ready for implementation plan
**Tool:** `tools/edit-config/edit_config.py` (+ `edit_config_lib/`)

## Problem

Feeds in the session-only config (`lazer_update.json` era) may carry a top-level
`exchangeId` that points into the config's top-level `exchanges[]` array. An
exchange entry defines the trading calendar (`marketSchedule` string per session).
When a feed has an `exchangeId`, it **inherits** that calendar: its session
entries (`marketSchedules[]`) carry no `marketSchedule` string of their own —
only `allowedPublisherIds`, `benchmarkMapping`, `minPublishers`, `session`.

`edit_config.py` has no way to add or remove an `exchangeId`. Operators do this
by hand, which is error-prone:

- Adding an `exchangeId` without stripping the now-redundant per-session
  `marketSchedule` strings leaves stale, conflicting data (2 feeds — 3167
  `Equity.US.NTRA/USD` and 3295 `Equity.US.ALGEF/USD` — are in this state today:
  they have both an `exchangeId` and inline schedule strings).
- Removing an `exchangeId` without restoring per-session schedule strings leaves
  the feed with no trading calendar at all.

## Goal

Add two surgical operations to `edit_config.py` that manage the `exchangeId`
field **and** the per-session `marketSchedule` strings together, so the feed is
always left in a valid, consistent state ("full inheritance").

## Data model (as observed in `lazer_new.json`)

- Top-level `exchanges[]`: each entry has `exchangeId` (int), `name`,
  `assetClass` (e.g. `EXCHANGE_ASSET_CLASS_EQUITY`), and `sessions[]` where each
  session has `session` (REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT) and a
  `marketSchedule` string. The array is **sparse** — ids 1–10 and 21 exist;
  11–20 are gaps the team will fill later, each with its own `marketSchedule`.
- A feed optionally carries a top-level `exchangeId: N`.
- Feed **with** `exchangeId` (620 feeds): session entries carry **no**
  `marketSchedule` string (inherited).
- Feed **without** `exchangeId` (2762 feeds): each session entry carries its own
  `marketSchedule` string.

Example — feed 922 `Equity.US.AAPL/USD`: `exchangeId: 1` (NASDAQ Global Select
Consolidated), 4 session entries, no schedule strings.

## CLI surface

Two new flags in the existing mutually-exclusive operation group. All existing
targeting (`--feed-id`, `--feed-ids-from`, `--symbol-pattern`, `--asset-class`,
`--state`) and execution (`--dry-run` default / `--apply`, `--no-backup`,
`--show-full-diff`) apply unchanged.

| Flag                   | Effect                                                                                                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--add-exchange-id N`  | Assign exchange `N` to each targeted feed and **strip** every session's `marketSchedule` string (now inherited). Reassigns + warns if a different id is already present.                          |
| `--remove-exchange-id` | Remove each targeted feed's `exchangeId` and **restore** every session's `marketSchedule` string by copying from that exchange's definition. Takes no value — operates on whatever id is present. |

`--remove-exchange-id` is a `store_true` flag (no value).

## Architecture

Fits the existing three-layer split; no change to the `op.apply(feed)` interface
or the `simulate_plan` signature.

### `config_ops.py` — two new op dataclasses

Both ops need the `exchanges[]` data, which lives at config top-level, not in
the feed dict. They capture it **at construction time**, exactly as
`SetRicMapping` captures `prefix_to_ric` and `SetRicFromResolver` captures
`rics`. So `apply(feed)` still receives only the feed and global context never
leaks into the per-feed loop.

A resolved exchange is represented as:

```
ExchangeInfo:
    exchange_id: int
    name: str
    asset_class: str                  # e.g. "EXCHANGE_ASSET_CLASS_EQUITY"
    sessions: dict[str, str]          # SESSION_NAME -> marketSchedule string
```

`AddExchangeId`:

- Fields: `exchange_id: int`, `exchange: ExchangeInfo` (pre-resolved at build
  time — the id is fixed for the invocation).
- `apply(feed)`:
  1. **Session coverage** — every session in `feed["marketSchedules"]` must be a
     key in `exchange.sessions`; otherwise `OpError` (can't strip a string with
     nothing to inherit).
  2. **Asset-class** — if `exchange.asset_class` doesn't map to the feed's
     `metadata.asset_type`, emit a `Warning` (does not block).
  3. **Reassignment** — if `feed.get("exchangeId")` is set and differs from
     `exchange_id`, emit a `Warning` (`reassigning exchangeId 1 -> 2`).
  4. Emit a `Change` for the `exchangeId` field: insert (`before=None`) when
     absent, else replace (`before=current, after=exchange_id`). NOOP when equal.
  5. Emit one `Change` per session that still carries a `marketSchedule` string:
     `location=SESSION_NAME, field="marketSchedule", before=<string>,
after=None` (delete). Sessions already stripped produce no change.
  6. If id is already correct **and** no strings remain → 0 changes (clean NOOP).

`RemoveExchangeId`:

- Fields: `exchanges_by_id: dict[int, ExchangeInfo]` (the whole map — different
  feeds in a batch may reference different exchanges).
- `apply(feed)`:
  1. `current = feed.get("exchangeId")`. If `None` → `Warning` (`feed X has no
exchangeId`), 0 changes.
  2. Look up `exchange = exchanges_by_id.get(current)`. If absent → `OpError`
     (can't restore schedules from an unknown exchange).
  3. **Session coverage** — every feed session must be in `exchange.sessions`;
     otherwise `OpError` (nothing to restore for that session).
  4. Emit a `Change` to delete the `exchangeId` field (`location="top_level",
field="exchangeId", before=current, after=None`).
  5. For each feed session lacking a `marketSchedule` string, emit a `Change` to
     insert it (`location=SESSION_NAME, field="marketSchedule", before=None,
after=<string from exchange.sessions[session]>`). A session that already has
     a string (anomaly) is left untouched (NOOP).

**Change convention:** `after = None` (with `before != None`) means _delete the
field_. This mirrors the existing `before = None` (with `after != None`) = _insert
the field_. Both non-None = replace.

### `config_text_surgery.py` — new primitives

- `delete_scalar_field(block, key)` — remove the whole physical line for a
  top-level int or quoted-string field, including its trailing comma. Used for
  the `exchangeId` int (in the feed block) and the session `marketSchedule`
  string (in a session block). Both targets always have a field after them
  (feed has more fields after `exchangeId`; a session always has `"session"`
  after `marketSchedule`), so they always carry a trailing comma — the
  last-field/dangling-comma case does not arise and is out of scope.
- Insert paths reuse existing helpers:
  - `exchangeId` insert → `insert_field_after_open_brace` (first field, matching
    feed 922's layout).
  - restored `marketSchedule` string → `insert_field_before_session` (canonical
    position, just before `"session"`).
- `exchangeId` update reuses `find_int_field_span(block, "exchangeId")` (exactly
  one `exchangeId` per feed block — safe). The restored schedule string value is
  JSON-escaped via `json.dumps` when building the inserted field text.

### `edit_config.py` / `config_editor.py` — wiring

- In `main()`, build `exchanges_by_id` once from `data["exchanges"]`.
- Add the two flags to `_build_parser` (in the op group) and the op names to
  `_OP_FLAGS`.
- `build_op_from_args` gains access to `exchanges_by_id` (threaded as a
  parameter) to construct the ops; for `--add-exchange-id` it validates the id
  exists in the map and raises `ValueError` (→ printed by `main()`) when it
  doesn't.
- YAML spec (`--from-spec`) gains `add_exchange_id` (required field:
  `exchange_id`) and `remove_exchange_id` (no required fields) in
  `_OP_REQUIRED_FIELDS` / `_build_op_from_yaml_entry`; `parse_yaml_spec` is
  threaded `exchanges_by_id` the same way.

### Apply ordering

The existing per-feed apply loop (`_apply_changes_to_feed_block`) re-locates each
change's span in the current block text before splicing, so whole-line
inserts/deletes that shift later offsets are already handled. The new field
delete/insert changes ride on that mechanism with no special ordering.

### INACTIVE feeds

Unchanged behavior: `simulate_plan` silently skips `state == INACTIVE` feeds for
every op except `SetState`. The two new ops are not `SetState`, so editing an
INACTIVE feed requires reactivating it first (`--set-state`). This is consistent
with the publisher/minPublishers ops and is documented, not special-cased.

## Validation summary

**Hard errors (block apply):**

- `--add-exchange-id N` where `N` not in `exchanges[]` (raised at build time).
- Feed has a session the exchange doesn't define (add: nothing to inherit;
  remove: nothing to restore).
- `--remove-exchange-id` where the feed's current id isn't in `exchanges[]`.

**Warnings (allow apply):**

- Asset-class mismatch (exchange `assetClass` vs feed `metadata.asset_type`).
- Reassignment (`exchangeId` already set to a different value).
- `--remove-exchange-id` on a feed with no `exchangeId` (NOOP).

**NOOP (0 changes):**

- Add with the same id and all strings already stripped.
- Per session: already-stripped (add) or already-present (remove) schedule
  string.

## Testing

- **Text-surgery unit tests** (`config_text_surgery`): insert / update / delete
  a top-level `exchangeId`; delete / insert a session `marketSchedule` string.
  Assert formatting is preserved and output re-parses as JSON.
- **Op unit tests** (`config_ops`): insert; reassign-warn; strip-strings;
  session-coverage error (add and remove); asset-class warn; same-id NOOP;
  anomaly cleanup (exchangeId + stale strings → strings removed); remove restores
  strings; remove unknown-id error; remove-without-id warn.
- **Integration** via `main()` on a small fixture config containing an
  `exchanges[]` array: dry-run then `--apply`, re-parse the result; verify a
  922-style feed round-trips (add strips strings, leaves a valid inherited feed);
  verify **add-then-remove** returns the per-session schedule strings.

## Docs

- `docs/edit_config.md`: add the two ops to the operations table and a short
  "Exchange inheritance" section describing the add/remove semantics and the
  validation rules.
- `CLAUDE.md`: extend the `edit_config.py` Scripts-table example line; update the
  "New config format (session-only publishers)" gotcha note to mention exchange
  inheritance.

## Out of scope

- Adding, editing, or removing entries in the top-level `exchanges[]` array
  itself (the team adds missing exchanges separately).
- Reconciling a feed's **set** of session entries to match the exchange's
  sessions (the feed's session set — which sessions carry publisher lists — is
  independent of inheritance; this feature only governs the `marketSchedule`
  string within sessions the feed already has).
- The last-field/dangling-comma deletion case (neither target is ever the last
  field in its object).
