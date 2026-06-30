"""Persist strategy optimization ranges and optimization search-space snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_profiles",
        sa.Column("optimization_ranges", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "optimization_runs",
        sa.Column("search_space_snapshot", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("optimization_runs", "search_space_snapshot")
    op.drop_column("strategy_profiles", "optimization_ranges")
