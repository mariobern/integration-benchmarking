# summarize_feeds redundancy floor — design

## Problem

In the `allowed` sheet of `summarize_feeds.py` output (e.g.
`dq_summary_lazer-prod_2026-05-20.xlsx`), many feed/session rows promote too few
publishers for safe redundancy. Two distinct code paths produce this:

1. **Fallback (0 passed).** When zero publishers clear the per-mode thresholds,
   `apply_filter` (`lazer_dq/summarize_feeds.py`) returns the top `fallback_top`
   (default **3**) by `rmse_over_spread`, flagged "FALLBACK: 0 passed filter".
   Example: feed 997 → `[35, 42, 45]`, feed 889 → `[41, 69, 71]`.
2. **Thin passers (1–2 passed).** When some publishers pass, `apply_filter`
   returns _all_ passers with no floor. Example: feed 885 → `[69]` (one
   publisher), feed 894 → `[41]` (one publisher). Bumping the fallback number
   does nothing for these — they never enter the fallback branch.

The goal is to promote **more publishers for redundancy while still maintaining
feed quality through the metrics**. A naive "fallback 3 → 5" bump fails on both
counts: it ignores the thin-passer feeds, and where it does fire it promotes
_more_ sub-threshold publishers (the fallback exists precisely because nothing
passed).

## Goal

Guarantee a minimum number of publishers per feed/session — a **redundancy
floor** — by preferring quality passers and topping up with the next-best
near-misses, bounded by a quality ceiling so genuinely bad publishers are never
promoted. Make the distinction between vetted passers and redundancy fillers
visible to the human reviewer who pastes the array into `after.json`.

Non-goals:

- Relaxing the per-mode pass thresholds themselves (`max_rmse_over_spread`,
  `min_hit_rate`) — those stay as-is; quality is enforced, not loosened.
- Changing the `rankings` sheet (still top-N by `rmse_over_spread`).
- Changing the aggregate-union logic beyond what the per-session arrays feed it.

## Design

### Redundancy floor (minimum, never maximum)

Let `N` be the floor (default **5**) and `ceiling = ceiling_mult × max_ros`
(default `ceiling_mult = 2.0`). For each feed/mode, given the
exclusion-filtered, parseable stat rows:

1. **Passers** = rows meeting all three thresholds (`r/s ≤ max_ros`,
   `hit ≥ min_hit`, `n_obs ≥ min_obs`), sorted ascending by `rmse_over_spread`.
2. If `len(passers) ≥ N` → return **all** passers. Healthy feeds with 8 passers
   still return 8; we never drop a vetted publisher. The floor is a minimum.
3. If `len(passers) < N` → **top up** with non-passers, ranked ascending by
   `rmse_over_spread`, that satisfy **both**:

   - `n_obs ≥ min_obs` (the observation floor always applies to top-ups), and
   - `r/s ≤ ceiling`.

   Take only `N − len(passers)` of them.

4. If still `< N` after exhausting eligible top-ups → return what we have. A
   publisher with `r/s > ceiling` is **never** promoted, even if the feed ends
   up below `N`.

`hit_rate` does **not** gate top-ups. A near-miss that fails only on hit-rate
but has acceptable `r/s` (≤ ceiling) and enough observations is eligible. The
`r/s` ceiling is the single quality proxy for top-ups, consistent with every
selection in this tool being ranked by `r/s`.

### Outcomes (per feed/mode)

- `n_passed ≥ N`: all passers, no top-ups. Healthy.
- `0 < n_passed < N`: passers + top-ups to reach `N` (or fewer if ceiling/n_obs
  exhaust eligibles).
- `n_passed = 0`, eligible top-ups exist: up to `N` top-ups (this is the old
  fallback case, now ceiling-bounded).
- `n_passed = 0`, **no** row under the ceiling: empty selection — a _new_
  outcome distinct from "no data". Surfaced explicitly, not hidden.

### Code changes — `lazer_dq/summarize_feeds.py`

**`apply_filter`** — change signature and return:

```python
def apply_filter(stats, max_ros, min_hit, min_obs, floor, ceiling_mult):
    """Return (selected, n_passed, n_topup).

    selected   : passers + top-ups, sorted ascending by rmse_over_spread,
                 length <= floor unless n_passed already exceeds floor.
    n_passed   : count meeting all three thresholds.
    n_topup    : count of below-threshold fillers added to reach the floor.
    """
```

