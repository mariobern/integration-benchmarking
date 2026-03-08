# Performance Optimization: Uptime Batching + Connection Reuse

**Date:** 2026-03-08
**Status:** Approved

## Problem

`feed_readiness.py` and `quick_benchmark.py` have degraded from ~1-2 minutes to ~3-4 minutes for a 10-feed run. The aggregate feed feature added 1-3 extra queries per feed, but the deeper issue is the uptime evaluation's N+1 query pattern and per-feed connection recreation.

## Root Causes

### 1. Uptime N+1 Pattern (biggest impact)

`uptime_core.py` runs 1 query per publisher per session. For 30 publishers × 4 sessions = 120 queries per feed. Should be 4 queries (1 per session, batching all publishers).

### 2. Connection Recreation (smaller but cumulative)

Each worker thread calls `get_clients(config)` per feed evaluation, creating fresh ClickHouse clients with full TLS handshake (~100-500ms overhead each time). Clients should be created once per worker and reused.

## Solution: Approach 2 (Batch Uptime + Connection Reuse)

### Uptime Batching

Rewrite `compute_uptime_1s_window()` and `compute_uptime_200ms_gap()` to accept a list of publisher IDs and return results for all of them in one query. Add `GROUP BY publisher_id` (1s-window) or `PARTITION BY publisher_id` in window function (gap-based).

**Before:** 120 queries/feed → **After:** 4 queries/feed

### Connection Reuse

Move `get_clients(config)` call outside the per-feed loop in worker threads. Create clients once per thread, reuse across all feed evaluations.

## Files Affected

| File                    | Change                                        |
| ----------------------- | --------------------------------------------- |
| `lib/uptime_core.py`    | Batch uptime queries by publisher             |
| `lib/config.py`         | No change needed (factory functions are fine) |
| `lib/readiness_core.py` | Move client creation outside per-feed loop    |
| `lib/benchmark_core.py` | Move client creation outside per-feed loop    |

## Backups

Original files saved to `backups/pre-perf-optimization/` before any changes.

## Expected Impact

- 50-70% speedup for `feed_readiness.py`
- 10-15% speedup for `quick_benchmark.py` (uptime not involved, just connection reuse)
- 10-feed full run: 3-4 min → ~1-1.5 min

## Risks

- Gap-based uptime method needs `PARTITION BY publisher_id` in window function to prevent data bleed between publishers
- Existing uptime tests must pass after changes
