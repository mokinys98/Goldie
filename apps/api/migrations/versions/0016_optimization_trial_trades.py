"""Add optimization trial trades."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "optimization_trial_trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trial_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("signal_reason", sa.String(length=64), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("close_reason", sa.String(length=32), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("commission", sa.Numeric(20, 8), nullable=False),
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("r_multiple", sa.Numeric(20, 8), nullable=False),
        sa.Column("mfe_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("mae_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("session", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["trial_id"],
            ["optimization_trials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_optimization_trial_trades_trial_id"),
        "optimization_trial_trades",
        ["trial_id"],
    )
    op.create_index(
        "ix_optimization_trial_trades_trial_opened_at",
        "optimization_trial_trades",
        ["trial_id", "opened_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_optimization_trial_trades_trial_opened_at",
        table_name="optimization_trial_trades",
    )
    op.drop_index(
        op.f("ix_optimization_trial_trades_trial_id"),
        table_name="optimization_trial_trades",
    )
    op.drop_table("optimization_trial_trades")
