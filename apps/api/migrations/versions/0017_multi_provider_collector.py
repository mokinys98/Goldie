"""Add provider identity to collector instruments."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("collector_instrument_configurations")
    }
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "collector_instrument_configurations"
        )
    }
    if (
        {"provider", "environment"}.issubset(columns)
        and "uq_collector_instrument_provider_symbol" in unique_constraints
    ):
        return
    with op.batch_alter_table("collector_instrument_configurations") as batch:
        if "provider" not in columns:
            batch.add_column(
                sa.Column(
                    "provider",
                    sa.String(length=32),
                    nullable=False,
                    server_default="oanda",
                )
            )
        if "environment" not in columns:
            batch.add_column(
                sa.Column(
                    "environment",
                    sa.String(length=32),
                    nullable=False,
                    server_default="practice",
                )
            )
        try:
            batch.drop_constraint(
                "collector_instrument_configurations_provider_symbol_key",
                type_="unique",
            )
        except ValueError:
            pass
        batch.create_unique_constraint(
            "uq_collector_instrument_provider_symbol",
            ["provider", "environment", "provider_symbol"],
        )
        batch.create_index(
            "ix_collector_instrument_configurations_provider",
            ["provider"],
        )


def downgrade() -> None:
    with op.batch_alter_table("collector_instrument_configurations") as batch:
        batch.drop_index("ix_collector_instrument_configurations_provider")
        batch.drop_constraint("uq_collector_instrument_provider_symbol", type_="unique")
        batch.create_unique_constraint(
            "collector_instrument_configurations_provider_symbol_key",
            ["provider_symbol"],
        )
        batch.drop_column("environment")
        batch.drop_column("provider")
