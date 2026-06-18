"""Add execution model fields."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _add_execution_columns(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("fill_mode", sa.String(length=16), nullable=False, server_default="simulated"),
    )
    op.add_column(
        table_name,
        sa.Column("taker_slippage", sa.Numeric(20, 8), nullable=False, server_default="0"),
    )
    op.add_column(
        table_name,
        sa.Column("medium_impact", sa.Numeric(20, 8), nullable=False, server_default="0.001"),
    )
    op.add_column(
        table_name,
        sa.Column("model_sqrt_limit", sa.Numeric(20, 8), nullable=False, server_default="1.0"),
    )
    op.add_column(
        table_name,
        sa.Column("min_qty_threshold", sa.Numeric(20, 8), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET medium_impact = slippage_medium "
            "WHERE slippage_medium IS NOT NULL"
        )
    )


def _drop_execution_columns(table_name: str) -> None:
    op.drop_column(table_name, "min_qty_threshold")
    op.drop_column(table_name, "model_sqrt_limit")
    op.drop_column(table_name, "medium_impact")
    op.drop_column(table_name, "taker_slippage")
    op.drop_column(table_name, "fill_mode")


def upgrade() -> None:
    _add_execution_columns("backtest_experiments")
    _add_execution_columns("optimization_runs")


def downgrade() -> None:
    _drop_execution_columns("optimization_runs")
    _drop_execution_columns("backtest_experiments")
