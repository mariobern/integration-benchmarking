# lazer_dq parity with research PR #287 — JP/KR/IN equities

**Date:** 2026-07-10
**Source:** pyth-network/research PR #287 — "[feat] benchmarking jp, kr and in equities" (merge commit `0a9b7932`, head `benchmarking-jp-and-kr`)
**Goal:** Bring `lazer_dq` to full parity with PR #287 so `evaluate_feeds_bulk.py` and the engine it drives support `jp-equities`, `kr-equities`, and `in-equities`.

## Background

`lazer_dq` is the integration-repo port of the research repo's papermill-notebook DQ flow. Parity is tracked per research PR (previous pass: PRs #285/#286). PR #287 adds three new foreign-equity market modes.

Research PR #287 touches three files:

- `evaluate_feeds.py` + `evaluate_feeds_against_benchmark.sh` — three new local-exchange session windows.
- `publisher_benchmark_eval.ipynb` — adds the three modes to the shared equities benchmark branch (reusing `datascope_global_equities_benchmark_data`) **and** adds three new qualifier filters to the shared equities filter.

Mapping research files → `lazer_dq`:

| Research file                                                | lazer_dq file                          |
| ------------------------------------------------------------ | -------------------------------------- |
| `evaluate_feeds.py` / `.sh` (session windows)                | `lazer_dq/evaluate_feeds_bulk.py`      |
| `publisher_benchmark_eval.ipynb` (benchmark query + filters) | `lazer_dq/evaluate_feed_standalone.py` |

`summarize_feeds.py` is integration-repo-only (not in #287) and is extended here so the downstream summary flow works for the new markets, mirroring the earlier hk-equities addition.

## New market windows (from #287)

| Mode          | Local window      | Timezone     | DST  |
| ------------- | ----------------- | ------------ | ---- |
| `jp-equities` | 09:00:00–10:00:00 | Asia/Tokyo   | none |
| `kr-equities` | 09:00:00–10:00:00 | Asia/Seoul   | none |
| `in-equities` | 09:15:00–10:15:00 | Asia/Kolkata | none |

These are the local first-hour windows converted to UTC. None of the three timezones observe DST, so the UTC offset is fixed year-round (JST +9, KST +9, IST +5:30).

## Changes

### 1. `lazer_dq/evaluate_feeds_bulk.py` — session windows

In `compute_times_from_mode`, add three branches following the existing `hk-equities` pattern (which uses `_local_to_utc(start, tz)`):

```python
if mode_lower == "hk-equities":
    return (_local_to_utc("09:30:00", "Asia/Hong_Kong"),
            _local_to_utc("10:30:00", "Asia/Hong_Kong"))
if mode_lower == "jp-equities":
    return (_local_to_utc("09:00:00", "Asia/Tokyo"),
            _local_to_utc("10:00:00", "Asia/Tokyo"))
if mode_lower == "kr-equities":
    return (_local_to_utc("09:00:00", "Asia/Seoul"),
            _local_to_utc("10:00:00", "Asia/Seoul"))
if mode_lower == "in-equities":
    return (_local_to_utc("09:15:00", "Asia/Kolkata"),
            _local_to_utc("10:15:00", "Asia/Kolkata"))
```

### 2. `lazer_dq/evaluate_feed_standalone.py` — benchmark query + filters

- Add `"jp-equities"`, `"kr-equities"`, `"in-equities"` to the equities benchmark-branch tuple (currently `("us-equities", "us-equities-pre", "us-equities-post", "hk-equities")`) so they reuse `datascope_global_equities_benchmark_data`.
- Add three new qualifier filters to that shared equities filter, matching #287. Per the "true parity" decision these apply to **all** equities modes (existing us/hk included):
  ```sql
  AND qualifiers NOT LIKE '%141[IRGCOND]%'
  AND qualifiers NOT LIKE '%2835[IRGCOND]%'
  AND qualifiers NOT LIKE '%4575[IRGCOND]%'
  ```
  Placed alongside the existing `%102[ODDSALCOND]%` / `%101[IRGSALCOND]%` entries, before the `PD_` regex clause (same ordering as the research notebook).
- Update the `--mode` argparse help string to list `jp-equities`, `kr-equities`, `in-equities`.

### 3. `lazer_dq/summarize_feeds.py` — asset-class config

Add three `ASSET_CLASS_CONFIG` entries, each mirroring the `hk-equities` entry (single mode, `REGULAR` session, 6-column layout):

```python
"jp-equities": {
    "modes": ["jp-equities"],
    "sessions": {"jp-equities": "REGULAR"},
    "default_max_ros": {"jp-equities": 1.0},
    "default_min_hit": {"jp-equities": 80.0},
},
# kr-equities, in-equities identical shape
```

Thresholds mirror hk-equities (confirmed acceptable). Each asset class is selected via `--asset-class jp-equities|kr-equities|in-equities`.

### 4. Tests

- `lazer_dq/tests/test_evaluate_feeds_bulk.py`: add `compute_times_from_mode` cases for jp/kr/in. Because these timezones have no DST, one fixed-offset assertion per market suffices (assert summer and winter dates yield identical UTC windows); include a case-insensitivity check mirroring the hk test.
  - JST/KST (+9): `09:00→00:00`, `10:00→01:00` UTC.
  - IST (+5:30): `09:15→03:45`, `10:15→04:45` UTC.
- `lazer_dq/tests/test_benchmark_ric_queries.py`: add jp/kr/in rows to the parametrized table-resolution test, all resolving to `datascope_global_equities_benchmark_data`.
- Add an assertion (extend an existing equities query test) that the three new qualifier codes appear in the generated equities benchmark query.

### 5. Docs — `CLAUDE.md`

- Extend the "Equities qualifier filter" gotcha: add `141[IRGCOND]`, `2835[IRGCOND]`, `4575[IRGCOND]`; note the equities benchmark branch now also covers `jp-equities`, `kr-equities`, `in-equities`.
- Add a gotcha (parallel to the existing hk-equities one) documenting the jp/kr/in local windows + timezones (no DST) used in `evaluate_feeds_bulk`.
- Update the `summarize_feeds` asset-class notes to mention the three new single-mode asset classes.

## Non-changes (deliberate)

- `benchmark_identifiers.session_for_mode` is **not** edited — unknown modes already default to `REGULAR`, which is correct for RIC resolution (identical to how hk-equities resolves).
- No new benchmark table; all three modes reuse `datascope_global_equities_benchmark_data`.

## Out of scope

- Overnight / pre / post sessions for these markets (not in #287).
- RIC-mapping or config-tooling changes.

## Definition of done

- [ ] `compute_times_from_mode` returns correct UTC windows for jp/kr/in.
- [ ] Standalone engine routes jp/kr/in to the global-equities table with the updated filter set.
- [ ] Three new qualifier codes present in the equities benchmark query for all equities modes.
- [ ] `summarize_feeds` accepts `--asset-class jp-equities|kr-equities|in-equities`.
- [ ] New tests pass; existing tests still green.
- [ ] CLAUDE.md gotchas updated.
- [ ] `pre-commit run --files <changed files>` clean.
