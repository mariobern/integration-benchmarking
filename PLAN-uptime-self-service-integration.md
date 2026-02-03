# Implementation Plan: Uptime + Benchmark + Feeds Integration (Low-Risk Path)

## Goal

Extend the self-service portal to include publisher uptime metrics alongside existing
benchmark results, while keeping the first iteration low-risk by aligning with the
current batch pipeline and data shapes.

Scope includes `publisher_feeds.py` as the discovery source of feeds, and uses the
same daily batch process as `publisher_benchmark.py`.

---

## Summary of Approach (Low-Risk)

1) **Daily batch only** (no on-demand uptime initially).
2) **Compute per-day, session-aware uptime** per (publisher_id, feed_id, session) using ClickHouse data.
3) **Store uptime results in Postgres** in a separate table keyed by date/publisher/feed/session.
4) **Join in API/UI** to show uptime next to benchmark metrics.
5) **Keep logic modular** so we can extend to holiday calendars and symbol-specific sessions later.

---

## Existing Building Blocks

- `publisher_feeds.py`: discovers a publisher's feeds from ClickHouse.
- `publisher_benchmark.py`: computes benchmark metrics for a publisher’s feeds.
- Portal batch runner: `portal/batch/daily_benchmark_runner.py`
- Portal schema: `portal/db/schema.sql`
- Portal API: `portal/api/routers/benchmarks.py`
- Portal results parser: `portal/batch/result_parser.py`

---

## Proposed Data Model

Add a new table for per-day, session-aware uptime for each publisher/feed.

File: `portal/db/schema.sql` (new table)

```sql
CREATE TABLE publisher_feed_daily_uptime (
    id SERIAL PRIMARY KEY,
    publisher_id INTEGER NOT NULL,
    feed_id INTEGER NOT NULL,
    uptime_date DATE NOT NULL,
    asset_class VARCHAR(50),
    session VARCHAR(32) NOT NULL,

    -- Uptime metrics
    uptime_pct DECIMAL(6, 4) NOT NULL,        -- e.g., 99.95
    downtime_ms BIGINT NOT NULL,
    period_length_ms BIGINT NOT NULL,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(publisher_id, feed_id, uptime_date, session)
);

CREATE INDEX idx_uptime_publisher_date ON publisher_feed_daily_uptime(publisher_id, uptime_date DESC);
CREATE INDEX idx_uptime_feed_date ON publisher_feed_daily_uptime(feed_id, uptime_date DESC);
CREATE INDEX idx_uptime_session_date ON publisher_feed_daily_uptime(session, uptime_date DESC);
```

Optionally, a daily aggregate table per publisher:

```sql
CREATE TABLE publisher_daily_uptime_summary (
    id SERIAL PRIMARY KEY,
    publisher_id INTEGER NOT NULL,
    uptime_date DATE NOT NULL,

    total_feeds INTEGER NOT NULL,
    mean_uptime_pct DECIMAL(6, 4),
    median_uptime_pct DECIMAL(6, 4),
    p90_uptime_pct DECIMAL(6, 4),

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(publisher_id, uptime_date)
);
```

---

## Data Sources / Query Strategy

### Feed discovery
Use `publisher_feeds.py` logic or shared helper to determine feed list for a publisher.

### Uptime query
Leverage existing uptime calculation logic from:
- `research/pythresearch/lazer/reliability/uptime.py`
- `research/pythresearch/data/lazer_db.py`

Low-risk approach: compute uptime per feed from ClickHouse using a daily window and session rules per asset class:

```
start = {date} 00:00:00 UTC
end   = {date+1} 00:00:00 UTC
```

Use a "fast" uptime calculation mode (window-based or MV) to limit load.
Start with time-of-day sessions (no holiday calendars); add holidays later.

---

## Batch Pipeline Integration (Low-Risk)

### 1) Add a new batch step
In `portal/batch/daily_benchmark_runner.py`, after running `publisher_benchmark.py`:

- Load publisher feeds (same list used for benchmarking).
- Compute daily uptime per feed from ClickHouse.
- Persist to Postgres `publisher_feed_daily_uptime`.

### 2) Add a parser/ingest helper
Create `portal/batch/uptime_runner.py` to:

- Connect to ClickHouse (reuse config).
- Query uptime per feed.
- Return structured rows to insert into Postgres.

---

## API and UI Integration

### API
Add a new endpoint for uptime:

- `GET /benchmarks/uptime?publisher_id=...&date=...`
  - returns per-feed uptime for the date.

### UI
Add an “Uptime” section to the publisher detail view:

- Daily uptime summary (avg/median).
- Table by feed with uptime % and downtime ms.

---

## Low-Risk Milestones

1) **Schema changes only**
   - Add `publisher_feed_daily_uptime` table.

2) **Batch uptime ingestion**
   - Implement `portal/batch/uptime_runner.py`.
   - Wire into `daily_benchmark_runner.py`.

3) **API endpoint**
   - Serve uptime rows for a given publisher/date.

4) **UI surface**
   - Minimal display next to benchmark metrics.

---

## Risks & Mitigations

- **ClickHouse load**: use MV/window-based uptime, limit concurrency.
- **Mismatch in sessions**: start with full-day uptime, extend later.
- **Feed mapping mismatches**: reuse `publisher_feeds.py` logic to ensure consistent feed lists.
- **Backfill**: start with daily cron going forward; add backfill job later.

---

## Extension Options (Post-MVP)

- Add session-specific uptime for US equities (align with benchmark sessions).
- Add deviation metrics (publisher vs Pyth aggregate) using LazerDb data.
- Add on-demand uptime calculations (async job).
