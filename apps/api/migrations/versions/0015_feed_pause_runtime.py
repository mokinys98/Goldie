"""Add authoritative feed pause runtime state."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collector_configurations",
        sa.Column(
            "globally_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "market_feeds",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "market_feeds",
        sa.Column("resume_from_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "signal_outcomes",
        sa.Column(
            "paused_duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_bots_runtime_feed",
        "bots",
        ["market_feed_id", "archived_at", "state"],
    )
    op.create_index("ix_runs_bot_status", "runs", ["bot_id", "status"])
    op.create_index(
        "ix_signals_bot_run_observed",
        "signals",
        ["bot_id", "run_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_bot_run_observed", table_name="signals")
    op.drop_index("ix_runs_bot_status", table_name="runs")
    op.drop_index("ix_bots_runtime_feed", table_name="bots")
    op.drop_column("signal_outcomes", "paused_duration_seconds")
    op.drop_column("market_feeds", "resume_from_at")
    op.drop_column("market_feeds", "paused_at")
    op.drop_column("collector_configurations", "globally_paused")
