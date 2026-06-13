"""Replace the local broker ingest schema with hosted OANDA feeds."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
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
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Revision 0001 uses live metadata. Fresh databases already have this schema.
    if "market_feeds" in inspector.get_table_names():
        return

    op.create_table(
        "market_feeds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "environment",
            "provider_symbol",
            name="uq_market_feed_provider_symbol",
        ),
    )
    op.create_index("ix_market_feeds_provider", "market_feeds", ["provider"])
    op.create_index(
        "ix_market_feeds_canonical_symbol", "market_feeds", ["canonical_symbol"]
    )

    with op.batch_alter_table("bots") as batch:
        batch.add_column(sa.Column("market_feed_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_bots_market_feed_id", "market_feeds", ["market_feed_id"], ["id"]
        )
        batch.create_index("ix_bots_market_feed_id", ["market_feed_id"])

    if "account_snapshots" in inspector.get_table_names():
        op.drop_table("account_snapshots")
    if "symbol_specifications" in inspector.get_table_names():
        op.drop_table("symbol_specifications")

    connection.execute(sa.text("DELETE FROM candles"))
    connection.execute(sa.text("DELETE FROM market_ticks"))
    connection.execute(sa.text("DELETE FROM agents"))

    with op.batch_alter_table("agents") as batch:
        batch.drop_index("ix_agents_bot_id")
        batch.drop_column("bot_id")
        batch.add_column(sa.Column("market_feed_id", sa.Uuid(), nullable=False))
        batch.create_foreign_key(
            "fk_agents_market_feed_id", "market_feeds", ["market_feed_id"], ["id"]
        )
        batch.create_index("ix_agents_market_feed_id", ["market_feed_id"])

    with op.batch_alter_table("market_ticks") as batch:
        batch.drop_index("ix_market_ticks_bot_id")
        batch.drop_column("bot_id")
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("market_feed_id", sa.Uuid(), nullable=False))
        batch.add_column(
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default="oanda",
            )
        )
        batch.create_foreign_key(
            "fk_market_ticks_market_feed_id",
            "market_feeds",
            ["market_feed_id"],
            ["id"],
        )
        batch.create_index("ix_market_ticks_market_feed_id", ["market_feed_id"])
        batch.create_index("ix_market_ticks_received_at", ["received_at"])

    with op.batch_alter_table("candles") as batch:
        batch.drop_constraint("uq_candle", type_="unique")
        batch.drop_index("ix_candles_bot_id")
        batch.drop_column("bot_id")
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("market_feed_id", sa.Uuid(), nullable=False))
        batch.add_column(
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default="oanda",
            )
        )
        batch.create_foreign_key(
            "fk_candles_market_feed_id",
            "market_feeds",
            ["market_feed_id"],
            ["id"],
        )
        batch.create_index("ix_candles_market_feed_id", ["market_feed_id"])
        batch.create_index("ix_candles_received_at", ["received_at"])
        batch.create_unique_constraint(
            "uq_feed_candle",
            ["market_feed_id", "symbol", "timeframe", "opened_at"],
        )

    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("initial_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("available_cash", sa.Numeric(20, 8), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id"),
    )
    op.create_index("ix_paper_accounts_bot_id", "paper_accounts", ["bot_id"])

    op.create_table(
        "instrument_specifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_feed_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=64), nullable=False),
        sa.Column("display_precision", sa.Integer(), nullable=False),
        sa.Column("pip_location", sa.Integer(), nullable=False),
        sa.Column("point", sa.Numeric(20, 10), nullable=False),
        sa.Column("minimum_trade_size", sa.Numeric(20, 8), nullable=True),
        sa.Column("trade_units_precision", sa.Integer(), nullable=True),
        sa.Column("margin_rate", sa.Numeric(20, 10), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["market_feed_id"], ["market_feeds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_instrument_specifications_market_feed_id",
        "instrument_specifications",
        ["market_feed_id"],
    )

    bots = sa.table(
        "bots",
        sa.column("id", sa.Uuid()),
        sa.column("mode", sa.String()),
    )
    paper_accounts = sa.table(
        "paper_accounts",
        sa.column("id", sa.Uuid()),
        sa.column("bot_id", sa.Uuid()),
        sa.column("currency", sa.String()),
        sa.column("initial_balance", sa.Numeric()),
        sa.column("balance", sa.Numeric()),
        sa.column("equity", sa.Numeric()),
        sa.column("available_cash", sa.Numeric()),
    )
    for bot_id in connection.execute(
        sa.select(bots.c.id).where(bots.c.mode == "PAPER")
    ).scalars():
        connection.execute(
            paper_accounts.insert().values(
                id=uuid.uuid4(),
                bot_id=bot_id,
                currency="USD",
                initial_balance=10000,
                balance=10000,
                equity=10000,
                available_cash=10000,
            )
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade to the removed local broker schema is not supported")
