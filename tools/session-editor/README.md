# session-editor

Add or remove market sessions on US-equity feeds in `after.json`. Dry-run by
default; YAML batch specs supported. Companion to `tools/edit-config`, which
handles per-session publisher / `minPublishers` / `state` edits but does not
add or remove session entries themselves.

## Why this exists

US-equity feeds carry up to four trading sessions in `marketSchedules[]`:
`REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`. When a feed's `state`
becomes `STABLE`, consumers tend to assume every listed session is supported.
`minPublishers` is the actual gate, but it's easy to miss. This tool gives
operators a surgical way to:

- **Remove** sessions that aren't ready, so they aren't listed at all.
- **Add** sessions back with `minPublishers: 100` (an intentionally
  unsatisfiable sentinel) once the schedule template is in place but
  publishers haven't been assigned yet. Lower `minPublishers` via
  `edit-config` after the publisher cohort is wired up.

The 1019 COMING_SOON feeds added in PR #26 are the primary target — many of
them have all four sessions templated but only REGULAR is actually ready.

## Quick start

```bash
# Dry-run preview (default)
python3 tools/session-editor/session_editor.py --config after.json \
    --remove-session OVER_NIGHT --feed-id 2500-2700

# Apply
python3 tools/session-editor/session_editor.py --config after.json \
    --add-session OVER_NIGHT --feed-id 1000-1050 --min-publishers 100 --apply

# Multi-session remove
python3 tools/session-editor/session_editor.py --config after.json \
    --remove-session PRE_MARKET,POST_MARKET,OVER_NIGHT --state STABLE \
    --feed-id 3100-3200

# YAML batch spec
python3 tools/session-editor/session_editor.py --config after.json \
    --from-spec my_session_edits.yaml --apply

# Sanity check that the canonical templates still match AAPL/922
python3 tools/session-editor/session_editor.py --config after.json \
    --verify-templates
```

## Behavior summary

- Eligible feeds: `symbol` starts with `Equity.US.` and `metadata.asset_type
== "equity"`. Anything else is skipped unless `--force` is passed.
- Added sessions use canonical schedule strings extracted from feedId 922
  (AAPL), match PR #26's expansion logic, and default to `minPublishers:
100`. `allowedPublisherIds` starts empty.
- `benchmarkMapping` is copied from the feed's REGULAR session. For
  `OVER_NIGHT`, RIC identifiers ending in `.O / .N / .A / .K` are rewritten
  to `.BLUE` (e.g., `ABNB.O` → `ABNB.BLUE`).
- `REGULAR` cannot be added (only the rest can; a feed without REGULAR can't
  be added to). `REGULAR` cannot be removed without `--force`.

## Layout

| Path                                | Purpose                                      |
| ----------------------------------- | -------------------------------------------- |
| `session_editor.py`                 | CLI entry point                              |
| `session_editor_lib/templates.py`   | Canonical schedule strings + `.BLUE` rewrite |
| `session_editor_lib/feed_filter.py` | Eligibility + session lookup                 |
| `session_editor_lib/ops.py`         | `AddSession` / `RemoveSession`               |
| `session_editor_lib/selector.py`    | Feed-ID selector grammar                     |
| `session_editor_lib/editor.py`      | Plan → simulate orchestrator                 |
| `session_editor_lib/diff.py`        | Unified diff with `feedId/symbol` headers    |
| `session_editor_lib/spec.py`        | YAML batch-spec parser                       |
| `tests/`                            | pytest suite (69 tests)                      |
| `tests/fixtures/sample_after.json`  | 5-feed slice covering all edge cases         |

## Docs

- Full reference: [`docs/session_editor.md`](../../docs/session_editor.md)
- Design spec: [`docs/superpowers/specs/2026-05-18-session-editor-design.md`](../../docs/superpowers/specs/2026-05-18-session-editor-design.md)

## Independence

Self-contained. Does not import from the repo's `lib/`, `tools/edit-config/`,
`tools/backfill-apids/`, or any other tool. Selector grammar and diff format
intentionally mirror `tools/edit-config` for operator ergonomics but the code
is independent.

## Tests

```bash
PYTHONPATH=tools/session-editor python3 -m pytest tools/session-editor/tests/ -v
```
