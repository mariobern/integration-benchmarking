# Temporary per-run publisher exclusion in `summarize_feeds.py`

**Date:** 2026-06-03
**Status:** Approved design — ready for implementation plan
**Component:** `lazer_dq/summarize_feeds.py`

## Problem

Some publishers temporarily degrade (e.g. publisher 80 currently has price
jitter on its input). When building the `allowedPublisherIds` lists from a DQ
run, we want to **hold such a publisher out of the config-facing `allowed`
list "for now"** and let a more stable publisher take its place — without
permanently banning it and without losing the ability to inspect its metrics.

The existing exclusion mechanism (`{0}` ∪ publishers whose name ends in
`.Test`, parsed from `publishers.md`) is the wrong tool: it is permanent, it
lives in a shared file, and it removes the publisher from **both** the
`rankings` and `allowed` sheets.

## Goals

- Provide a **per-run, temporary** way to exclude one or more publisher IDs.
- The excluded publisher **stays visible in the `rankings` sheet** (so its
  r/s, n_obs, and hit% can still be inspected to confirm the issue).
- The excluded publisher **is removed from the `allowed` sheet** (the
  config-facing list).
- When removal drops a feed/session below the redundancy floor, the **existing
  top-up logic automatically backfills the next-best eligible publisher** — no
  new substitution logic.
- When the flag is not used, behavior is **byte-identical to today**.

## Non-Goals

- No explicit `80 → 25` mapping engine. Substitution is "auto next-best",
  delivered for free by the existing `--redundancy-floor` / top-up mechanism.
- No guaranteed 1:1 count preservation. Backfill is **floor-based**: a
  substitute is only pulled in when removal drops the feed below
  `--redundancy-floor`. Feeds still above the floor simply lose the excluded
  publisher.
- No permanent change to `publishers.md`.
- No change to downstream consumers (`apply_allowed_to_config.py` reads the
  `allowed` sheet, which will already be correct).

## Design

### Two-layer exclusion

The tool currently applies a single `excluded` set at the row level inside
`_build_per_feed_data`, **before both** `rank_top_n` (rankings) and
`apply_filter` (allowed). This design adds a **second, narrower** exclusion —
a per-run `manual_exclude: set[int]` — applied **only** on the path to the
`allowed` sheet:

| Layer                  | Source                               | Applies to rankings?   | Applies to allowed? |
| ---------------------- | ------------------------------------ | ---------------------- | ------------------- |
| `excluded` (existing)  | `{0}` ∪ `.Test` from `publishers.md` | Yes (removed)          | Yes (removed)       |
| `manual_exclude` (new) | `--exclude-publisher` CLI flag       | **No (stays visible)** | Yes (removed)       |

### CLI flag

```
--exclude-publisher 80 [55 ...]
```

- `nargs="+"`, `type=int`, default `None` (treated as empty set).
- Help text states explicitly: _publishers are excluded from the `allowed`
  sheet only; they remain visible in `rankings`._
- Accepts multiple IDs so several jittery publishers can be held out in one
  run.

### Integration point

Inside `_build_per_feed_data`, per `(feed_id, mode)`:

1. `kept` is computed as today (rows after the `{0}`/`.Test` exclusion).
2. **Rankings path — unchanged:**
   `ranked = rank_top_n(kept, n=top_n, excluded=set())`.
   The manually-excluded publisher is _not_ removed here, so it still appears
   in the `rankings` sheet.
3. **Allowed path — new filter step:**
   ```python
   filter_input = [
       r for r in kept
       if int(r["publisher_id"]) not in manual_exclude
   ]
   selected, n_passed, n_topup = apply_filter(filter_input, ...)
   ```
   The excluded publisher can no longer be a passer. If its removal drops the
   feed below `--redundancy-floor`, the existing top-up branch inside
   `apply_filter` backfills the next-best eligible publisher automatically. No
   new backfill code.

`apply_filter`, `rank_top_n`, `compute_aggregate`, and the sheet writers are
otherwise unchanged.

### Threading

- One new parameter `manual_exclude: set[int]` added to
  `_build_per_feed_data`.
- Built in `main()` from `args.exclude_publisher`
  (`set(args.exclude_publisher or [])`).

### Transparency

Two lightweight additions so a saved workbook is self-explaining (otherwise an
excluded publisher visibly tops `rankings` yet silently vanishes from
`allowed`):

1. **stdout summary line**, printed only when the flag is used, e.g.:
   `Manually excluded from allowed: [80] → applied to 23 feed/session cells`
   ("applied to N cells" = count of `(feed, mode)` candidate sets from which at
   least one manually-excluded publisher was actually removed).
2. **`allowed` sheet subtitle note**, written only when the flag is used, e.g.
   a cell under the title reading `Manually excluded from allowed: 80`.
   The `write_allowed_sheet` signature gains an optional
   `manual_exclude` argument (default empty) so existing callers/tests are
   unaffected; when non-empty it writes the note and shifts the existing
   header/data rows down by one.

> Note: this subtitle is a small, deliberate deviation from a strict
> "allowed-sheet-only, no annotation" reading — kept because it is nearly free
> and materially improves auditability. It can be dropped if undesired.

## Error handling & edge cases

- **Flag absent / empty** → `manual_exclude` is empty; every code path is
  byte-identical to current behavior, including the `allowed` sheet layout (no
  subtitle row, no row shift).
- **Excluded ID not present in a feed** → no-op for that feed; not counted in
  the "applied to N cells" total.
- **Excluding an ID already in `{0}`/`.Test`** → harmless; the publisher was
  already gone from both sheets. (Optionally noted, but no special handling
  required.)
- **Excluding so many publishers that a feed can no longer reach the floor** →
  same as today's "0 passed / all > ceiling" situation; the existing `allowed`
  sheet `(no data)` / Notes messaging applies. No new error.
- **Non-integer flag value** → `argparse type=int` rejects it with a standard
  usage error.

## Testing

Add cases under `lazer_dq/tests/`:

1. **Visible-but-excluded:** with `--exclude-publisher 80`, publisher 80
   appears in `rankings` output for a feed but is absent from that feed's
   `allowed` list.
2. **Below-floor backfill:** a feed where 80 was a passer and removal drops the
   passer count below the floor → a next-best substitute is backfilled (the
   `allowed` list contains the substitute, not 80, and length ≥ floor).
3. **Above-floor shrink:** a feed with passers comfortably above the floor →
   removing 80 just drops 80; no extra substitute is added.
4. **No-op parity:** without the flag, output is identical to current
   behavior (rankings + allowed sheets, including no subtitle row).
5. **Multiple IDs:** `--exclude-publisher 80 55` removes both from `allowed`,
   both still visible in `rankings`.

## Documentation

- Update `docs/summarize_feeds.md`: add `--exclude-publisher` to the Arguments
  table, a short usage example, and a note in the Ranking & Filtering section
  clarifying it affects the `allowed` sheet only.
- Update the Scripts-table example in `CLAUDE.md` only if warranted (likely not
  necessary).

## Out of scope / future

- A `publishers.md`-driven "temporarily degraded" flag for cross-tool reuse.
- Explicit per-feed substitution mappings.
