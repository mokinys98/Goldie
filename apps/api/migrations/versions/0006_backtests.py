"""Add backtest experiments and trades."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if {"backtest_experiments", "backtest_trades"}.issubset(tables):
        return
    op.create_table(
        "backtest_experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("config_version_id", sa.Uuid(), nullable=False),
        sa.Column("market_feed_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("spread_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("commission_per_trade", sa.Numeric(20, 8), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("reason_counts", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.ForeignKeyConstraint(["config_version_id"], ["config_versions.id"]),
        sa.ForeignKeyConstraint(["market_feed_id"], ["market_feeds.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_backtest_experiments_bot_id", "backtest_experiments", ["bot_id"])
    op.create_index(
        "ix_backtest_experiments_config_version_id",
        "backtest_experiments",
        ["config_version_id"],
    )
    op.create_index(
        "ix_backtest_experiments_market_feed_id",
        "backtest_experiments",
        ["market_feed_id"],
    )
    op.create_index("ix_backtest_experiments_status", "backtest_experiments", ["status"])
    op.create_index(
        "ix_backtest_experiments_status_created_at",
        "backtest_experiments",
        ["status", "created_at"],
    )
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("risk_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("close_reason", sa.String(length=32), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("commission", sa.Numeric(20, 8), nullable=False),
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("r_multiple", sa.Numeric(20, 8), nullable=False),
        sa.Column("mfe_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("mae_points", sa.Numeric(20, 8), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["backtest_experiments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_trades_experiment_id", "backtest_trades", ["experiment_id"])
    op.create_index(
        "ix_backtest_trades_experiment_opened_at",
        "backtest_trades",
        ["experiment_id", "opened_at"],
    )


def downgrade() -> None:
    op.drop_table("backtest_trades")
    op.drop_table("backtest_experiments")
