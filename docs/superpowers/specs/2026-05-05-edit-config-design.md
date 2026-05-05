# edit-config: Design Spec

**Date:** 2026-05-05
**Status:** Draft (pending user review)
**Branch:** `feat/edit-config-tool`

## Problem

`after.json` is a 3.4 MB Lazer feed config with 3,258 feeds. Operators
routinely need to make small, targeted edits — add/remove a publisher
across a range of feeds, change `minPublishers`, promote or retire a
feed by changing its `state` — and today these edits are either manual
(error-prone, tedious) or routed through specialized data-driven scripts
that don't fit ad-hoc intent:

| Tool                            | Purpose                                         | Limit                                                                      |
| ------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------- |
| `update_config_from_summary.py` | Bulk edit publisher lists from a readiness CSV  | Requires CSV; data-driven only                                             |
| `update_min_publishers.py`      | Enforce `minPublishers` floor by count rule     | Skips extended-hours equities; never edits per-session; no manual override |
| `update_lazer_symbols.py`       | Promote `COMING_SOON` → `STABLE` from a summary | One direction; summary-driven                                              |

Concrete pain point: "add publisher 80 to feeds 1000–1050" today requires
51 manual JSON edits with no validation, diff, or rollback.

## Goal

A surgical, manual-intent editor for `after.json` that:

1. Adds/removes publishers from `allowedPublisherIds` (top-level and
   per-session for US equity feeds with extended hours).
2. Sets or bumps `minPublishers` (top-level and per-session).
3. Sets `state` (`STABLE`, `COMING_SOON`, `INACTIVE`).
4. Operates via single-op CLI flags or batched YAML specs.
5. Is dry-run by default, prints a hunk-headed diff, validates atomically,
   and writes a `.bak` before applying.
6. Is fully independent of the other update scripts — no shared imports.

## Non-goals

- **Rule-based enforcement** (count → minPublishers thresholds, etc.).
  That stays in `update_min_publishers.py`.
- **Data-driven edits** from readiness CSVs. That stays in
  `update_config_from_summary.py`.
- **Modifying any non-publisher / non-minPublishers / non-state fields**
  (no edits to `marketSchedule`, `metadata`, `expiryTime`, `symbol`, etc.).
- **`feedId` editing or feed creation/deletion** — out of scope.

## Schema reality (informs the design)

Across 3,258 feeds:

| Pattern                              | Count  | Asset types                                                     | Edit semantics                                          |
| ------------------------------------ | ------ | --------------------------------------------------------------- | ------------------------------------------------------- |
| Top-level only, no per-session lists | 3,029  | crypto, fx, equity (single-session), commodity, metal, rates, … | Only top-level is editable; sessions hold schedule only |
| Top-level + 4 per-session lists      | 115    | US equities with extended hours                                 | Both editable, **independently**                        |
| Empty (no publishers anywhere)       | ~1,099 | Mostly unconfigured / `COMING_SOON`                             | Edits create/populate as needed                         |

**Top-level is not a derived view of per-session.** Feed 922 (AAPL) currently
has 5 publishers in top-level that aren't in any session
(`11, 13, 57, 72, 73`). Top-level is an authoritative roster; per-session
lists are the active subset for that session.

Session names in the file: `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`.

States in the file: `STABLE` (968), `COMING_SOON` (1,949), `INACTIVE` (341).

## Operations

### `add_publisher`

For each matched feed:

- **Default scope** (no `session` given):
  - Equity feed with sessions → add to top-level `allowedPublisherIds`
    AND to REGULAR session's `allowedPublisherIds`.
  - Non-equity (no per-session lists) → add only to top-level.
- **`session: REGULAR/PRE_MARKET/POST_MARKET/OVER_NIGHT`** → add to that
  session AND to top-level. Hard error if the session doesn't exist on
  the feed.
- **`session: ALL`** → add to all 4 sessions if they exist AND to top-level.
  Hard error on a feed with no per-session lists.
