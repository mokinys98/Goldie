"""Drop legacy backtest cost fields superseded by broker cost model."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("backtest_experiments")}

    for name in ["spread_points", "slippage_points", "commission_per_trade"]:
        if name in columns:
            op.drop_column("backtest_experiments", name)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("backtest_experiments")}

    restorations: list[tuple[str, sa.Column]] = [
        (
            "spread_points",
            sa.Column(
                "spread_points",
                sa.Numeric(20, 8),
                nullable=False,
                server_default="2",
            ),
        ),
        (
            "slippage_points",
            sa.Column(
                "slippage_points",
                sa.Numeric(20, 8),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "commission_per_trade",
            sa.Column(
                "commission_per_trade",
                sa.Numeric(20, 8),
                nullable=False,
                server_default="0",
            ),
        ),
    ]
    for name, column in restorations:
        if name not in columns:
            op.add_column("backtest_experiments", column)
