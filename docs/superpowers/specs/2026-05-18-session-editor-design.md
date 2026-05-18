# Session Editor — Design Spec

**Date:** 2026-05-18
**Status:** Draft (in-progress)
**Author:** mario@pyth.network

## Problem

US-equity feeds in `after.json` carry up to four trading sessions in
`marketSchedules[]`: `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`.
A feed's `state: STABLE` does not imply that every listed session is actually
production-ready — `minPublishers` per session communicates that gap, but
consumers routinely assume that anything shown is supported.

The recent backfill (PR #26) expanded 218 of the 1019 new COMING_SOON feeds
into the 4-session shape using AAPL/feedId 922 as the schedule template. As
those feeds transition to STABLE, operators need a systematic way to:

1. **Remove** sessions that are not yet ready (so they're not displayed at all).
2. **Add** sessions back once a publisher cohort and benchmark are in place.

Current state of the world (US-equity feeds, sampled from `after.json`):

| state       | sessions                          | count |
| ----------- | --------------------------------- | ----- |
| COMING_SOON | REGULAR + PRE + POST + OVER_NIGHT | 296   |
| COMING_SOON | REGULAR only                      | 177   |
| STABLE      | REGULAR + PRE + POST + OVER_NIGHT | 143   |
| STABLE      | REGULAR + PRE + POST              | 91    |
| STABLE      | REGULAR only                      | 304   |
| INACTIVE    | REGULAR only                      | 73    |
| (other)     | misc                              | 3     |

`edit_config.py` already supports session-scoped publisher edits, but it does
not add or remove session entries themselves. That's the gap.

## Goals

- Add or remove session entries on US-equity feeds (`Equity.US.*`,
  `metadata.asset_type == "equity"`).
- Dry-run by default; explicit `--apply` to write.
- Operate over a feed-ID selector (single, ranges, file/stdin), mirroring
  `edit-config` ergonomics.
- Use the AAPL/922 schedule strings as canonical templates so added sessions
  match the rest of the corpus.
- For added sessions, derive `benchmarkMapping` from the existing REGULAR
  session: keep the same RIC root + exchange suffix for REG/PRE/POST and
  swap to `<root>.BLUE` for OVER_NIGHT (consistent with PR #26).
- Print a unified diff with `feedId / symbol / session` hunk headers
  (consistent with `config_diff.py` output).
- Refuse to remove REGULAR unless `--force` is passed.
- Refuse to add a session that already exists (no-op match, warn).
- Refuse to operate on non-US-equity feeds (warn + skip, with `--force` to
  override for power users).

## Non-goals

- Adding/removing whole feeds. Use the existing tooling for that.
- Editing the schedule string itself. The canonical templates are the only
  supported form. If a feed has a non-standard schedule, the operator should
  use `edit_config` or hand-edit; this tool stays opinionated.
- Adding sessions to non-US-equity asset classes (FX, metals, crypto, etc.).
  Those have different session semantics and are out of scope.
- Editing `allowedPublisherIds` on the session being added. Added sessions
  start with `allowedPublisherIds: []` and `minPublishers:` set from a CLI
  flag (default `100`, an intentionally-unsatisfiable sentinel that keeps
  the session displayed-but-unusable until the operator pairs publishers
  via `edit_config` and lowers `minPublishers`).

## CLI

```bash
# Single op, dry-run is the default
python3 tools/session-editor/session_editor.py --config after.json \
    --remove-session OVER_NIGHT --feed-id 2500-2700

python3 tools/session-editor/session_editor.py --config after.json \
    --add-session OVER_NIGHT --feed-id 922,1000-1050 --min-publishers 2 --apply

# Multi-session
python3 tools/session-editor/session_editor.py --config after.json \
    --remove-session PRE_MARKET,POST_MARKET,OVER_NIGHT --feed-id 3100-3200

# YAML spec (batched ops)
python3 tools/session-editor/session_editor.py --config after.json \
    --from-spec session_edits.yaml --apply
```

Flags:

| Flag                    | Meaning                                                                 |
| ----------------------- | ----------------------------------------------------------------------- |
| `--add-session`         | Comma-list of sessions to add (PRE_MARKET,POST_MARKET,OVER_NIGHT)       |
| `--remove-session`      | Comma-list of sessions to remove                                        |
| `--feed-id`             | Selector grammar from edit-config (`922`, `1000-1050,2000`)             |
| `--feed-ids-from`       | Read selector from file or `-` for stdin                                |
| `--symbol-pattern`      | Additional filter (fnmatch)                                             |
| `--state`               | Additional filter (STABLE / COMING_SOON / INACTIVE)                     |
| `--min-publishers N`    | minPublishers for newly added sessions (default `100`, "not ready")     |
| `--verify-templates`    | Diff canonical templates vs. feedId 922 (AAPL); exit code != 0 on drift |
| `--dry-run` / `--apply` | Dry-run is default; `--apply` writes                                    |
| `--no-backup`           | Skip `after.json.bak` on apply                                          |
| `--force`               | Allow removing REGULAR / operating on non-US-equity feeds               |
| `--from-spec PATH`      | YAML batched ops                                                        |

## Behavior

### Adding a session

1. Locate the feed's existing REGULAR session (the source of truth for the
   feed's RIC + exchange suffix). If REGULAR is missing, refuse.
2. If the target session already exists on the feed: skip with a warning.
3. Construct a new session entry:
   - `session`: the target enum
   - `marketSchedule`: canonical template string (see below)
   - `minPublishers`: from `--min-publishers` (default 1)
   - `allowedPublisherIds`: `[]`
   - `benchmarkMapping`: copy from REGULAR; for OVER_NIGHT, rewrite the
     identifier suffix from the exchange code (`.O`, `.N`, `.A`, `.K`) to
     `.BLUE` while preserving the ticker root and `validFrom`.
4. Insert into `marketSchedules` at the canonical position so the array is
   always in order REGULAR → PRE_MARKET → POST_MARKET → OVER_NIGHT.

### Removing a session

1. Find the session entry by `session` field.
2. Refuse to remove REGULAR unless `--force`.
3. Delete the entry; preserve the rest verbatim.

### Canonical schedule strings (AAPL/922 template)

```
PRE_MARKET   "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
POST_MARKET  "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
OVER_NIGHT   "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,1224/0000-0400,1225/C,1231/0000-0400,0101/C"
REGULAR      (kept from existing feed; never synthesized)
```

These are extracted from feedId 922 (AAPL) and shared across all standard
US-equity 4-session feeds expanded in PR #26.

### Eligibility filter

A feed is eligible iff:

- `symbol.startswith("Equity.US.")`, AND
- `metadata.asset_type == "equity"`, AND
- it has an existing REGULAR session (for `--add-session`).

Ineligible feeds are skipped with a warning unless `--force`.

## Output

Plan summary, then a unified diff:

```
Plan:
  [1] AddSession OVER_NIGHT → 47 feed(s) matched, 2 skipped (already present)
  [2] RemoveSession PRE_MARKET → 12 feed(s) matched, 0 skipped

Validation: OK (0 errors, 2 warnings)

@@ feedId=1042 symbol=Equity.US.XYZW/USD session=OVER_NIGHT @@
+    {
+      "session": "OVER_NIGHT",
+      ...
+    }
...
```

On `--apply`, writes `after.json.bak` (unless `--no-backup`) then atomic
write of `after.json`.

## Layout

```
tools/session-editor/
├── README.md
├── session_editor.py                       # CLI wrapper
├── session_editor_lib/
│   ├── __init__.py
│   ├── templates.py                        # canonical schedule strings
│   ├── feed_filter.py                      # eligibility predicate
│   ├── ops.py                              # AddSession / RemoveSession
│   ├── editor.py                           # plan → simulate → apply
│   └── diff.py                             # unified diff w/ session-aware hunks
└── tests/
    ├── fixtures/
    │   └── sample_after.json
    ├── test_templates.py
    ├── test_ops.py
    ├── test_editor.py
    └── test_cli.py
```

Independent of `lib/` and `tools/edit-config/` (mirrors edit-config's
self-contained convention). Some patterns will be intentionally similar
(selector grammar, diff format) — they may be lifted/adapted, but not
imported, to keep the tools decoupled.

## Tests (pytest)

- Unit: schedule templates match AAPL/922 byte-for-byte; eligibility predicate
  rejects non-US equities; OVER_NIGHT benchmarkMapping rewrite covers `.O .N
.A .K` → `.BLUE`; ordering of inserted sessions is canonical.
- Integration: add → idempotent re-add is a no-op; remove → re-remove is a
  no-op; remove REGULAR without `--force` errors; add OVER_NIGHT without an
  existing REGULAR errors.
- CLI: dry-run does not modify; apply writes backup; YAML spec round-trip.

## Risks

- **Schedule template drift.** If the canonical schedules ever change
  (e.g., new market holidays), the template here will go stale. Mitigation:
  templates are centralized in `templates.py` with a comment pointing to
  AAPL/922 as the source. A small `--verify-template` flag could be added
  later to diff the template against a live feed.
- **Non-standard schedules.** Some feeds may have custom schedules. The
  tool refuses to overwrite them on `--add-session` (skip with warning)
  because we never synthesize a REGULAR schedule. `--remove-session` is
  always safe — we never touch the schedule string of remaining sessions.
- **`allowedPublisherIds` desync.** Removing a session leaves the top-level
  `allowedPublisherIds` untouched. That's intentional — the top-level list
  is the union; per-session lists are the source of truth for routing.
  The existing `config_linter` rules cover that invariant.

## Open questions

(Resolved by reasonable-call given the "work without stopping" directive;
flagged here so they're easy to overturn.)

1. **Default `--min-publishers` for added sessions.** Chose `100` (per
   operator preference). 100 is not a real publisher count for any feed
   today (real values are 1–3), so it serves as an intentional sentinel:
   the session is listed for visibility but is never satisfied until the
   operator explicitly lowers it after assigning publishers via
   `edit_config`. This directly addresses the "STABLE feed displaying
   unusable sessions" problem.
2. **Removing the last non-REGULAR session.** Allowed; the feed simply
   becomes REGULAR-only.
3. **YAML spec schema.** Mirrors `edit_config`'s spec shape: a top-level
   list of ops, each with `op`, `target`, and op-specific fields.
