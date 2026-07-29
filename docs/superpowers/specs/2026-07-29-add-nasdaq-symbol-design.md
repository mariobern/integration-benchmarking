# add_nasdaq_symbol — Backfill nasdaq_symbol for Asian Equity Feeds

**Date:** 2026-07-29
**Status:** Design approved, pending implementation plan
**Module:** `add_nasdaq_symbol.py` (repo root)

## Background & Motivation

US equity feeds already carry `metadata.nasdaq_symbol`, set equal to `metadata.name`
(e.g. `AAPL`'s feed has `"name": "AAPL", "nasdaq_symbol": "AAPL"`). HK, CN, JP, KR, and IN
equity feeds have no `nasdaq_symbol` field at all today.

For these markets, `metadata.name` currently holds the raw exchange-issued code or ticker
downstream users actually use to look up the security — a numeric code for HK/CN/JP/KR
(`0002`, `603986`), or, for the handful of already-alphabetic names, the literal ticker
(`NIFTYBEES`, `HKHZ5`, `KSH6`, `1321-JP`). Separately, `rename_numeric_feed_names.py`
(see
[2026-07-28-numeric-feed-name-rename-design.md](2026-07-28-numeric-feed-name-rename-design.md))
overwrites `metadata.name` with a human-readable company name derived from
`metadata.description`, for display purposes. Once that rename runs, the original
downstream-facing code is gone from `metadata.name` — so it needs to be preserved in
`nasdaq_symbol` before that happens.

This design adds a one-purpose script that copies `metadata.name` into a new
`metadata.nasdaq_symbol` field for every in-scope Asian equity feed, verbatim, while it
still holds the original code.

## Goal

For every HK/CN/JP/KR/IN equity feed in `lazer_jpkr.json`, set
`metadata.nasdaq_symbol = metadata.name` (verbatim, no transformation), so the
exchange-facing identifier survives independently of any later display-name rename.

## Scope

**In scope:**

- New standalone script `add_nasdaq_symbol.py` at repo root, targeting `lazer_jpkr.json`.
- Symbol prefixes: `Equity.HK.`, `Equity.CN.`, `Equity.JP.`, `Equity.KR.`, `Equity.IN.`
  (a new prefix tuple, distinct from `rename_numeric_feed_names.MARKET_PREFIXES`, which
  excludes IN).
- All feed states (STABLE, COMING_SOON, INACTIVE) — `nasdaq_symbol` is descriptive
  metadata, not gated on lifecycle state.
- Unit tests `tests/test_add_nasdaq_symbol.py`.
- Docs: `docs/add_nasdaq_symbol.md` plus a row in the CLAUDE.md Scripts table.

**Out of scope:**

- Any config file other than `lazer_jpkr.json` (not `lazer-state.json`, `lazer_new.json`,
  `lazer_newest.json`, `lazer_to_modify.json`, or `state.json` — those are snapshots from
  other in-flight work).
- Any transformation of the value being copied (no stripping, no normalization) — this is
  a verbatim copy-forward, not a derivation like `rename_numeric_feed_names.py`'s
  `derive_name()`.
- Markets outside HK/CN/JP/KR/IN (US equities already have `nasdaq_symbol`; other asset
  classes don't use this field).
- Modifying `rename_numeric_feed_names.py` itself — kept as a separate script so the two
  transformations (rename metadata.name vs. backfill nasdaq_symbol) stay independently
  testable and independently re-runnable, matching how `generate_short_name_candidates.py`
  was deliberately kept separate from the renamer in PR#64.

## Design

### 1. Candidate selection

Runs over every feed whose `symbol` starts with one of the configured prefixes
(`--symbol-prefix`, repeatable, defaults to the 5 above — same CLI shape as
`rename_numeric_feed_names.py`).

### 2. Per-feed decision — `plan_change(feed)`

For each in-scope feed:

1. **Already set:** if `metadata.nasdaq_symbol` is present (any value, including empty
   string), skip with reason `"nasdaq_symbol already set"`. This is what makes the script
   idempotent — a second run over an unchanged config is a no-op.
2. **Empty name:** if `metadata.name` is empty/missing, skip with reason
   `"metadata.name is empty"` — nothing to copy.
3. **Suspicious name (ordering guard):** if `metadata.name` contains whitespace, skip with
   reason `"metadata.name looks like a display name, not a code (contains whitespace)"`.
   Every real exchange code/ticker observed in `lazer_jpkr.json` today is a single
   whitespace-free token (`603986`, `0002`, `HKHZ5`, `KSH6`, `NIFTYBEES`, `1321-JP`);
   every name `rename_numeric_feed_names.py` produces is a multi-word company name
   (`GIGADEVICE SEMICONDUCTOR INC`). This catches the hazard of running this script
   against a config where the rename has already happened, which would otherwise copy a
   display name into `nasdaq_symbol` silently.
4. **Otherwise:** plan `metadata.nasdaq_symbol = metadata.name`, verbatim.

This mirrors the `Change`/`Skip` dataclass-and-report shape used by
`rename_numeric_feed_names.py` and `generate_short_name_candidates.py`.

### 3. Applying changes — key order

Every existing `metadata` dict in `lazer_jpkr.json` is already alphabetically
key-sorted (verified against both HK and US-equity sample feeds), and on US feeds
`nasdaq_symbol` already sits between `name` and `quote_currency` — consistent with strict
alphabetical order. When a change is applied, the feed's `metadata` dict is rebuilt with
its keys in sorted order (rather than appending `nasdaq_symbol` at the end via plain
dict assignment), so newly-touched feeds keep the same key ordering as the
already-populated US feeds and nothing looks out of place in the diff.

### 4. Verification — JSON-aware, not line-diff

`rename_numeric_feed_names.py`'s `verify_text` assumes line count never changes, because
renaming an existing value never adds a line. That assumption doesn't hold here: adding
`nasdaq_symbol` adds one line per change. Verification is JSON-aware instead:

1. Reload the written file; the feed-id set must be unchanged.
2. Every feed **not** in the change set must have a byte-identical `metadata` dict to
   before (nothing leaks outside the planned set).
3. Every feed **in** the change set must have exactly the planned `nasdaq_symbol` value
   added, and every other key in its `metadata` dict unchanged from before.

This is the same spirit as `rename_numeric_feed_names.py`'s `verify_feed_names` (JSON-path
-aware, not multiset-based), extended to check a whole dict instead of one field, and
without the companion line-count check (which doesn't apply when lines are being added).

### 5. CLI

```
add_nasdaq_symbol.py --config lazer_jpkr.json [--symbol-prefix ...] [--apply] [--no-backup]
```

- `--config` (required): path to the config (in practice always `lazer_jpkr.json` for this
  rollout, but not hardcoded, consistent with sibling scripts).
- `--symbol-prefix` (repeatable): defaults to `Equity.HK.`, `Equity.CN.`, `Equity.JP.`,
  `Equity.KR.`, `Equity.IN.`.
- `--apply`: write changes (dry run is the default, matching every other config-editing
  script in this repo).
- `--no-backup`: skip the `.bak` copy `--apply` makes by default.

### 6. Output / reporting

Console report in the same shape as the two prior scripts: a change table
(`feed_id  symbol  name -> nasdaq_symbol value`), a skip table with per-feed reasons, and a
summary line with counts. No CSV output — this script writes directly to the config file
(behind `--apply`), unlike `generate_short_name_candidates.py`, because the value being
written is a verbatim copy with no judgment call for a human to review.

## Testing

`tests/test_add_nasdaq_symbol.py`, fixture-based:

1. In-scope numeric name (HK/CN/JP/KR) → `nasdaq_symbol` set to that value.
2. In-scope alphabetic-but-whitespace-free name (`NIFTYBEES`, `HKHZ5`, `KSH6`) →
   `nasdaq_symbol` set to that value.
3. `metadata.nasdaq_symbol` already present → skipped, reported, value unchanged.
4. `metadata.name` contains a space (already renamed) → skipped, reported, no
   `nasdaq_symbol` added.
5. `metadata.name` empty → skipped, reported.
6. Feed outside the configured prefixes (e.g. `Equity.US.*`, `Equity.Index.*`) → never
   touched.
7. Key ordering: after applying, the feed's `metadata` dict keys are alphabetically
   sorted.
8. Verification catches an injected corruption (a change written to the wrong feed, or an
   unplanned field altered) by raising `VerificationError`.
9. Full-file round trip on a small fixture config: feed count unchanged, only planned
   feeds changed, `--no-backup` suppresses the `.bak` file, dry run (no `--apply`) writes
   nothing.

Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash, so
this suite is run on its own:

```bash
pytest tests/test_add_nasdaq_symbol.py -v
```

Real-data smoke test (manual, not asserted in CI): dry run against `lazer_jpkr.json` and
eyeball the change/skip counts (465 in-scope feeds today: expect ~465 changes and 0 skips,
since no feed in this file has been renamed or already carries `nasdaq_symbol` yet).

## Definition of Done

- [ ] `add_nasdaq_symbol.py` implemented: dry-run by default, `--apply` to write, `.bak`
      backup unless `--no-backup`.
- [ ] All automated unit tests pass.
- [ ] `docs/add_nasdaq_symbol.md` written; CLAUDE.md Scripts table updated.
- [ ] `pre-commit run --files <changed files>` passes.
- [ ] Dry run against `lazer_jpkr.json` reviewed by hand before `--apply` is used for real.
