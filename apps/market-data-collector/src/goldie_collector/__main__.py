import logging
import random
import threading
import time
from datetime import UTC, datetime, timedelta

from .client import GoldieApiClient
from .provider import OandaConfigurationError, OandaProvider
from .settings import CollectorSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("goldie-market-data-collector")


def run_instrument(settings: CollectorSettings) -> None:
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


def instrument_worker(settings: CollectorSettings) -> None:
    attempt = 0
    while True:
        try:
            run_instrument(settings)
            attempt = 0
        except OandaConfigurationError as exc:
            delay = settings.configuration_retry_seconds
            logger.error(
                "Collector configuration error; retrying in %.0f seconds: %s",
                delay,
                exc,
            )
            try:
                client = GoldieApiClient(settings)
                client.register(settings)
                client.heartbeat(
                    "ERROR",
                    {
                        "error": type(exc).__name__,
                        "message": str(exc),
                        "retry_seconds": round(delay, 1),
                    },
                )
            except Exception:
                logger.warning("Could not report collector configuration failure")
            time.sleep(delay)
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


def main() -> None:
    settings = CollectorSettings()
    threads: list[threading.Thread] = []
    for provider_symbol in settings.instrument_symbols:
        instrument_settings = settings.for_instrument(provider_symbol)
        thread = threading.Thread(
            target=instrument_worker,
            args=(instrument_settings,),
            name=f"collector-{provider_symbol.lower()}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)
        logger.info("Started collector worker for %s", provider_symbol)
        time.sleep(1)

    try:
        while all(thread.is_alive() for thread in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        return
    raise RuntimeError("One or more collector workers stopped unexpectedly")


if __name__ == "__main__":
    main()
