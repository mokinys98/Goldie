"""Persist per-strategy trade exit optimization ranges."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_profiles",
        sa.Column("trade_ranges", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("strategy_profiles", "trade_ranges")
