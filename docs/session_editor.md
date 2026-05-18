# session_editor

Surgical editor for `after.json` that adds or removes market sessions on
US-equity feeds. Companion to [`edit_config`](edit_config.md).

- **Scope:** US-equity feeds only (`Equity.US.*`, `metadata.asset_type ==
"equity"`). Other asset classes are skipped unless `--force` is passed.
- **Default:** dry-run. Pass `--apply` to write.
- **Backup:** writes `after.json.bak` on apply unless `--no-backup`.

## When to use it

| Situation                                                        | Use this tool                                                                 |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Promoting a feed to STABLE but PRE/POST/OVER_NIGHT aren't ready  | `--remove-session PRE_MARKET,POST_MARKET,OVER_NIGHT`                          |
| Adding OVER_NIGHT to a feed that just got 24h publisher coverage | `--add-session OVER_NIGHT --min-publishers 100`, then lower via `edit_config` |
| Cleaning up the 1019 backfilled feeds from PR #26                | `--remove-session ... --feed-ids-from list.txt`                               |
| Verifying the canonical templates haven't drifted from AAPL/922  | `--verify-templates`                                                          |

For per-session publisher / `minPublishers` / `state` edits, keep using
[`edit_config`](edit_config.md) — this tool intentionally doesn't overlap.

## CLI

```text
session_editor.py --config PATH
                  (--add-session SESSIONS | --remove-session SESSIONS
                   | --from-spec PATH      | --verify-templates)
                  [--feed-id SELECTOR]
                  [--feed-ids-from PATH-or--]
                  [--symbol-pattern GLOB]
                  [--state STABLE|COMING_SOON|INACTIVE]
                  [--min-publishers N]          (default: 100)
                  [--force]
                  [--apply | --dry-run]         (default: dry-run)
                  [--no-backup]
                  [--show-full-diff]
```

### Flags

| Flag                 | Effect                                                                                 |
| -------------------- | -------------------------------------------------------------------------------------- |
| `--config PATH`      | Path to `after.json`.                                                                  |
| `--add-session L`    | Comma list from `{PRE_MARKET, POST_MARKET, OVER_NIGHT}`.                               |
| `--remove-session L` | Comma list from `{REGULAR, PRE_MARKET, POST_MARKET, OVER_NIGHT}`.                      |
| `--from-spec PATH`   | YAML batch spec (see below).                                                           |
| `--verify-templates` | Diff canonical templates against feedId 922 (AAPL); non-zero exit on drift.            |
| `--feed-id`          | Selector: `922`, `1000-1050`, `1000-1050,2000`.                                        |
| `--feed-ids-from`    | Read selector(s) from a `.txt` file (or `-` for stdin). See "Input file format" below. |
| `--symbol-pattern`   | `fnmatch` glob on `feed.symbol` (e.g. `'Equity.US.A*'`).                               |
| `--state`            | Filter to feeds in a given state.                                                      |
| `--min-publishers N` | minPublishers on added sessions. Default `100` (sentinel: not yet ready).              |
| `--force`            | Allow non-US-equity feeds and allow removing `REGULAR`.                                |
| `--apply`            | Write to disk. Without it, the tool only previews.                                     |
| `--no-backup`        | Skip writing `after.json.bak` on apply.                                                |
| `--show-full-diff`   | Print the full diff regardless of size.                                                |

### Eligibility

A feed is eligible iff:

- `symbol.startswith("Equity.US.")`, **and**
- `metadata.asset_type == "equity"`, **and**
- it has a `REGULAR` session (required to derive `benchmarkMapping` and
  prove the feed shape is right).

`--force` overrides the first two conditions; the REGULAR-presence check is
absolute for `--add-session` (we never synthesize a REGULAR schedule).

## Input file format (`--feed-ids-from`)

A plain-text file of feed-ID selectors, **one selector per line**, exactly
the same shape `tools/edit-config` uses:

```text
# stable-missing-overnight.txt
921      # Equity.US.A/USD
923-925  # ABBV, ABNB, ABT
2031
2057-2059
```

- Lines may be a single feed-ID, a `lo-hi` inclusive range, or a comma list
  combining both (e.g. `1000-1050,2000`).
- Leading/trailing whitespace is ignored.
- `#` starts a comment; everything from `#` to end-of-line is dropped.
- Blank lines are skipped.

Pass `-` instead of a path to read selectors from stdin:

```bash
echo "922
924
1000-1010" | session_editor.py --config after.json \
                --add-session OVER_NIGHT --feed-ids-from -
```

The generated remediation lists under
[`tools/session-editor/remediation/`](../tools/session-editor/remediation/)
are ready to feed straight in — they follow this exact format.

> **CSV?** Not supported. Use the `.txt` selector form above (or
> `--from-spec PATH` for YAML batched ops that mix add/remove across feeds).

## What `--add-session` produces

For each matched feed, a new session entry is inserted into `marketSchedules`
at the canonical position (so the array is always ordered
`REGULAR → PRE_MARKET → POST_MARKET → OVER_NIGHT`):

