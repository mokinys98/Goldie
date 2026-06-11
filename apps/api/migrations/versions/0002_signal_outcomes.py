"""Add shadow signal outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("config_version_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("close_reason", sa.String(length=32), nullable=True),
        sa.Column("skip_reason", sa.String(length=40), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=True),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=True),
        sa.Column("volume", sa.Numeric(20, 8), nullable=True),
        sa.Column("risk_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("gross_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("pnl_points", sa.Numeric(20, 8), nullable=True),
        sa.Column("r_multiple", sa.Numeric(20, 8), nullable=True),
        sa.Column("mfe_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("mae_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.ForeignKeyConstraint(["config_version_id"], ["config_versions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
    )
    op.create_index("ix_signal_outcomes_signal_id", "signal_outcomes", ["signal_id"])
    op.create_index("ix_signal_outcomes_bot_id", "signal_outcomes", ["bot_id"])
    op.create_index("ix_signal_outcomes_run_id", "signal_outcomes", ["run_id"])
    op.create_index(
        "ix_signal_outcomes_config_version_id",
        "signal_outcomes",
        ["config_version_id"],
    )
    op.create_index(
        "uq_signal_outcomes_one_open_per_bot",
        "signal_outcomes",
        ["bot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    op.drop_index("uq_signal_outcomes_one_open_per_bot", table_name="signal_outcomes")
    op.drop_index("ix_signal_outcomes_config_version_id", table_name="signal_outcomes")
    op.drop_index("ix_signal_outcomes_run_id", table_name="signal_outcomes")
    op.drop_index("ix_signal_outcomes_bot_id", table_name="signal_outcomes")
    op.drop_index("ix_signal_outcomes_signal_id", table_name="signal_outcomes")
    op.drop_table("signal_outcomes")
