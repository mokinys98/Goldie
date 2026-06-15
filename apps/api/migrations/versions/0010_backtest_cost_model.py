"""Replace backtest cost fields with broker cost model parameters."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("backtest_experiments")}

    additions: list[tuple[str, sa.Column]] = [
        ("fee_maker", sa.Column("fee_maker", sa.Numeric(20, 8), nullable=False, server_default="0.001")),
        ("fee_taker", sa.Column("fee_taker", sa.Numeric(20, 8), nullable=False, server_default="0.001")),
        ("slippage_small", sa.Column("slippage_small", sa.Numeric(20, 8), nullable=False, server_default="0.0005")),
        ("slippage_medium", sa.Column("slippage_medium", sa.Numeric(20, 8), nullable=False, server_default="0.001")),
        ("impact_model", sa.Column("impact_model", sa.String(length=32), nullable=False, server_default="sqrt")),
        ("limit_fill_timeout_s", sa.Column("limit_fill_timeout_s", sa.Integer(), nullable=False, server_default="30")),
        ("min_qty_check", sa.Column("min_qty_check", sa.Boolean(), nullable=False, server_default=sa.true())),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("backtest_experiments", column)


def downgrade() -> None:
    for name in [
        "min_qty_check",
        "limit_fill_timeout_s",
        "impact_model",
        "slippage_medium",
        "slippage_small",
        "fee_taker",
        "fee_maker",
    ]:
        op.drop_column("backtest_experiments", name)