```json
{
  "allowedPublisherIds": [],
  "benchmarkMapping": { ...copied from REGULAR (BLUE-rewritten for OVER_NIGHT)... },
  "marketSchedule": "<canonical AAPL/922 string for this session>",
  "minPublishers": 100,
  "session": "<target>"
}
```

The canonical schedule strings live in
[`session_editor_lib/templates.py`](../tools/session-editor/session_editor_lib/templates.py).
They were extracted byte-for-byte from feedId 922 (AAPL) and are shared by
every standard US-equity 4-session feed produced by PR #26.

### The `minPublishers: 100` sentinel

`100` is not a real publisher count for any feed in `after.json` today (real
values are 1–3). Using it as the default for newly added sessions means the
session is **listed for visibility but never satisfied** until an operator
explicitly lowers `minPublishers` via `edit_config` after assigning a real
publisher cohort. This directly addresses the "STABLE feed displaying
unusable sessions" problem.

### OVER_NIGHT identifier rewrite

When adding `OVER_NIGHT`, RIC identifiers in `benchmarkMapping` are rewritten
to the `.BLUE` form. Suffixes covered: `.O`, `.N`, `.A`, `.K`.

| REGULAR RIC | OVER_NIGHT RIC |
| ----------- | -------------- |
| `AAPL.O`    | `AAPL.BLUE`    |
| `IBM.N`     | `IBM.BLUE`     |
| `BRKb.N`    | `BRKb.BLUE`    |
| `UEEC.K`    | `UEEC.BLUE`    |

This matches the LSEG/Datascope convention used by PR #26.

## What `--remove-session` produces

The matching session entry is removed from `marketSchedules`. Top-level
`allowedPublisherIds` is untouched (it's the union and is regenerated
elsewhere).

`REGULAR` is refused without `--force`.

## YAML batch spec

Shape (mirrors `edit_config`):

```yaml
version: 1
operations:
  - op: add_session
    session: OVER_NIGHT # str or list
    min_publishers: 100 # optional; default 100
    feed_id: "1000-1050,2000" # int, str-selector, or list of either
    symbol_pattern: "Equity.US.A*" # optional
    state: COMING_SOON # optional
    force: false # optional

  - op: remove_session
    session: [PRE_MARKET, POST_MARKET]
    feed_id: [922, "3000-3050"]
```

Unknown keys are rejected (no silent typos).

## Examples

### Preview removing OVER_NIGHT from the backfilled range

```bash
python3 tools/session-editor/session_editor.py \
    --config after.json \
    --remove-session OVER_NIGHT \
    --feed-id 2500-2700 \
    --state COMING_SOON
```

### Promote a small batch by adding OVER_NIGHT

```bash
echo "
1042
1057-1059
2031
" | python3 tools/session-editor/session_editor.py \
       --config after.json \
       --add-session OVER_NIGHT \
       --feed-ids-from - \
       --apply
```

### Audit-only: how many STABLE feeds advertise OVER_NIGHT?

```bash
python3 tools/session-editor/session_editor.py \
    --config after.json \
    --remove-session OVER_NIGHT --state STABLE \
    --symbol-pattern 'Equity.US.*'
# Read the plan summary, then drop the --remove-session flag and don't apply.
```

(Or use the linter — but this is a quick approximation.)

### Verify templates against AAPL

```bash
python3 tools/session-editor/session_editor.py --config after.json --verify-templates
# Exits 0 on match, 1 on drift; useful in CI.
```

## Exit codes

| Code | Meaning                                                              |
| ---- | -------------------------------------------------------------------- |
| `0`  | Dry-run preview printed, OR `--apply` succeeded, OR templates match. |
| `1`  | Template drift detected via `--verify-templates`.                    |
| `2`  | Argument / spec error.                                               |

## Limitations & non-goals

- Doesn't add/remove whole feeds. Use existing tooling.
- Doesn't synthesize REGULAR schedules. A feed without REGULAR can't be
  added to.
- Doesn't edit individual schedule strings. The canonical AAPL templates
  are the only supported form for added sessions — operators with custom
  schedules should use `edit_config` or hand-edit.
- Doesn't touch top-level `allowedPublisherIds` on removal. The
  `config_linter` covers union-consistency.

## Risks

- **Template drift.** If NYSE/NASDAQ holiday calendar changes,
  `templates.py` may go stale. Mitigation: `--verify-templates` against
  AAPL/922 in CI; update the constants when AAPL changes.
- **Non-standard schedules.** Operating on feeds whose existing REGULAR has
  a non-AAPL schedule still works (we only read the benchmark mapping from
  REGULAR, not the schedule string), but added PRE/POST/OVER_NIGHT will use
  the AAPL templates regardless. Use with care on non-standard feeds.

## See also

- [Design spec](superpowers/specs/2026-05-18-session-editor-design.md)
- [edit_config](edit_config.md) — the per-session publisher / state editor
- [config_linter](config_linter.md) — invariant checks
- PR #26 (backfill-apids) — the source of the 4-session expansion this tool
  mirrors
