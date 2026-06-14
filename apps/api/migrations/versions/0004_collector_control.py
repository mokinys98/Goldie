"""Add collector control plane."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
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
    if "collector_configurations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "collector_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("quote_interval_seconds", sa.Numeric(10, 2), nullable=False),
        sa.Column("candle_poll_seconds", sa.Numeric(10, 2), nullable=False),
        sa.Column("heartbeat_seconds", sa.Numeric(10, 2), nullable=False),
        sa.Column("backfill_days", sa.Integer(), nullable=False),
        sa.Column("backfill_batch_size", sa.Integer(), nullable=False),
        sa.Column("configuration_retry_seconds", sa.Numeric(10, 2), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "collector_instrument_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_symbol", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_symbol"),
    )
    op.create_index(
        "ix_collector_instrument_configurations_provider_symbol",
        "collector_instrument_configurations",
        ["provider_symbol"],
    )
    op.create_table(
        "collector_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_config_version", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_collector_instances_name", "collector_instances", ["name"])
    op.create_table(
        "collector_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collector_instance_id", sa.Uuid(), nullable=True),
        sa.Column("market_feed_id", sa.Uuid(), nullable=True),
        sa.Column("command", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["collector_instance_id"], ["collector_instances.id"]),
        sa.ForeignKeyConstraint(["market_feed_id"], ["market_feeds.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collector_commands_collector_instance_id",
        "collector_commands",
        ["collector_instance_id"],
    )
    op.create_index(
        "ix_collector_commands_market_feed_id",
        "collector_commands",
        ["market_feed_id"],
    )
    op.create_index("ix_collector_commands_command", "collector_commands", ["command"])
    op.create_index("ix_collector_commands_status", "collector_commands", ["status"])


def downgrade() -> None:
    op.drop_table("collector_commands")
    op.drop_table("collector_instances")
    op.drop_table("collector_instrument_configurations")
    op.drop_table("collector_configurations")