- **`session: NONE`** → top-level only.
- **NOOP** if the publisher is already in every targeted list.
- `minPublishers` is left untouched.
- Lists are deduped and sorted ascending after the edit.

### `remove_publisher`

For each matched feed:

- **Default scope**: remove from **everywhere** in this feed — the
  top-level list AND every session list that contains the publisher.
  The natural meaning of "remove publisher X" is "evict entirely."
- **`session: REGULAR/...`** → remove from that session only; top-level
  untouched (publisher may still be active in another session).
- **`session: ALL`** → remove from every session, leave top-level alone.
- **`session: NONE`** → remove from top-level only; sessions untouched.
  Tool emits a consistency warning since publishers in sessions but not
  in top-level may fail downstream validation.
- **NOOP** if not present in any targeted list.
- **Warning** (does not block apply) if removal leaves any list with
  `len(allowed) <= minPublishers` (zero headroom or worse).

### `set_min_publishers`

For each matched feed:

- **Default scope**: top-level only for non-equity; top-level + REGULAR
  for equities (mirrors `add_publisher`).
- **Explicit `session`**: that session only. Top-level untouched unless
  `session: NONE`.
- **Hard error** if `value > len(allowed)` in any targeted list —
  unsatisfiable threshold.
- **Warning** if `value >= len(allowed)` (at-floor; zero headroom).
- **Warning** if `value == 1` on a `STABLE` feed (unusual posture).

### `bump_min_publishers`

Same defaults and warnings as `set_min_publishers`. Adds a `delta` (signed
int). Result is clamped at floor of 1 (never below).

### `set_state`

