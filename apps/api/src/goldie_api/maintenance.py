from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from .db import SessionLocal
from .models import MarketTick
from .settings import get_settings


def prune_market_quotes() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().quote_retention_days)
    with SessionLocal() as db:
        result = db.execute(delete(MarketTick).where(MarketTick.received_at < cutoff))
        db.commit()
        return result.rowcount or 0


if __name__ == "__main__":
    print(f"Deleted {prune_market_quotes()} expired market quotes")
