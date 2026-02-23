"""Add publisher feed daily uptime table.

Revision ID: 002_uptime_table
Revises: 001_initial
Create Date: 2026-01-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_uptime_table"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publisher_feed_daily_uptime",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # Identifiers
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("uptime_date", sa.Date(), nullable=False),
        sa.Column("asset_class", sa.String(50), nullable=True),
        sa.Column("session", sa.String(32), nullable=False),
        # Metrics
        sa.Column("uptime_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("downtime_ms", sa.BigInteger(), nullable=False),
        sa.Column("period_length_ms", sa.BigInteger(), nullable=False),
        # Metadata
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publisher_id",
            "feed_id",
            "uptime_date",
            "session",
            name="uq_uptime_publisher_feed_date_session",
        ),
    )

    op.create_index(
        "idx_uptime_publisher_date",
        "publisher_feed_daily_uptime",
        ["publisher_id", sa.text("uptime_date DESC")],
    )
    op.create_index(
        "idx_uptime_feed_date",
        "publisher_feed_daily_uptime",
        ["feed_id", sa.text("uptime_date DESC")],
    )
    op.create_index(
        "idx_uptime_session_date",
        "publisher_feed_daily_uptime",
        ["session", sa.text("uptime_date DESC")],
    )


def downgrade() -> None:
    op.drop_table("publisher_feed_daily_uptime")