- Passers ≥ floor → `(passers, len(passers), 0)`.
- Else compute `ceiling = ceiling_mult * max_ros`; eligible top-ups =
  non-passers with `n_obs >= min_obs and r/s <= ceiling`, sorted by `r/s`; take
  `floor - len(passers)`; return `(passers + topups, len(passers), len(topups))`.
- Empty input → `([], 0, 0)`.

**`_build_per_feed_data`** — store `n_passed` and `n_topup` per mode instead of
`is_fallback`; replace the `fallback_count` tally with `topup_rows`
(rows where `n_topup > 0`) and `zero_passer_rows` (rows where `n_passed == 0`
and the row has data).

**`write_allowed_sheet`** — Notes column and fill driven by counts:

| Situation                          | `allowedPublisherIds` | Notes                        | Fill   |
| ---------------------------------- | --------------------- | ---------------------------- | ------ |
| all passers (`n_topup = 0`, `>0`)  | JSON array            | (blank)                      | none   |
| passers + top-ups (`n_passed > 0`) | JSON array            | `2 passed + 3 top-up (≤2×)`  | yellow |
| 0 passed, top-ups present          | JSON array            | `0 passed + 5 top-up (≤2×)`  | yellow |
| 0 passed, none under ceiling       | `(no data)`           | `0 passed, all > 2× ceiling` | gray   |
| mode missing                       | `(no data)`           | `mode missing for <date>`    | gray   |

The JSON array stays clean and paste-ready, sorted by `publisher_id` (unchanged
ordering). The "≤2×" text reflects the actual `ceiling_mult`. The passer/top-up
split lives only in Notes, so a reviewer sees the mix at a glance without the
JSON being polluted.

**`main`** — retire `--fallback-top` and `DEFAULT_FALLBACK_TOP`; add:

- `--redundancy-floor` (type int, default `5`, replaces `DEFAULT_FALLBACK_TOP`
  via new `DEFAULT_REDUNDANCY_FLOOR = 5`).
- `--topup-ceiling-mult` (type float, default `2.0`,
  `DEFAULT_TOPUP_CEILING_MULT = 2.0`).

Update the closing summary lines (e.g. `Rows using top-ups: X`,
`Rows with 0 passers: Y`) in place of `Fallbacks triggered: N cells`.

**Unchanged**: `rank_top_n`, `write_rankings_sheet`, `compute_aggregate`,
`load_stats`, `discover_feeds`, exclusion handling, the asset-class registry.

### CLI breaking change

`--fallback-top` is removed (not aliased). This is an internal workbook
generator; the flag is replaced by `--redundancy-floor`. Any caller passing
`--fallback-top` will get an argparse error and should switch to
`--redundancy-floor`.

## Testing

TDD against `lazer_dq/tests/`:

- passers `≥ floor` → returns all passers, `n_topup = 0`.
- `0 < passers < floor` → tops up to exactly `floor`, correct `n_passed` /
  `n_topup`.
- top-up ceiling excludes a publisher with `r/s > ceiling` even when the feed
  stays below `floor`.
- `n_obs` floor excludes a thin near-miss from top-ups.
- `0` passers + eligible near-misses → up to `floor` top-ups, `n_passed = 0`.
- `0` passers + every row over the ceiling → empty selection (new outcome).
- empty input → `([], 0, 0)`.
- Notes-string formatting for each row situation in the table above.

## Example (floor 5, ceiling 2×)

```
feed 885: passers=[69]            -> [69, +4 next-best ≤2× w/ enough obs]   "1 passed + 4 top-up (≤2×)"
feed 894: passers=[41]            -> [41, +4 next-best]                     "1 passed + 4 top-up (≤2×)"
feed 997: passers=[]              -> top-5 within 2× ceiling                "0 passed + 5 top-up (≤2×)"
feed XXX: passers=[a..h] (8)      -> [a..h] all 8                           (blank, healthy)
feed YYY: passers=[], all > 2×    -> (no data)                             "0 passed, all > 2× ceiling"
```
