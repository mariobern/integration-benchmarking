"""Fix precision for uptime_pct column.

Revision ID: 005_fix_uptime_precision
Revises: 004_fix_statistic_precision
Create Date: 2026-01-30

The uptime_pct column needs to hold values 0-100 with 4 decimal places.
DECIMAL(6,4) can only hold up to 99.9999. Change to DECIMAL(8,4).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_fix_uptime_precision"
down_revision: Union[str, None] = "004_fix_statistic_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix uptime_pct in publisher_feed_daily_uptime
    op.alter_column(
        "publisher_feed_daily_uptime",
        "uptime_pct",
        type_=sa.Numeric(8, 4),
        existing_type=sa.Numeric(6, 4),
        existing_nullable=False,
    )

    # Fix uptime columns in publisher_daily_uptime_summary
    for col in [
        "regular_median_uptime_pct",
        "regular_mean_uptime_pct",
        "regular_min_uptime_pct",
        "premarket_median_uptime_pct",
        "premarket_mean_uptime_pct",
        "premarket_min_uptime_pct",
        "afterhours_median_uptime_pct",
        "afterhours_mean_uptime_pct",
        "afterhours_min_uptime_pct",
        "overnight_median_uptime_pct",
        "overnight_mean_uptime_pct",
        "overnight_min_uptime_pct",
        "overall_median_uptime_pct",
        "overall_mean_uptime_pct",
    ]:
        op.alter_column(
            "publisher_daily_uptime_summary",
            col,
            type_=sa.Numeric(8, 4),
            existing_type=sa.Numeric(6, 4),
            existing_nullable=True,
        )

    # Fix uptime columns in publisher_daily_summary
    for col in ["overall_median_uptime_pct", "regular_median_uptime_pct"]:
        op.alter_column(
            "publisher_daily_summary",
            col,
            type_=sa.Numeric(8, 4),
            existing_type=sa.Numeric(6, 4),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Revert publisher_feed_daily_uptime
    op.alter_column(
        "publisher_feed_daily_uptime",
        "uptime_pct",
        type_=sa.Numeric(6, 4),
        existing_type=sa.Numeric(8, 4),
        existing_nullable=False,
    )

    # Revert publisher_daily_uptime_summary
    for col in [
        "regular_median_uptime_pct",
        "regular_mean_uptime_pct",
        "regular_min_uptime_pct",
        "premarket_median_uptime_pct",
        "premarket_mean_uptime_pct",
        "premarket_min_uptime_pct",
        "afterhours_median_uptime_pct",
        "afterhours_mean_uptime_pct",
        "afterhours_min_uptime_pct",
        "overnight_median_uptime_pct",
        "overnight_mean_uptime_pct",
        "overnight_min_uptime_pct",
        "overall_median_uptime_pct",
        "overall_mean_uptime_pct",
    ]:
        op.alter_column(
            "publisher_daily_uptime_summary",
            col,
            type_=sa.Numeric(6, 4),
            existing_type=sa.Numeric(8, 4),
            existing_nullable=True,
        )

    # Revert publisher_daily_summary
    for col in ["overall_median_uptime_pct", "regular_median_uptime_pct"]:
        op.alter_column(
            "publisher_daily_summary",
            col,
            type_=sa.Numeric(6, 4),
            existing_type=sa.Numeric(8, 4),
            existing_nullable=True,
        )
