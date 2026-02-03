"""Initial schema for publisher performance portal.

Revision ID: 001_initial
Revises:
Create Date: 2025-01-27

Creates all tables for storing benchmark results, publisher summaries,
and job tracking.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable UUID extension
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # Publishers table
    op.create_table(
        "publishers",
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("publisher_id"),
    )
    op.create_index(
        "idx_publishers_active",
        "publishers",
        ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # Feeds table
    op.create_table(
        "feeds",
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=True),
        sa.Column("asset_class", sa.String(50), nullable=True),
        sa.Column("exponent", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("feed_id"),
    )
    op.create_index("idx_feeds_asset_class", "feeds", ["asset_class"])
    op.create_index("idx_feeds_symbol", "feeds", ["symbol"])
    op.create_index(
        "idx_feeds_active",
        "feeds",
        ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # Benchmark results table
    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # Identifiers
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("benchmark_date", sa.Date(), nullable=False),
        sa.Column("asset_class", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=True),
        # Pass/Fail
        sa.Column("passes", sa.Boolean(), nullable=False),
        # Primary metrics
        sa.Column("n_observations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("benchmark_price_range", sa.Numeric(18, 8), nullable=True),
        # Secondary metrics
        sa.Column("rmse", sa.Numeric(18, 8), nullable=True),
        sa.Column("mean_spread", sa.Numeric(18, 8), nullable=True),
        sa.Column("rmse_over_spread", sa.Numeric(12, 6), nullable=True),
        # Statistical metrics - Basic
        sa.Column("mean_diff", sa.Numeric(18, 10), nullable=True),
        sa.Column("std_diff", sa.Numeric(18, 10), nullable=True),
        sa.Column("mean_pct_diff", sa.Numeric(12, 8), nullable=True),
        sa.Column("std_pct_diff", sa.Numeric(12, 8), nullable=True),
        sa.Column("mae", sa.Numeric(18, 10), nullable=True),
        # Statistical metrics - Hypothesis tests
        sa.Column("t_statistic", sa.Numeric(12, 6), nullable=True),
        sa.Column("t_pvalue", sa.Numeric(12, 8), nullable=True),
        sa.Column("wilcoxon_statistic", sa.Numeric(12, 6), nullable=True),
        sa.Column("wilcoxon_pvalue", sa.Numeric(12, 8), nullable=True),
        sa.Column("normality_pvalue", sa.Numeric(12, 8), nullable=True),
        sa.Column("mean_abs_z_score", sa.Numeric(12, 6), nullable=True),
        # Extended hours metrics
        sa.Column("premarket_n_observations", sa.Integer(), nullable=True),
        sa.Column("premarket_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("premarket_hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("premarket_passes", sa.Boolean(), nullable=True),
        sa.Column("premarket_error", sa.Text(), nullable=True),
        sa.Column("afterhours_n_observations", sa.Integer(), nullable=True),
        sa.Column("afterhours_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("afterhours_hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("afterhours_passes", sa.Boolean(), nullable=True),
        sa.Column("afterhours_error", sa.Text(), nullable=True),
        # Error tracking
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        # Metadata
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publisher_id", "feed_id", "benchmark_date", name="uq_results_publisher_feed_date"),
    )
    op.create_index("idx_results_publisher_date", "benchmark_results", ["publisher_id", sa.text("benchmark_date DESC")])
    op.create_index("idx_results_feed_date", "benchmark_results", ["feed_id", sa.text("benchmark_date DESC")])
    op.create_index("idx_results_asset_class_date", "benchmark_results", ["asset_class", sa.text("benchmark_date DESC")])
    op.create_index("idx_results_date", "benchmark_results", [sa.text("benchmark_date DESC")])
    op.create_index("idx_results_passes", "benchmark_results", ["passes", sa.text("benchmark_date DESC")])
    op.create_index(
        "idx_results_errors",
        "benchmark_results",
        [sa.text("benchmark_date DESC")],
        postgresql_where=sa.text("error IS NOT NULL"),
    )

    # Publisher daily summary table
    op.create_table(
        "publisher_daily_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # Identifiers
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        # Counts
        sa.Column("total_feeds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pass_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pass_rate_pct", sa.Numeric(5, 2), nullable=True),
        # Pass criteria breakdown
        sa.Column("pass_by_nrmse_alone", sa.Integer(), server_default="0", nullable=True),
        sa.Column("pass_by_nrmse_and_hit_rate", sa.Integer(), server_default="0", nullable=True),
        # NRMSE aggregates
        sa.Column("median_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("mean_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("p90_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("p95_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("min_nrmse", sa.Numeric(12, 8), nullable=True),
        sa.Column("max_nrmse", sa.Numeric(12, 8), nullable=True),
        # Hit rate aggregates
        sa.Column("median_hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("mean_hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("min_hit_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_hit_rate", sa.Numeric(8, 4), nullable=True),
        # RMSE/Spread aggregates
        sa.Column("median_rmse_over_spread", sa.Numeric(12, 6), nullable=True),
        sa.Column("mean_rmse_over_spread", sa.Numeric(12, 6), nullable=True),
        sa.Column("p90_rmse_over_spread", sa.Numeric(12, 6), nullable=True),
        sa.Column("p95_rmse_over_spread", sa.Numeric(12, 6), nullable=True),
        # Coverage metrics
        sa.Column("total_observations", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("mean_observations_per_feed", sa.Numeric(10, 1), nullable=True),
        sa.Column("median_observations_per_feed", sa.Integer(), nullable=True),
        # Statistical summary
        sa.Column("median_mae", sa.Numeric(18, 10), nullable=True),
        sa.Column("mean_mae", sa.Numeric(18, 10), nullable=True),
        sa.Column("t_test_significance_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("normality_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("median_z_score", sa.Numeric(12, 6), nullable=True),
        # JSON breakdowns
        sa.Column("asset_class_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("extended_hours_summary", postgresql.JSONB(), nullable=True),
        # Timing
        sa.Column("batch_duration_sec", sa.Numeric(10, 2), nullable=True),
        # Metadata
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publisher_id", "summary_date", name="uq_summary_publisher_date"),
    )
    op.create_index("idx_summary_date", "publisher_daily_summary", [sa.text("summary_date DESC")])
    op.create_index("idx_summary_publisher_date", "publisher_daily_summary", ["publisher_id", sa.text("summary_date DESC")])
    op.create_index("idx_summary_pass_rate", "publisher_daily_summary", [sa.text("summary_date DESC"), sa.text("pass_rate_pct DESC NULLS LAST")])
    op.create_index("idx_summary_nrmse", "publisher_daily_summary", [sa.text("summary_date DESC"), sa.text("median_nrmse ASC NULLS LAST")])

    # Benchmark jobs table
    op.create_table(
        "benchmark_jobs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        # Job parameters
        sa.Column("publisher_id", sa.Integer(), nullable=True),
        sa.Column("feed_ids", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("include_extended_hours", sa.Boolean(), server_default="false", nullable=False),
        # Job lifecycle
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        # Results summary
        sa.Column("results_count", sa.Integer(), nullable=True),
        sa.Column("pass_count", sa.Integer(), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=True),
        # Error tracking
        sa.Column("error", sa.Text(), nullable=True),
        # Metadata
        sa.Column("job_type", sa.String(20), server_default="on_demand", nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="chk_status"),
    )
    op.create_index("idx_jobs_publisher", "benchmark_jobs", ["publisher_id", sa.text("requested_at DESC")])
    op.create_index(
        "idx_jobs_status",
        "benchmark_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index("idx_jobs_date", "benchmark_jobs", [sa.text("target_date DESC")])


def downgrade() -> None:
    op.drop_table("benchmark_jobs")
    op.drop_table("publisher_daily_summary")
    op.drop_table("benchmark_results")
    op.drop_table("feeds")
    op.drop_table("publishers")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
