-- Publisher Performance Portal - Database Schema
-- This schema stores benchmark results from publisher_benchmark.py
-- for the self-service publisher performance dashboard.

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- PUBLISHERS TABLE
-- Registry of publishers (cached from ClickHouse for fast lookups)
-- ============================================================================

CREATE TABLE IF NOT EXISTS publishers (
    publisher_id INTEGER PRIMARY KEY,
    name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_publishers_active ON publishers(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- FEEDS TABLE
-- Registry of feeds (cached from ClickHouse for fast lookups)
-- ============================================================================

CREATE TABLE IF NOT EXISTS feeds (
    feed_id INTEGER PRIMARY KEY,
    symbol VARCHAR(255),
    asset_class VARCHAR(50),
    exponent INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feeds_asset_class ON feeds(asset_class);
CREATE INDEX IF NOT EXISTS idx_feeds_symbol ON feeds(symbol);
CREATE INDEX IF NOT EXISTS idx_feeds_active ON feeds(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- BENCHMARK RESULTS TABLE
-- One row per publisher/feed/date combination
-- Contains all metrics from publisher_benchmark.py
-- ============================================================================

CREATE TABLE IF NOT EXISTS benchmark_results (
    id BIGSERIAL PRIMARY KEY,

    -- Identifiers
    publisher_id INTEGER NOT NULL,
    feed_id INTEGER NOT NULL,
    benchmark_date DATE NOT NULL,
    asset_class VARCHAR(50) NOT NULL,
    symbol VARCHAR(255),

    -- Pass/Fail status
    passes BOOLEAN NOT NULL,

    -- Primary metrics (used for pass/fail criteria)
    n_observations INTEGER NOT NULL DEFAULT 0,
    nrmse DECIMAL(12, 8),                    -- RMSE / benchmark_price_range
    hit_rate DECIMAL(8, 4),                  -- % within 10 basis points
    benchmark_price_range DECIMAL(18, 8),    -- max - min benchmark price

    -- Secondary metrics (informational)
    rmse DECIMAL(18, 8),                     -- Root Mean Square Error
    mean_spread DECIMAL(18, 8),              -- Mean bid-ask spread
    rmse_over_spread DECIMAL(12, 6),         -- RMSE / mean_spread

    -- Statistical metrics - Basic
    mean_diff DECIMAL(18, 10),               -- Mean of (publisher - benchmark)
    std_diff DECIMAL(18, 10),                -- Std dev of price differences
    mean_pct_diff DECIMAL(12, 8),            -- Mean percentage difference
    std_pct_diff DECIMAL(12, 8),             -- Std dev of percentage differences
    mae DECIMAL(18, 10),                     -- Mean Absolute Error

    -- Statistical metrics - Hypothesis tests
    t_statistic DECIMAL(12, 6),              -- t-test statistic
    t_pvalue DECIMAL(12, 8),                 -- t-test p-value (< 0.05 = significant bias)
    wilcoxon_statistic DECIMAL(12, 6),       -- Wilcoxon signed-rank statistic
    wilcoxon_pvalue DECIMAL(12, 8),          -- Wilcoxon p-value
    normality_pvalue DECIMAL(12, 8),         -- D'Agostino-Pearson normality test
    mean_abs_z_score DECIMAL(12, 6),         -- Mean |z-score| (typical: ~0.8)

    -- Extended hours metrics (US equities only, nullable)
    premarket_n_observations INTEGER,
    premarket_nrmse DECIMAL(12, 8),
    premarket_hit_rate DECIMAL(8, 4),
    premarket_passes BOOLEAN,
    premarket_error TEXT,

    afterhours_n_observations INTEGER,
    afterhours_nrmse DECIMAL(12, 8),
    afterhours_hit_rate DECIMAL(8, 4),
    afterhours_passes BOOLEAN,
    afterhours_error TEXT,

    -- Error tracking
    error TEXT,
    execution_time_ms INTEGER,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_results_publisher_feed_date UNIQUE(publisher_id, feed_id, benchmark_date)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_results_publisher_date
    ON benchmark_results(publisher_id, benchmark_date DESC);

CREATE INDEX IF NOT EXISTS idx_results_feed_date
    ON benchmark_results(feed_id, benchmark_date DESC);

CREATE INDEX IF NOT EXISTS idx_results_asset_class_date
    ON benchmark_results(asset_class, benchmark_date DESC);

CREATE INDEX IF NOT EXISTS idx_results_date
    ON benchmark_results(benchmark_date DESC);

CREATE INDEX IF NOT EXISTS idx_results_passes
    ON benchmark_results(passes, benchmark_date DESC);

CREATE INDEX IF NOT EXISTS idx_results_errors
    ON benchmark_results(benchmark_date DESC)
    WHERE error IS NOT NULL;

-- ============================================================================
-- PUBLISHER DAILY SUMMARY TABLE
-- Pre-aggregated daily statistics per publisher for fast leaderboard queries
-- ============================================================================

CREATE TABLE IF NOT EXISTS publisher_daily_summary (
    id BIGSERIAL PRIMARY KEY,

    -- Identifiers
    publisher_id INTEGER NOT NULL,
    summary_date DATE NOT NULL,

    -- Counts
    total_feeds INTEGER NOT NULL DEFAULT 0,
    pass_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    pass_rate_pct DECIMAL(5, 2),

    -- Pass criteria breakdown
    pass_by_nrmse_alone INTEGER DEFAULT 0,          -- nrmse < 0.01
    pass_by_nrmse_and_hit_rate INTEGER DEFAULT 0,   -- nrmse < 0.05 AND hit_rate >= 98

    -- NRMSE aggregates (lower is better)
    median_nrmse DECIMAL(12, 8),
    mean_nrmse DECIMAL(12, 8),
    p90_nrmse DECIMAL(12, 8),
    p95_nrmse DECIMAL(12, 8),
    min_nrmse DECIMAL(12, 8),
    max_nrmse DECIMAL(12, 8),

    -- Hit rate aggregates (higher is better)
    median_hit_rate DECIMAL(8, 4),
    mean_hit_rate DECIMAL(8, 4),
    min_hit_rate DECIMAL(8, 4),
    max_hit_rate DECIMAL(8, 4),

    -- RMSE/Spread aggregates (reference metric)
    median_rmse_over_spread DECIMAL(12, 6),
    mean_rmse_over_spread DECIMAL(12, 6),
    p90_rmse_over_spread DECIMAL(12, 6),
    p95_rmse_over_spread DECIMAL(12, 6),

    -- Coverage metrics
    total_observations BIGINT DEFAULT 0,
    mean_observations_per_feed DECIMAL(10, 1),
    median_observations_per_feed INTEGER,

    -- Statistical summary
    median_mae DECIMAL(18, 10),
    mean_mae DECIMAL(18, 10),
    t_test_significance_rate DECIMAL(5, 2),   -- % of feeds with significant bias
    normality_rate DECIMAL(5, 2),             -- % of feeds with normal errors
    median_z_score DECIMAL(12, 6),

    -- Breakdown by asset class (flexible JSON storage)
    asset_class_breakdown JSONB,

    -- Extended hours summary (US equities only)
    extended_hours_summary JSONB,

    -- Timing
    batch_duration_sec DECIMAL(10, 2),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_summary_publisher_date UNIQUE(publisher_id, summary_date)
);

-- Indexes for leaderboard queries
CREATE INDEX IF NOT EXISTS idx_summary_date
    ON publisher_daily_summary(summary_date DESC);

CREATE INDEX IF NOT EXISTS idx_summary_publisher_date
    ON publisher_daily_summary(publisher_id, summary_date DESC);

CREATE INDEX IF NOT EXISTS idx_summary_pass_rate
    ON publisher_daily_summary(summary_date DESC, pass_rate_pct DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_summary_nrmse
    ON publisher_daily_summary(summary_date DESC, median_nrmse ASC NULLS LAST);

-- ============================================================================
-- PUBLISHER FEED DAILY UPTIME TABLE
-- Session-aware uptime per publisher/feed/date
-- ============================================================================

CREATE TABLE IF NOT EXISTS publisher_feed_daily_uptime (
    id BIGSERIAL PRIMARY KEY,

    -- Identifiers
    publisher_id INTEGER NOT NULL,
    feed_id INTEGER NOT NULL,
    uptime_date DATE NOT NULL,
    asset_class VARCHAR(50),
    session VARCHAR(32) NOT NULL,

    -- Uptime metrics
    uptime_pct DECIMAL(6, 4) NOT NULL,
    downtime_ms BIGINT NOT NULL,
    period_length_ms BIGINT NOT NULL,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_uptime_publisher_feed_date_session UNIQUE(publisher_id, feed_id, uptime_date, session)
);

CREATE INDEX IF NOT EXISTS idx_uptime_publisher_date
    ON publisher_feed_daily_uptime(publisher_id, uptime_date DESC);

CREATE INDEX IF NOT EXISTS idx_uptime_feed_date
    ON publisher_feed_daily_uptime(feed_id, uptime_date DESC);

CREATE INDEX IF NOT EXISTS idx_uptime_session_date
    ON publisher_feed_daily_uptime(session, uptime_date DESC);

-- ============================================================================
-- BENCHMARK JOBS TABLE
-- Tracks on-demand and batch benchmark job runs
-- ============================================================================

CREATE TABLE IF NOT EXISTS benchmark_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Job parameters
    publisher_id INTEGER,                    -- NULL = all publishers (daily batch)
    feed_ids INTEGER[],                      -- NULL = all feeds for publisher
    target_date DATE NOT NULL,
    include_extended_hours BOOLEAN DEFAULT FALSE,

    -- Job lifecycle
    status VARCHAR(20) DEFAULT 'pending',    -- pending, running, completed, failed
    requested_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Results summary
    results_count INTEGER,
    pass_count INTEGER,
    fail_count INTEGER,
    error_count INTEGER,

    -- Error tracking
    error TEXT,

    -- Metadata
    job_type VARCHAR(20) DEFAULT 'on_demand', -- on_demand, daily_batch
    requested_by VARCHAR(255),                -- IP or identifier

    CONSTRAINT chk_status CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_publisher
    ON benchmark_jobs(publisher_id, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON benchmark_jobs(status)
    WHERE status IN ('pending', 'running');

CREATE INDEX IF NOT EXISTS idx_jobs_date
    ON benchmark_jobs(target_date DESC);

-- ============================================================================
-- VIEWS
-- Convenient views for common queries
-- ============================================================================

-- Latest results per publisher (most recent date)
CREATE OR REPLACE VIEW v_latest_publisher_summary AS
SELECT DISTINCT ON (publisher_id)
    *
FROM publisher_daily_summary
ORDER BY publisher_id, summary_date DESC;

-- Latest results per feed (most recent date)
CREATE OR REPLACE VIEW v_latest_feed_results AS
SELECT DISTINCT ON (feed_id, publisher_id)
    *
FROM benchmark_results
WHERE error IS NULL
ORDER BY feed_id, publisher_id, benchmark_date DESC;

-- Leaderboard view (latest date, ranked by pass rate)
CREATE OR REPLACE VIEW v_leaderboard AS
SELECT
    pds.*,
    p.name as publisher_name,
    RANK() OVER (ORDER BY pds.pass_rate_pct DESC NULLS LAST) as rank_by_pass_rate,
    RANK() OVER (ORDER BY pds.median_nrmse ASC NULLS LAST) as rank_by_nrmse,
    RANK() OVER (ORDER BY pds.median_hit_rate DESC NULLS LAST) as rank_by_hit_rate
FROM publisher_daily_summary pds
LEFT JOIN publishers p ON pds.publisher_id = p.publisher_id
WHERE pds.summary_date = (SELECT MAX(summary_date) FROM publisher_daily_summary);

-- Failing feeds view (for alerts/attention)
CREATE OR REPLACE VIEW v_failing_feeds AS
SELECT
    br.*,
    f.symbol as feed_symbol,
    p.name as publisher_name
FROM benchmark_results br
LEFT JOIN feeds f ON br.feed_id = f.feed_id
LEFT JOIN publishers p ON br.publisher_id = p.publisher_id
WHERE br.passes = FALSE
  AND br.error IS NULL
  AND br.benchmark_date = (SELECT MAX(benchmark_date) FROM benchmark_results);

-- ============================================================================
-- FUNCTIONS
-- Helper functions for common operations
-- ============================================================================

-- Function to compute percentile (used in summary computation)
CREATE OR REPLACE FUNCTION percentile_cont_array(percentiles float8[], arr float8[])
RETURNS float8[] AS $$
    SELECT array_agg(p)
    FROM (
        SELECT percentile_cont(unnest(percentiles)) WITHIN GROUP (ORDER BY v) as p
        FROM unnest(arr) v
    ) sub;
$$ LANGUAGE SQL IMMUTABLE;

-- Function to get latest benchmark date
CREATE OR REPLACE FUNCTION get_latest_benchmark_date()
RETURNS DATE AS $$
    SELECT MAX(benchmark_date) FROM benchmark_results;
$$ LANGUAGE SQL STABLE;
