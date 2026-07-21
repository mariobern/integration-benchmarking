# Document jp/kr/in-equities in summarize_feeds.md

Last updated: 2026-07-16

## Goal

`docs/summarize_feeds.md`'s "Asset Classes & Modes" section documents only
`us-equities` and `hk-equities`, even though `jp-equities`, `kr-equities`,
and `in-equities` are already fully implemented in `ASSET_CLASS_CONFIG`
(`lazer_dq/summarize_feeds.py`) and already documented as available
`--asset-class` values in `CLAUDE.md`. Close that gap so the per-script doc
matches the code and `CLAUDE.md`.

## Background

Investigation confirmed:

- `ASSET_CLASS_CONFIG` in `lazer_dq/summarize_feeds.py` has working entries
  for `hk-equities`, `jp-equities`, `kr-equities`, and `in-equities` — each
  1 mode, `REGULAR` session, `default_max_ros` 1.0, `default_min_hit` 80.0.
- `CLAUDE.md` already lists all four foreign single-mode equity classes
  correctly in its `summarize_feeds` asset class, `jp-equities /
kr-equities / in-equities modes`, and `Equities qualifier filter`
  bullets. No `CLAUDE.md` changes are needed.
- `docs/summarize_feeds.md`'s "Asset Classes & Modes" section only shows a
  table for `hk-equities`; `jp-equities`/`kr-equities`/`in-equities` are
  missing entirely.

A related idea — adding a new `sh-equities` mode covering `Equity.CN.*`
feeds (Shanghai + Shenzhen, already unified under one exchange config) —
was raised during scoping but explicitly deferred: that engine mode
doesn't exist yet in `evaluate_feed_standalone.py` /
`evaluate_feeds_bulk.py`, so no code or docs work for it is in scope here.

## Scope

- In scope: `docs/summarize_feeds.md` only.
- Out of scope: any code change (`summarize_feeds.py`,
  `evaluate_feed_standalone.py`, `evaluate_feeds_bulk.py`,
  `qualify_candidates.py`); `CLAUDE.md` (already correct); any mention of
  `sh-equities`/CN equities.

## Change

In the "Asset Classes & Modes" section of `docs/summarize_feeds.md`:

1. Replace the standalone `hk-equities` table with one consolidated table
   covering all four single-mode foreign-equity classes, since they share
   an identical shape (1 mode, `REGULAR` session, 6-column rankings
   layout, same default thresholds):

   ```
   **Single-mode foreign equity classes** — 1 mode each, 6-column rankings layout, REGULAR session:

   | Asset Class   | Mode          | Session |
   | ------------- | ------------- | ------- |
   | `hk-equities` | `hk-equities` | REGULAR |
   | `jp-equities` | `jp-equities` | REGULAR |
   | `kr-equities` | `kr-equities` | REGULAR |
   | `in-equities` | `in-equities` | REGULAR |
   ```

2. Update the trailing "Notes" bullet — currently states thresholds only
   for `hk-equities` REGULAR — to state that all four classes share the
   same registry defaults (max `rmse_over_spread` 1.0, min `hit_rate`
   80%).

3. Update the usage-example comment above the `--asset-class hk-equities`
   example (currently `# HK equities (1 mode); see Asset Classes & Modes
below`) to note it applies to HK/JP/KR/IN equities, so the single
   example is clearly read as representative of all four rather than
   HK-specific.

## Definition of done

- [ ] "Asset Classes & Modes" section lists `hk-equities`, `jp-equities`,
      `kr-equities`, and `in-equities` in one consolidated table.
- [ ] Notes bullet reflects thresholds for all four classes, not just
      `hk-equities`.
- [ ] Usage-example comment reads as representative of all four classes.
- [ ] No code files touched; no mention of `sh-equities` added.
- [ ] `pre-commit run --files docs/summarize_feeds.md` passes.
