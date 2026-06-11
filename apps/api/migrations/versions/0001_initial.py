"""Initial read-only platform schema."""

from alembic import op
from goldie_api import models  # noqa: F401
from goldie_api.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

INITIAL_TABLE_NAMES = {
    "users",
    "bots",
    "config_versions",
    "runs",
    "agents",
    "account_snapshots",
    "symbol_specifications",
    "market_ticks",
    "candles",
    "signals",
    "audit_events",
}


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in INITIAL_TABLE_NAMES:
            table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in INITIAL_TABLE_NAMES:
            table.drop(bind=bind)
