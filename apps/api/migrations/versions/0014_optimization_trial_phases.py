"""Add optimization trial phases and fixed config overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "optimization_trials",
        sa.Column(
            "phase",
            sa.String(length=32),
            nullable=False,
            server_default="STRATEGY_SEARCH",
        ),
    )
    op.add_column(
        "optimization_trials",
        sa.Column("config_overrides", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        op.f("ix_optimization_trials_phase"),
        "optimization_trials",
        ["phase"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_optimization_trials_phase"), table_name="optimization_trials")
    op.drop_column("optimization_trials", "config_overrides")
    op.drop_column("optimization_trials", "phase")
