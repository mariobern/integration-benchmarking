"""Fix precision for wilcoxon_statistic and t_statistic columns.

Revision ID: 004_fix_statistic_precision
Revises: 003_uptime_summary
Create Date: 2026-01-30

The wilcoxon_statistic can be very large (billions) for large sample sizes.
Increase precision from DECIMAL(12, 6) to DECIMAL(20, 6).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004_fix_statistic_precision"
down_revision: Union[str, None] = "003_uptime_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase precision for statistical columns that can have large values
    op.alter_column(
        "benchmark_results",
        "wilcoxon_statistic",
        type_=sa.Numeric(20, 6),
        existing_type=sa.Numeric(12, 6),
        existing_nullable=True,
    )
    op.alter_column(
        "benchmark_results",
        "t_statistic",
        type_=sa.Numeric(20, 6),
        existing_type=sa.Numeric(12, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "benchmark_results",
        "wilcoxon_statistic",
        type_=sa.Numeric(12, 6),
        existing_type=sa.Numeric(20, 6),
        existing_nullable=True,
    )
    op.alter_column(
        "benchmark_results",
        "t_statistic",
        type_=sa.Numeric(12, 6),
        existing_type=sa.Numeric(20, 6),
        existing_nullable=True,
    )
