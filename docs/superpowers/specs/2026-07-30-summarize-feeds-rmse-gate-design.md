# summarize_feeds.py: raw-rmse passer gate

## Problem

`summarize_feeds.py` ranks and filters publishers using `rmse_over_spread`
exclusively: `rank_top_n()` sorts the `rankings` sheet by it, and
`apply_filter()` gates `allowed`-sheet passers by it (plus `hit_rate` and
`n_observations`). `rmse_over_spread` normalizes raw RMSE by spread, which the
user has found is not accurate enough on its own — some publishers pass on
`rmse_over_spread` despite a raw RMSE the user considers too high. `stats.csv`
already carries a raw `rmse` column (read today only for display in the
`rankings` sheet), so no new data source is needed — this is purely a new
filtering criterion.

## Goal

Add an optional raw-`rmse` ceiling that, when set, a publisher must also clear
to count as a passer on the `allowed` sheet.

## Non-goals

- Changing `rankings`-sheet sort order (stays ascending by `rmse_over_spread`).
- A universal/default rmse threshold — raw RMSE scale varies too much by
  instrument price to guess a sane default.
- Gating top-ups by rmse (top-ups stay gated by `rmse_over_spread`'s ceiling
  multiplier only, as today).
- Extending per-mode CLI overrides to hk/jp/kr/in-equities — those asset
  classes have no CLI override for `rmse_over_spread` either today (a known,
  pre-existing gap); this change doesn't address it.

## Design

### Filtering semantics

`apply_filter()` gains a new optional parameter `max_rmse: float | None =
None`. Passer criteria become:

```
ros <= max_ros AND hit >= min_hit AND n_obs >= min_obs
    AND (max_rmse is None OR rmse <= max_rmse)
```

This mirrors how `hit_rate` already behaves: it gates **passers only**.
Top-ups (used to fill the redundancy floor when passers < `--redundancy-floor`)
remain gated only by `n_observations` and the existing `rmse_over_spread`
ceiling multiplier — unchanged. A publisher that fails only the new rmse gate
is simply not a passer; it can still be pulled in as a top-up if it otherwise
qualifies, exactly like a publisher that fails only the hit-rate gate today.

`rmse` is parsed from `r["rmse"]` — already present in every `stats.csv` row.
It is only parsed/checked when `max_rmse is not None`, to avoid disturbing
runs that don't use the flag. If `max_rmse` is set and a row's `rmse` field is
missing or non-numeric, that row is treated as failing the gate (added to
`non_passers`, not skipped) — consistent with malformed rows for other
optional-ish fields not silently vanishing from consideration for top-up.

### CLI surface

Four new optional flags, `us-equities` only, naming mirrored from the existing
`--max-rmse-over-spread-*` flags:

- `--max-rmse-regular`
- `--max-rmse-pre`
- `--max-rmse-post`
- `--max-rmse-overnight`

All `type=float`, `default=None` (disabled). Existing invocations are
unaffected unless one of these is explicitly passed.

For asset classes other than `us-equities` (hk/jp/kr/in-equities, single-mode),
`max_rmse_map` is built as `{mode: None for mode in modes}` — the gate is
simply unavailable there, matching the existing asymmetry where those asset
classes also have no CLI override for `rmse_over_spread`/`hit_rate`.

### Threading through

- `main()`: build `max_rmse_map` alongside the existing `max_ros_map` /
  `min_hit_map` construction (same `us-equities` vs. else branch).
- `_build_per_feed_data(...)`: add a `max_rmse_map` parameter, pass
  `max_rmse_map[mode]` into the `apply_filter()` call per mode.
- No changes to `rank_top_n()`, `write_rankings_sheet()`,
  `write_allowed_sheet()`, or the Notes-column top-up messaging — the
  passed/topup counting logic is already metric-agnostic.

## Testing

Extend `lazer_dq/tests/test_summarize_feeds.py` coverage for `apply_filter`:

- `max_rmse=None` (default): behavior identical to today (regression guard).
- `max_rmse` set, a passer-by-ros-and-hit-rate publisher has `rmse` above the
  ceiling: it is excluded from passers; if this drops the feed below
  `--redundancy-floor`, it may still appear as a top-up.
- `max_rmse` set, all other thresholds clear and `rmse` clears the ceiling too:
  passer as before.
- Malformed/missing `rmse` field with `max_rmse` set: row treated as
  non-passer (not silently dropped), still eligible for top-up if it
  otherwise qualifies.

## Documentation

Update `docs/summarize_feeds.md`:

- Arguments table: add the 4 new flags, default `(none — disabled)`.
- "Ranking & Filtering" section: extend the passer bullet to mention the
  optional rmse gate and that, like `hit_rate`, it doesn't constrain top-ups.
