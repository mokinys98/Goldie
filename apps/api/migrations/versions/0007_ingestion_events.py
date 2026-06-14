"""Add idempotent ingestion event tracking."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "ingestion_events" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "ingestion_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("market_feed_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("collector_id", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["collector_id"], ["collector_instances.id"]),
        sa.ForeignKeyConstraint(["market_feed_id"], ["market_feeds.id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_ingestion_events_event_type",
        "ingestion_events",
        ["event_type"],
    )
    op.create_index(
        "ix_ingestion_events_market_feed_id",
        "ingestion_events",
        ["market_feed_id"],
    )
    op.create_index(
        "ix_ingestion_events_agent_id",
        "ingestion_events",
        ["agent_id"],
    )


def downgrade() -> None:
    op.drop_table("ingestion_events")
