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

### Connection Reuse via `ThreadLocalClients`

Extracted a shared `ThreadLocalClients` class in `lib/config.py` that replaces duplicated `threading.local()` patterns across 3 files. Key properties:

- **Thread-local caching**: creates one client (or client pair) per worker thread, reuses across all feed evaluations on that thread
- **Thread-safe tracking**: all created clients are tracked in a lock-protected list
- **Explicit cleanup**: context manager calls `client.close()` on all tracked clients when the `ThreadPoolExecutor` `with` block exits
- **Two modes**: `get_clients()` for lazer+analytics (benchmark/readiness), `get_lazer_client()` for lazer-only (uptime) via `lazer_only=True`

## Files Affected

| File                    | Change                                                     |
| ----------------------- | ---------------------------------------------------------- |
| `lib/uptime_core.py`    | Batch uptime queries by publisher                          |
| `lib/config.py`         | Add `ThreadLocalClients` class for connection pool+cleanup |
| `lib/readiness_core.py` | Use `ThreadLocalClients` context manager                   |
| `lib/benchmark_core.py` | Use `ThreadLocalClients` context manager                   |

## Backups

Original files saved to `backups/pre-perf-optimization/` before any changes.

## Expected Impact

- 50-70% speedup for `feed_readiness.py`
- 10-15% speedup for `quick_benchmark.py` (uptime not involved, just connection reuse)
- 10-feed full run: 3-4 min → ~1-1.5 min

## Risks

- Gap-based uptime method needs `PARTITION BY publisher_id` in window function to prevent data bleed between publishers
- Existing uptime tests must pass after changes
