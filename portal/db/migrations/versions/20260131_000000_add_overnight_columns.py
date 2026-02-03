"""Add overnight session columns to benchmark_results.

Revision ID: 006_add_overnight_columns
Revises: 005_fix_uptime_precision
Create Date: 2026-01-31

Adds columns to store overnight session benchmark results for US equities.
Overnight session (8 PM - 4 AM EST) uses publisher 32 as reference.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "006_add_overnight_columns"
down_revision: Union[str, None] = "005_fix_uptime_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add overnight columns to benchmark_results
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_n_observations", sa.Integer(), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_n_reference_observations", sa.Integer(), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_nrmse", sa.Numeric(12, 8), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_hit_rate", sa.Numeric(8, 4), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_passes", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_reference_publisher_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "benchmark_results",
        sa.Column("overnight_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("benchmark_results", "overnight_error")
    op.drop_column("benchmark_results", "overnight_reference_publisher_id")
    op.drop_column("benchmark_results", "overnight_passes")
    op.drop_column("benchmark_results", "overnight_hit_rate")
    op.drop_column("benchmark_results", "overnight_nrmse")
    op.drop_column("benchmark_results", "overnight_n_reference_observations")
    op.drop_column("benchmark_results", "overnight_n_observations")
