# Per-Session Publisher Consistency & Classifications

**Date:** 2026-02-20
**Status:** Approved

## Problem

`feed_readiness.py --detailed` outputs PUBLISHER CONSISTENCY and PUBLISHER CLASSIFICATIONS sections, but only for regular hours. When `--extended-hours` or `--overnight` flags are active, per-session (premarket, afterhours, overnight) consistency and classification data is missing from the output, even though per-session benchmark and uptime data already exists on `PublisherReadinessDetail`.

## Design Decisions

| Decision | Choice |
|----------|--------|
| Session pass logic | Both benchmark AND uptime must pass (mirrors regular hours) |
| CSV layout | Separate consistency + classification section pair per session |
| Publisher inclusion | Only publishers with session data (uptime > 0%) appear in that session's table |
| Approach | Generalize existing `compute_publisher_consistency` with a status extractor parameter |

## Changes

### 1. Generalize `compute_publisher_consistency`

Add a `status_extractor` parameter — a callable `(PublisherReadinessDetail) -> str | None`:

- Returns `"PASS"`, `"FAIL"`, `"ERROR"`, or `None` (no data → exclude)
- Default extractor preserves existing regular-hours logic
- `None` return causes the publisher-date pair to be skipped entirely

```python
def compute_publisher_consistency(
    results: list[FeedReadinessResult],
    status_extractor: Callable[[PublisherReadinessDetail], str | None] | None = None,
) -> dict:
```

### 2. Session status extractors

For each session (premarket, afterhours, overnight):

```python
def premarket_status(detail: PublisherReadinessDetail) -> str | None:
    # No data → exclude from table
    if detail.premarket_uptime_pct is None or detail.premarket_uptime_pct == 0.0:
        return None
    bp = detail.premarket_benchmark_passes
    up = detail.premarket_uptime_passes
    if bp is None:
        return "ERROR"
    return "PASS" if (bp and up) else "FAIL"
```

Analogous functions for afterhours and overnight, using respective fields.

### 3. Parameterize `write_publisher_consistency_csv`

Add `session_prefix` parameter to control section headers and classification row labels:

- `""` (default) → `PUBLISHER CONSISTENCY` / `regular_always_passing`
- `"PREMARKET "` → `PREMARKET PUBLISHER CONSISTENCY` / `premarket_always_passing`
- `"AFTERHOURS "` → `AFTERHOURS PUBLISHER CONSISTENCY` / `afterhours_always_passing`
- `"OVERNIGHT "` → `OVERNIGHT PUBLISHER CONSISTENCY` / `overnight_always_passing`

### 4. Calling logic

After writing regular-hours consistency (existing behavior, unchanged):

```python
if extended_hours:
    for session_name, extractor in [("PREMARKET", premarket_status), ("AFTERHOURS", afterhours_status)]:
        session_consistency = compute_publisher_consistency(results, extractor)
        if len(session_consistency["dates"]) > 1 and session_consistency["rows"]:
            write_publisher_consistency_csv(writer, session_consistency, session_prefix=f"{session_name} ")

if overnight:
    session_consistency = compute_publisher_consistency(results, overnight_status)
    if len(session_consistency["dates"]) > 1 and session_consistency["rows"]:
        write_publisher_consistency_csv(writer, session_consistency, session_prefix="OVERNIGHT ")
```

Same pattern for console output via `print_publisher_consistency`.

### 5. Console output

`print_publisher_consistency` gets the same `session_prefix` parameter. Called once per active session after the regular-hours print.

## Output Format

When `--extended-hours --overnight --detailed` with multiple dates:

```csv
PUBLISHER CONSISTENCY
publisher_id,dates_seen,pass_dates,fail_dates,pass_rate,results
19,3,3,0,100.00%,2026-02-17:PASS;2026-02-18:PASS;2026-02-19:PASS
...

PUBLISHER CLASSIFICATIONS
regular_always_passing,19;71
regular_always_failing,20;40;41
regular_intermittent,22;65;43;44;28;29;32;72;73

PREMARKET PUBLISHER CONSISTENCY
publisher_id,dates_seen,pass_dates,fail_dates,pass_rate,results
65,3,2,1,66.67%,2026-02-17:PASS;2026-02-18:FAIL;2026-02-19:PASS
...

PREMARKET PUBLISHER CLASSIFICATIONS
premarket_always_passing,65
premarket_always_failing,20;32
premarket_intermittent,19;22

AFTERHOURS PUBLISHER CONSISTENCY
publisher_id,dates_seen,pass_dates,fail_dates,pass_rate,results
...

AFTERHOURS PUBLISHER CLASSIFICATIONS
afterhours_always_passing,...
afterhours_always_failing,...
afterhours_intermittent,...

OVERNIGHT PUBLISHER CONSISTENCY
publisher_id,dates_seen,pass_dates,fail_dates,pass_rate,results
...

OVERNIGHT PUBLISHER CLASSIFICATIONS
overnight_always_passing,...
overnight_always_failing,...
overnight_intermittent,...
```

## What Does NOT Change

- `PublisherReadinessDetail` dataclass (session fields already exist)
- `FeedReadinessResult` dataclass
- Benchmark/uptime computation logic
- Regular-hours behavior (fully backward compatible)
- Feed-level CSV rows
- PUBLISHER DETAIL section

## Visibility Rules

| Section | Appears when |
|---------|-------------|
| Regular consistency + classifications | `--detailed` + multi-date (existing) |
| Premarket consistency + classifications | `--detailed` + multi-date + `--extended-hours` |
| Afterhours consistency + classifications | `--detailed` + multi-date + `--extended-hours` |
| Overnight consistency + classifications | `--detailed` + multi-date + `--overnight` |