- Per-feed `state` field only — no per-session state exists.
- **Soft guardrails** (warn, don't block):
  - `STABLE → COMING_SOON` (regression)
  - `STABLE → INACTIVE` (deactivation)
  - `INACTIVE → STABLE` (reactivation — sanity check)
- **NOOP** if already in target state.

### Defaults summary

| Op                    | Equity feed default            | Non-equity default |
| --------------------- | ------------------------------ | ------------------ |
| `add_publisher`       | top-level + REGULAR            | top-level          |
| `remove_publisher`    | top-level + all sessions       | top-level          |
| `set_min_publishers`  | top-level + REGULAR            | top-level          |
| `bump_min_publishers` | top-level + REGULAR            | top-level          |
| `set_state`           | top-level (no session concept) | top-level          |

## Targeting

Targeting flags are AND-combined. **At least one targeting flag is required**
for any operation; there is no implicit "edit everything" default.

| Filter         | CLI form                                                 | YAML form                                          |
| -------------- | -------------------------------------------------------- | -------------------------------------------------- |
| Feed ID        | `--feed-id 922` or `--feed-id 100-200,205,208,3530-3540` | `feed_id: 922` or `feed_id: [100, "200-250", 300]` |
| From file      | `--feed-ids-from feeds.txt` (or `-` for stdin)           | _(use CLI; YAML inlines the list directly)_        |
| Symbol pattern | `--symbol-pattern "Equity.US.*"`                         | `symbol_pattern: "Equity.US.*"`                    |
| Asset class    | `--asset-class us-equities`                              | `asset_class: us-equities`                         |
| State          | `--state STABLE`                                         | `state: STABLE` or `state: [STABLE, COMING_SOON]`  |

### Feed ID selector syntax

A single, unified syntax is used everywhere a feed ID can be specified
(CLI `--feed-id`, the file behind `--feed-ids-from`, and YAML `feed_id`).
Each entry is one of:

- A single feed ID: `922`
- An inclusive range: `100-200` (requires `A <= B`)

CLI, file, and YAML each accept a list of these entries. Resolution is
the union of all entries (deduplicated). `--feed-id` and
`--feed-ids-from` may both be passed in the same invocation; their
results are unioned.

`state` accepts a list only in YAML; CLI takes a single value (pipe
through a spec for multi-state filtering).

### `--feed-ids-from` file format

Plain text, UTF-8. Forgiving parser:

- **Tokens**: a token is `N` (single ID) or `A-B` (range).
- **Separators**: tokens may be separated by commas, whitespace, or
  newlines — any combination. Internally split on `[,\s]+`.
- **Comments**: `#` to end-of-line is stripped before tokenization.
- **Blank lines** ignored.
- **No header**, no quoting.
- **Errors**: any token not matching `^\d+$` or `^\d+-\d+$` is a hard
  error with line and column. Empty file is a hard error (matches the
  "zero target match" rule below).

Example file (all four equivalent):

```text
# canonical one-per-line
100-200
205
208
275
299
3530
```

```text
# inline (paste from a slack message)
100-200, 205, 208, 275, 299, 3530
```

```text
# annotated
100-200    # contig run from the incident
205 208    # spotty middle
275, 299
3530       # one-off
```

```text
# everything on one line
100-200,205,208,275,299,3530
```

Stdin: pass `-` as the path. Useful for piping from other tools, e.g.
`awk -F, 'NR>1 {print $1}' summary.csv | edit_config.py --feed-ids-from -`.

**Hard error** if the resolved target set is empty for any operation.
Silent zero-match is a footgun, not a feature.

## Tool surface

### CLI

Exactly one operation flag per CLI invocation. Use the YAML spec for
multi-op runs.

```text
python3 tools/edit-config/edit_config.py --config after.json [OP] [TARGETING] [SCOPE] [EXEC]
```

Operation (mutually exclusive):

- `--add-publisher INT`
- `--remove-publisher INT`
- `--set-min-publishers INT`
- `--bump-min-publishers ±INT`
- `--set-state {STABLE,COMING_SOON,INACTIVE}`
- `--from-spec PATH`

Targeting (≥1 required when not using `--from-spec`; AND-combined):

- `--feed-id SELECTOR` — single ID, range, or comma-separated mix:
  `922` / `1000-1050` / `100-200,205,208,3530-3540`. Repeatable;
  multiple `--feed-id` flags are unioned.
- `--feed-ids-from PATH` — read selector(s) from a file (or stdin via
  `-`). Same selector grammar; whitespace, commas, newlines, and `#`
  comments all accepted. See "`--feed-ids-from` file format" above.
- `--symbol-pattern GLOB` — `fnmatch`-style: `*`, `?`, `[abc]`.
- `--asset-class STR` — matched against `metadata.asset_type`.
- `--state {STABLE,COMING_SOON,INACTIVE}` — single state filter.

Scope (publisher / minPublishers ops; ignored for `set-state`):

- `--session {REGULAR,PRE_MARKET,POST_MARKET,OVER_NIGHT,ALL,NONE}`

Execution:

- `--dry-run` (default; explicit form for clarity)
- `--apply` (required to write)
- `--show-full-diff` (don't truncate the diff output)
- `--no-lint` (skip post-apply config-linter run)
- `--no-backup` (skip `.bak` write)

Exit codes: `0` = success (warnings allowed), `1` = validation/runtime error.

### YAML spec

```yaml
# edits.yaml
version: 1
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: "1000-1050"
    # session omitted → default

  - op: remove_publisher
    publisher_id: 22
    feed_id: 922
    session: PRE_MARKET

  - op: set_min_publishers
    value: 3
    asset_class: us-equities
    state: STABLE
    session: REGULAR

  - op: bump_min_publishers
    delta: +1
    feed_id: [1000, 1001, 1002]

  - op: set_state
    value: COMING_SOON
    feed_id: [500, 501, 502]

  - op: add_publisher
    publisher_id: 80
    feed_id: [100, "200-250", 300, "400-410", 500] # mixed singles + ranges
    session: NONE

  - op: add_publisher
    publisher_id: 90
    symbol_pattern: "Equity.US.*"
    state: [STABLE, COMING_SOON]
    session: ALL
```

Schema rules:

- `version` is optional; tool warns on unknown values, fails on `version > 1`.
- Each entry must have an `op` plus at least one targeting field plus the
  op-specific value field (`publisher_id`, `value`, `delta`).
- **Unknown keys fail validation** (typos shouldn't silently drop ops).
- Operations are applied **in spec order**.
- `feed_id` accepts a single integer, a range string (`"A-B"`), or a
  list whose entries are integers and/or range strings. Range strings
  must be quoted (unquoted `1000-1050` is parsed by YAML as the
  arithmetic expression `-50`).

## Validation pipeline

```
1. Parse spec (CLI flags → single Op, OR YAML → list of Ops)
2. Load after.json (parse + keep raw text for surgical edits)
3. For each Op, in spec order:
   a. Resolve target filter → list of matching feeds
   b. Hard error if zero matches
   c. Simulate the op on a parsed working-copy structure
   d. Collect: changes, NOOPs, warnings, errors
4. Render output:
   - **Always** on dry-run: print plan, validation result (errors and/or
     warnings), and diff (truncated). The diff reflects the simulated
     post-op state regardless of error status — this lets you see what
     would have changed even when validation blocks an apply.
   - On `--apply`: print plan and validation result. Print diff only if
     validation passes (otherwise no write happens, so a "what would
     have been" diff is misleading).
   - Errors set the exit code to 1; warnings do not.
5. If --apply and no errors:
   - Apply text edits to the raw string in spec order
   - Write .bak (unless --no-backup)
   - Write after.json
   - Run config-linter (unless --no-lint), print findings (informational)
   - Exit 0
```

The simulation in step 3c uses the parsed structure so we detect
inter-op interactions (op 2 removes a publisher op 1 just added, etc.).
The actual write in step 5 uses raw-string surgical edits to preserve
formatting (single-line publisher arrays, indentation, etc.) and
produce reviewable diffs.

## Output format

Dry-run output (default):

```
Reading after.json (3,258 feeds)...
Parsing edits.yaml... 4 operations.

Plan:
  [1] add_publisher pub=80 → feeds 1000-1050
      matched 51 feeds (5 NOOP, 46 changes)
  [2] remove_publisher pub=22 → feed 922 PRE_MARKET
      matched 1 feed (1 change)
  [3] set_min_publishers value=3 → asset_class=us-equities AND state=STABLE AND session=REGULAR
      matched 89 feeds (12 NOOP, 77 changes)
  [4] set_state value=COMING_SOON → feed_id [500,501,502]
      matched 3 feeds (3 changes)
      WARNING: feed 500 STABLE → COMING_SOON (regression)
      WARNING: feed 501 STABLE → COMING_SOON (regression)
      WARNING: feed 502 STABLE → COMING_SOON (regression)

Validation: PASS (0 errors, 3 warnings)

Diff (truncated; full diff with --show-full-diff):
--- after.json
+++ after.json (proposed)
@@ feedId 1000 @@
-      "allowedPublisherIds": [ 1, 3, 14, 22, 41, 54 ],
+      "allowedPublisherIds": [ 1, 3, 14, 22, 41, 54, 80 ],
@@ feedId 922 (Equity.US.AAPL/USD), session PRE_MARKET @@
-          "allowedPublisherIds": [ 19, 20, 22, 41, 42, 45, 55, 59, 65 ],
+          "allowedPublisherIds": [ 19, 20, 41, 42, 45, 55, 59, 65 ],
... (1247 more changed lines; rerun with --show-full-diff)

Summary: 127 changes across 130 feeds, 0 errors, 3 warnings.
[DRY RUN] No changes written. Re-run with --apply to write after.json.
```

Apply output:

```
[same plan + validation as above]

Backup written: after.json.bak
Wrote 127 changes to after.json.
Running config-linter on after.json...
✓ No lint findings.
```

Hunk headers carry feedId, symbol, and session — plain unified-diff line
numbers in a 3.4 MB file are unreadable. Diff truncates at 40 hunks by
default; `--show-full-diff` opts out.

Diff is **always** printed on dry-run (even on validation failure, after
the error report). Diff is printed on `--apply` only after validation
passes.

## File layout

```
tools/edit-config/
  README.md
  edit_config.py                       # CLI wrapper (~80 lines)
  lib/
    __init__.py
    config_editor.py                   # orchestrator
    config_ops.py                      # operation classes
    config_text_surgery.py             # bracket scanner, block locators
    config_diff.py                     # diff renderer with custom hunk headers
  tests/
    __init__.py
    test_config_text_surgery.py
    test_config_ops.py
    test_config_editor.py
    test_edit_config_cli.py
    fixtures/
      after_sample.json                # ~10 representative feeds
      edits_basic.yaml
      edits_invalid.yaml

docs/
  edit_config.md                       # full usage reference
  edit_config_examples.md              # copy-pasteable recipes

docs/superpowers/specs/
  2026-05-05-edit-config-design.md     # this document
```

**Independence:** no imports from `update_config_from_summary.py`,
`update_min_publishers.py`, `update_lazer_symbols.py`, or the repo-level
`lib/` package. The bracket-depth scanner and block locators are
re-implemented inside `tools/edit-config/lib/config_text_surgery.py`.

## Testing strategy

Per repo `testing.md`: ≥ 80 % coverage, TDD, pytest.

- **Unit tests, surgery** (`test_config_text_surgery.py`): bracket
  scanner, escaped quotes, nested arrays, feed/session block bounds.
- **Unit tests, ops** (`test_config_ops.py`): each op in isolation —
  happy path, NOOP, hard errors, every session scope, equity vs
  non-equity defaults, the `len <= minPublishers` warning.
- **Integration tests** (`test_config_editor.py`): full YAML →
  plan → diff → write cycle on the fixture file; atomicity (one
  error → no write); inter-op interaction (op 2 sees op 1's effect).
- **CLI tests** (`test_edit_config_cli.py`): subprocess invocation,
  exit codes, `.bak` creation, lint integration, diff truncation.
- **Coverage gate**: `pytest --cov=tools/edit-config --cov-fail-under=80`.

## Linter integration

After successful `--apply`, invoke
`tools/config-linter/config_linter.py` as a subprocess against the
freshly written `after.json`. Findings are printed for awareness;
non-zero linter exit code is informational and does **not** make
edit-config exit non-zero (lint findings may pre-exist). `--no-lint`
skips this step entirely.

## Documentation

- `docs/edit_config.md` — usage reference: CLI flags, spec schema,
  op semantics, defaults table, exit codes, examples per op.
- `docs/edit_config_examples.md` — recipes:
  - "add a publisher to all FX feeds"
  - "promote 5 specific feeds COMING_SOON → STABLE"
  - "raise minPublishers across us-equities REGULAR by 1"
  - "deactivate a list of feeds"
  - "remove a retired publisher entirely"
- New row in `CLAUDE.md` Scripts table.

## Open questions deferred to implementation

None blocking. Two minor items to confirm during implementation, both
have defensible defaults:

- Glob syntax for `--symbol-pattern`: shell-style (`*`, `?`, `[abc]`) via
  `fnmatch`. Fast and standard. Decision pending only if a more powerful
  matcher proves needed.
- Whether `--apply` should require a TTY confirmation prompt for ops
  touching > N feeds (e.g., > 100). Current spec: no prompt — `--dry-run`
  default already enforces a review step. A `--confirm` flag could be
  added later if requested.

## Out of scope (for this PR)

- Modifying any field besides `allowedPublisherIds`, `minPublishers`,
  `state`.
- Creating, deleting, or renaming feeds.
- Reordering existing publisher entries (lists are sorted ascending; if
  a feed currently has unsorted lists, edit-config will sort on write —
  this is a deliberate normalization).
- Reading/writing other config files in the repo.
- A web UI or VS Code extension wrapper. Possible follow-up; the existing
  `tools/vscode-extension/` could later wrap this tool the same way it
  wraps the linter.
