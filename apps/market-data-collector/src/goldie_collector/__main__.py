import logging
import random
import time
from datetime import UTC, datetime, timedelta

from .client import GoldieApiClient
from .provider import OandaProvider
from .settings import CollectorSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("goldie-market-data-collector")


def run_once(settings: CollectorSettings) -> None:
    client = GoldieApiClient(settings)
    provider = OandaProvider(settings)
    latest_candle_at = client.register(settings)
    instrument = provider.validate_instrument()
    client.instrument(instrument)

    now = datetime.now(UTC)
    backfill_start = max(
        latest_candle_at + timedelta(minutes=1)
        if latest_candle_at
        else now - timedelta(days=settings.backfill_days),
        now - timedelta(days=settings.backfill_days),
    )
    backfill = provider.candles(backfill_start, now)
    for index in range(0, len(backfill), 1000):
        result = client.candles(backfill[index : index + 1000])
        logger.info(
            "Backfill batch accepted=%s duplicates=%s",
            result.get("count", 0),
            result.get("duplicates", 0),
        )

    provider.start()
    last_quote_sent = 0.0
    last_quote_observed_at: datetime | None = None
    last_candle_poll = 0.0
    last_heartbeat = 0.0
    candle_cursor = (
        backfill[-1].opened_at + timedelta(minutes=1)
        if backfill
        else backfill_start
    )
    try:
        while True:
            monotonic = time.monotonic()
            if provider.stream_error is not None:
                raise provider.stream_error

            if monotonic - last_quote_sent >= settings.quote_interval_seconds:
                quote = provider.latest_quote()
                if quote is not None and (
                    last_quote_observed_at is None
                    or quote.observed_at > last_quote_observed_at
                ):
                    client.quotes([quote])
                    last_quote_observed_at = quote.observed_at
                    last_quote_sent = monotonic

            if monotonic - last_candle_poll >= settings.candle_poll_seconds:
                current = datetime.now(UTC)
                candles = provider.candles(candle_cursor, current)
                if candles:
                    client.candles(candles)
                    candle_cursor = candles[-1].opened_at + timedelta(minutes=1)
                last_candle_poll = monotonic

            if monotonic - last_heartbeat >= settings.heartbeat_seconds:
                closed = provider.market_is_closed()
                client.heartbeat(
                    "MARKET_CLOSED" if closed else "ONLINE",
                    {
                        "read_only": True,
                        "provider": "oanda",
                        "latest_quote_at": (
                            provider.latest_quote().observed_at.isoformat()
                            if provider.latest_quote()
                            else None
                        ),
                    },
                )
                last_heartbeat = monotonic
            time.sleep(0.25)
    finally:
        provider.close()


def main() -> None:
    settings = CollectorSettings()
    attempt = 0
    while True:
        try:
            run_once(settings)
            attempt = 0
        except KeyboardInterrupt:
            return
        except Exception as exc:
            attempt += 1
            delay = min(60, 2 ** min(attempt, 5)) + random.uniform(0, 1)
            logger.exception("Collector failed; retrying in %.1f seconds", delay)
            try:
                client = GoldieApiClient(settings)
                client.register(settings)
                client.heartbeat(
                    "DEGRADED",
                    {"error": type(exc).__name__, "retry_seconds": round(delay, 1)},
                )
            except Exception:
                logger.warning("Could not report collector failure")
            time.sleep(delay)


if __name__ == "__main__":
    main()
