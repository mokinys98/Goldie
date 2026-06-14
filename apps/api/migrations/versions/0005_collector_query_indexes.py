"""Add indexes used by collector dashboard queries."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {
        table: {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        for table in ("market_ticks", "candles", "agents", "collector_commands")
    }
    definitions = (
        ("ix_market_ticks_feed_observed_at", "market_ticks", ["market_feed_id", "observed_at"]),
        ("ix_candles_feed_opened_at", "candles", ["market_feed_id", "opened_at"]),
        ("ix_agents_feed_updated_at", "agents", ["market_feed_id", "updated_at"]),
        (
            "ix_collector_commands_feed_created_at",
            "collector_commands",
            ["market_feed_id", "created_at"],
        ),
    )
    for name, table, columns in definitions:
        if name not in indexes[table]:
            op.create_index(name, table, columns)


def downgrade() -> None:
    definitions = (
        ("ix_collector_commands_feed_created_at", "collector_commands"),
        ("ix_agents_feed_updated_at", "agents"),
        ("ix_candles_feed_opened_at", "candles"),
        ("ix_market_ticks_feed_observed_at", "market_ticks"),
    )
    inspector = sa.inspect(op.get_bind())
    for name, table in definitions:
        if name in {item["name"] for item in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
