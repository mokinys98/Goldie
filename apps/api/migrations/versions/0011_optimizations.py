"""Add optimization runs and trials."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("config_version_id", sa.Uuid(), nullable=False),
        sa.Column("market_feed_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_trials", sa.Integer(), nullable=False),
        sa.Column("objective", sa.String(length=32), nullable=False, server_default="BALANCED"),
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee_maker", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee_taker", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage_small", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage_medium", sa.Numeric(20, 8), nullable=False),
        sa.Column("impact_model", sa.String(length=32), nullable=False, server_default="sqrt"),
        sa.Column("limit_fill_timeout_s", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("min_qty_check", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("best_candidate", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.ForeignKeyConstraint(["config_version_id"], ["config_versions.id"]),
        sa.ForeignKeyConstraint(["market_feed_id"], ["market_feeds.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_optimization_runs_status_created_at",
        "optimization_runs",
        ["status", "created_at"],
    )
    op.create_index(op.f("ix_optimization_runs_bot_id"), "optimization_runs", ["bot_id"])
    op.create_index(op.f("ix_optimization_runs_config_version_id"), "optimization_runs", ["config_version_id"])
    op.create_index(op.f("ix_optimization_runs_market_feed_id"), "optimization_runs", ["market_feed_id"])
    op.create_index(op.f("ix_optimization_runs_status"), "optimization_runs", ["status"])

    op.create_table(
        "optimization_trials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("optimization_run_id", sa.Uuid(), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("sampled_parameters", sa.JSON(), nullable=False),
        sa.Column("score", sa.Numeric(20, 8), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["optimization_run_id"], ["optimization_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("optimization_run_id", "trial_number", name="uq_optimization_trial_number"),
    )
    op.create_index(
        "ix_optimization_trials_run_score",
        "optimization_trials",
        ["optimization_run_id", "score"],
    )
    op.create_index(op.f("ix_optimization_trials_optimization_run_id"), "optimization_trials", ["optimization_run_id"])
    op.create_index(op.f("ix_optimization_trials_status"), "optimization_trials", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_optimization_trials_status"), table_name="optimization_trials")
    op.drop_index(op.f("ix_optimization_trials_optimization_run_id"), table_name="optimization_trials")
    op.drop_index("ix_optimization_trials_run_score", table_name="optimization_trials")
    op.drop_table("optimization_trials")

    op.drop_index(op.f("ix_optimization_runs_status"), table_name="optimization_runs")
    op.drop_index(op.f("ix_optimization_runs_market_feed_id"), table_name="optimization_runs")
    op.drop_index(op.f("ix_optimization_runs_config_version_id"), table_name="optimization_runs")
    op.drop_index(op.f("ix_optimization_runs_bot_id"), table_name="optimization_runs")
    op.drop_index("ix_optimization_runs_status_created_at", table_name="optimization_runs")
    op.drop_table("optimization_runs")
