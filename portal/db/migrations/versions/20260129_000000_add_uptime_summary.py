"""Add publisher daily uptime summary table and link uptime to benchmark summary.

Revision ID: 003_uptime_summary
Revises: 002_uptime_table
Create Date: 2026-01-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "003_uptime_summary"
down_revision: Union[str, None] = "002_uptime_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create publisher_daily_uptime_summary table
    op.create_table(
        "publisher_daily_uptime_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # Identifiers
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        # Per-session aggregates - Regular
        sa.Column("regular_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("regular_mean_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("regular_min_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("regular_total_feeds", sa.Integer(), default=0),
        # Per-session aggregates - Premarket
        sa.Column("premarket_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("premarket_mean_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("premarket_min_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("premarket_total_feeds", sa.Integer(), default=0),
        # Per-session aggregates - Afterhours
        sa.Column("afterhours_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("afterhours_mean_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("afterhours_min_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("afterhours_total_feeds", sa.Integer(), default=0),
        # Per-session aggregates - Overnight
        sa.Column("overnight_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("overnight_mean_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("overnight_min_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("overnight_total_feeds", sa.Integer(), default=0),
        # Overall aggregates
        sa.Column("overall_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("overall_mean_uptime_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("total_feeds", sa.Integer(), default=0),
        # Asset class breakdown (JSON)
        sa.Column("asset_class_uptime", JSONB(), nullable=True),
        # Metadata
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publisher_id",
            "summary_date",
            name="uq_uptime_summary_publisher_date",
        ),
    )

    # Create indexes
    op.create_index(
        "idx_uptime_summary_date",
        "publisher_daily_uptime_summary",
        [sa.text("summary_date DESC")],
    )
    op.create_index(
        "idx_uptime_summary_publisher",
        "publisher_daily_uptime_summary",
        ["publisher_id", sa.text("summary_date DESC")],
    )

    # Add uptime columns to publisher_daily_summary to link benchmark + uptime
    op.add_column(
        "publisher_daily_summary",
        sa.Column("overall_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
    )
    op.add_column(
        "publisher_daily_summary",
        sa.Column("regular_median_uptime_pct", sa.Numeric(6, 4), nullable=True),
    )


def downgrade() -> None:
    # Remove uptime columns from publisher_daily_summary
    op.drop_column("publisher_daily_summary", "overall_median_uptime_pct")
    op.drop_column("publisher_daily_summary", "regular_median_uptime_pct")

    # Drop publisher_daily_uptime_summary table
    op.drop_table("publisher_daily_uptime_summary")
