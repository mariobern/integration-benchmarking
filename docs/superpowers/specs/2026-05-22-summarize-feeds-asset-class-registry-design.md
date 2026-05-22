# summarize_feeds asset-class registry — design

## Problem

`lazer_dq/summarize_feeds.py` is hard-coded to four US-equities modes
(`MODE_ORDER`, `MODE_TO_SESSION`, `DEFAULT_MAX_ROS`, `DEFAULT_MIN_HIT`). Running
it against a CSV of HK-equities feeds (mode `hk-equities` in column 3) returns
"Error: no feed produced any data" because the script only ever looks under
`dq_reports/<cluster>/us-equities*/...`. The `hk-equities` reports exist on
disk and are produced correctly by `evaluate_feeds_bulk`; only the summarizer
is blind to them.

## Goal

Make `summarize_feeds.py` work for `hk-equities` today, and make adding the
next asset class (e.g. `fx`, `metals`, `eu-equities`) a small data-only edit
rather than a refactor.

Non-goals:

- A single workbook spanning multiple asset classes (one run = one asset
  class, matching how `evaluate_feeds_bulk` is invoked).
- Auto-discovery of modes from CSV column 3.
- Reworking thresholds storage (they stay as flat CLI flags for now).

## Design

### Asset-class registry

Introduce a module-level `ASSET_CLASS_CONFIG` dict keyed by asset-class slug.
Each entry declares the modes used by that asset class, the
`mode → session-label` mapping for the `allowed` sheet, and the default
per-mode thresholds.

```python
ASSET_CLASS_CONFIG = {
    "us-equities": {
        "modes": ["us-equities", "us-equities-pre",
                  "us-equities-post", "us-equities-overnight"],
        "sessions": {
            "us-equities": "REGULAR",
            "us-equities-pre": "PRE_MARKET",
            "us-equities-post": "POST_MARKET",
            "us-equities-overnight": "OVER_NIGHT",
        },
        "default_max_ros": {
            "us-equities": 1.0, "us-equities-pre": 2.0,
            "us-equities-post": 2.0, "us-equities-overnight": 3.0,
        },
        "default_min_hit": {
            "us-equities": 80.0, "us-equities-pre": 50.0,
            "us-equities-post": 50.0, "us-equities-overnight": 25.0,
        },
    },
    "hk-equities": {
        "modes": ["hk-equities"],
        "sessions": {"hk-equities": "REGULAR"},
        "default_max_ros": {"hk-equities": 1.0},
        "default_min_hit": {"hk-equities": 80.0},
    },
}
```

Adding a new asset class = adding one dict entry. No code-path changes.

### CLI surface

Add one new flag:

```
--asset-class {us-equities,hk-equities}   (default: us-equities)
```

Choices come from `ASSET_CLASS_CONFIG.keys()`. Default `us-equities` preserves
backward compatibility with existing invocations and tests.

Threshold flags stay as they are for `us-equities` (regular/pre/post/overnight
variants). They are only consulted when `--asset-class us-equities`. For
other asset classes, the registry's `default_max_ros` / `default_min_hit`
values are used as-is in this iteration. (If per-mode threshold overrides
become a pain point for HK later, we add `--threshold mode:ros:hit` pairs
in a follow-up; YAGNI for now.)

### CSV validation

After parsing the CSV, walk column 3 and check every non-empty row's mode
against the selected asset class's `modes` list. If any row's mode is not in
that list, exit with a clear error:

```
Error: CSV contains mode 'us-equities' but --asset-class is 'hk-equities'.
       Mismatched rows: 884 (us-equities), 885 (us-equities). [...]
```

This kills the silent-empty-results failure mode that produced the original
bug report.

Rows whose mode IS in the list are accepted; the existing column-1 numeric
parsing is unchanged. Rows with empty column 3 are accepted (back-compat —
some older CSVs only have a feed_id column).

### Refactor

`MODE_ORDER` and `MODE_TO_SESSION` become local variables inside `main()`
sourced from `ASSET_CLASS_CONFIG[args.asset_class]`. Functions that currently
close over the module-level constants (`write_rankings_sheet`,
`write_allowed_sheet`, `_build_per_feed_data`, `compute_aggregate`) take the
mode list and session map as parameters instead.

The 24-column rankings layout becomes parametric on `len(modes)`:

- 1 rank column + N × 5-col mode blocks + (N-1) × 1-col spacers
  = `1 + 5N + (N-1) = 6N` columns total.
- N=4 (us-equities) → 24 cols (matches today).
- N=1 (hk-equities) → 6 cols.

`mode_starts` is computed from the mode list rather than hard-coded.

### Tests

- Keep all existing `test_summarize_feeds.py` cases green (default behavior
  unchanged for `us-equities`).
- Add cases for:
  - `--asset-class hk-equities` end-to-end on a small fixture (rankings + allowed sheets render with one mode block).
  - Mismatched CSV mode → exits with the validation error and a non-zero code.
  - Registry-driven `mode_starts` math: N=1 → 6 cols, N=4 → 24 cols.

### Out-of-scope (documented as future work)

- `fx` / `metals` / `eu-equities` registrations — trivial to add when needed.
- Per-asset-class threshold CLI flags.
- Multi-asset-class workbooks.
- Auto-discovery of modes from CSV column 3.

## Risks

- **Layout regressions on us-equities workbooks.** Mitigation: snapshot test
  on column counts and cell positions for the existing 4-mode layout.
- **Tests that import `MODE_ORDER` / `MODE_TO_SESSION` directly.** A grep
  confirms they are only used inside `summarize_feeds.py`; the constants can
  remain as module-level aliases pointing at the `us-equities` registry entry
  to keep any external importer working. (Will verify during implementation.)
