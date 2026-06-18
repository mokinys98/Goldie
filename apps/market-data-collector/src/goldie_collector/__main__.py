import logging
import random
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

from .client import GoldieApiClient
from .provider import OandaConfigurationError, OandaProvider
from .settings import CollectorSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("goldie-market-data-collector")
backfill_locks: dict[str, threading.Lock] = {}
backfill_locks_guard = threading.Lock()


def backfill_lock(symbol: str) -> threading.Lock:
    with backfill_locks_guard:
        return backfill_locks.setdefault(symbol, threading.Lock())


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def run_backfill(
    settings: CollectorSettings,
    client: GoldieApiClient,
    provider: OandaProvider,
    start: datetime,
    end: datetime,
    *,
    command_id: str | None = None,
) -> datetime:
    with backfill_lock(settings.provider_symbol):
        candles = provider.candles(start, end)
        total = len(candles)
        accepted = 0
        duplicates = 0
        size = settings.backfill_batch_size
        for index in range(0, total, size):
            result = client.candles(candles[index : index + size])
            accepted += int(result.get("count", 0))
            duplicates += int(result.get("duplicates", 0))
            if command_id:
                client.update_command(
                    command_id,
                    "RUNNING",
                    progress={
                        "processed": min(index + size, total),
                        "total": total,
                        "accepted": accepted,
                        "duplicates": duplicates,
                    },
                )
        if command_id:
            client.update_command(
                command_id,
                "SUCCEEDED",
                progress={
                    "processed": total,
                    "total": total,
                    "accepted": accepted,
                    "duplicates": duplicates,
                },
                result={"accepted": accepted, "duplicates": duplicates},
            )
        return candles[-1].opened_at + timedelta(minutes=1) if candles else start


class InstrumentWorker:
    def __init__(
        self,
        settings: CollectorSettings,
        on_registered,
        collector_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.on_registered = on_registered
        self.collector_id = collector_id
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run_forever,
            name=f"collector-{settings.provider_symbol.lower()}",
            daemon=True,
        )
        self.feed_id: str | None = None
        self.status = "REGISTERED"
        self.last_error: str | None = None
        self.latest_quote_at: str | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)

    def _wait(self, seconds: float) -> bool:
        return self.stop_event.wait(seconds)

    def _run_forever(self) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            try:
                self._run()
                attempt = 0
            except OandaConfigurationError as exc:
                self.status = "ERROR"
                self.last_error = str(exc)
                logger.error("%s configuration error: %s", self.settings.provider_symbol, exc)
                if self._wait(self.settings.configuration_retry_seconds):
                    return
            except Exception as exc:
                attempt += 1
                self.status = "DEGRADED"
                self.last_error = f"{type(exc).__name__}: {exc}"
                delay = min(60, 2 ** min(attempt, 5)) + random.uniform(0, 15)
                logger.warning(
                    "Collector %s failed; retrying in %.1f seconds: %s",
                    self.settings.provider_symbol,
                    delay,
                    self.last_error,
                    exc_info=attempt == 1,
                )
                if self._wait(delay):
                    return

    def _run(self) -> None:
        client = GoldieApiClient(self.settings)
        client.set_collector_id(self.collector_id)
        provider = OandaProvider(self.settings)
        latest_candle_at = client.register(self.settings)
        self.feed_id = str(client.feed_id)
        self.on_registered(self.settings.provider_symbol, self.feed_id)
        instrument = provider.validate_instrument()
        client.instrument(instrument)
        now = datetime.now(UTC)
        start = max(
            latest_candle_at + timedelta(minutes=1)
            if latest_candle_at
            else now - timedelta(days=self.settings.backfill_days),
            now - timedelta(days=self.settings.backfill_days),
        )
        candle_cursor = run_backfill(self.settings, client, provider, start, now)
        provider.start()
        self.status = "ONLINE"
        self.last_error = None
        last_quote_sent = 0.0
        last_quote_observed_at: datetime | None = None
        last_candle_poll = 0.0
        last_heartbeat = 0.0
        try:
            while not self.stop_event.is_set():
                monotonic = time.monotonic()
                if provider.stream_error is not None:
                    raise provider.stream_error
                if monotonic - last_quote_sent >= self.settings.quote_interval_seconds:
                    quote = provider.latest_quote()
                    if quote is not None and (
                        last_quote_observed_at is None
                        or quote.observed_at > last_quote_observed_at
                    ):
                        client.quotes([quote])
                        last_quote_observed_at = quote.observed_at
                        self.latest_quote_at = quote.observed_at.isoformat()
                        last_quote_sent = monotonic
                client.flush_due()
                if monotonic - last_candle_poll >= self.settings.candle_poll_seconds:
                    current = datetime.now(UTC)
                    candles = provider.candles(candle_cursor, current)
                    if candles:
                        client.candles(candles)
                        candle_cursor = candles[-1].opened_at + timedelta(minutes=1)
                    last_candle_poll = monotonic
                if monotonic - last_heartbeat >= self.settings.heartbeat_seconds:
                    closed = provider.market_is_closed()
                    self.status = "MARKET_CLOSED" if closed else "ONLINE"
                    client.heartbeat(
                        self.status,
                        {
                            "read_only": True,
                            "provider": "oanda",
                            "latest_quote_at": self.latest_quote_at,
                            "error": self.last_error,
                        },
                    )
                    last_heartbeat = monotonic
                self.stop_event.wait(0.25)
        finally:
            client.flush_quotes()
            provider.close()


class CollectorSupervisor:
    def __init__(self, settings: CollectorSettings) -> None:
        self.base_settings = settings
        self.control_client = GoldieApiClient(settings)
        registration = self.control_client.register_instance(settings)
        self.instance_id = registration["instance"]["id"]
        self.workers: dict[str, InstrumentWorker] = {}
        self.feed_symbols: dict[str, str] = {}
        self.paused: set[str] = set()
        self.globally_paused = False
        self.applied_version: int | None = None
        self.last_error: str | None = None
        self.backfill_threads: dict[str, threading.Thread] = {}

    def on_registered(self, symbol: str, feed_id: str) -> None:
        self.feed_symbols[feed_id] = symbol

    def effective_settings(
        self,
        symbol: str,
        configuration: dict,
        overrides: dict,
    ) -> CollectorSettings:
        values = {
            key: configuration[key]
            for key in (
                "quote_interval_seconds",
                "candle_poll_seconds",
                "heartbeat_seconds",
                "backfill_days",
                "backfill_batch_size",
                "configuration_retry_seconds",
            )
        }
        values.update(overrides)
        instrument_settings = self.base_settings.for_instrument(symbol)
        return CollectorSettings.model_validate(
            instrument_settings.model_dump() | values
        )

    def reconcile(self, control: dict) -> None:
        configuration = control["configuration"]
        version = int(configuration["version"])
        desired: dict[str, CollectorSettings] = {}
        for instrument in control["instruments"]:
            symbol = instrument["provider_symbol"]
            feed_id = instrument.get("market_feed_id")
            if feed_id:
                self.feed_symbols[feed_id] = symbol
            if instrument["enabled"] and symbol not in self.paused and not self.globally_paused:
                desired[symbol] = self.effective_settings(
                    symbol,
                    configuration,
                    instrument.get("overrides") or {},
                )
        for symbol, worker in list(self.workers.items()):
            replacement = desired.get(symbol)
            if replacement is None or worker.settings != replacement:
                worker.stop()
                del self.workers[symbol]
        for symbol, settings in desired.items():
            if symbol not in self.workers:
                worker = InstrumentWorker(settings, self.on_registered, self.instance_id)
                self.workers[symbol] = worker
                worker.start()
                logger.info("Started collector worker for %s", symbol)
        self.applied_version = version

    def target_symbols(self, command: dict) -> list[str]:
        feed_id = command.get("market_feed_id")
        if feed_id:
            symbol = self.feed_symbols.get(feed_id)
            return [symbol] if symbol else []
        return list(self.workers) or self.base_settings.instrument_symbols

    def execute_backfill(self, command: dict, symbol: str) -> None:
        command_id = command["id"]
        try:
            worker = self.workers.get(symbol)
            settings = worker.settings if worker else self.base_settings.for_instrument(symbol)
            client = GoldieApiClient(settings)
            client.set_collector_id(self.instance_id)
            client.register(settings)
            provider = OandaProvider(settings)
            provider.validate_instrument()
            run_backfill(
                settings,
                client,
                provider,
                parse_time(command["payload"]["start"]),
                parse_time(command["payload"]["end"]),
                command_id=command_id,
            )
        except Exception as exc:
            logger.exception("Manual backfill failed")
            self.control_client.update_command(
                command_id,
                "FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self.backfill_threads.pop(symbol, None)

    def handle_command(self, command: dict) -> None:
        command_id = command["id"]
        symbols = self.target_symbols(command)
        if not symbols:
            self.control_client.update_command(
                command_id,
                "FAILED",
                error="Target feed is not registered by this collector",
            )
            return
        action = command["command"]
        if action == "PAUSE":
            if command.get("market_feed_id"):
                self.paused.update(symbols)
            else:
                self.globally_paused = True
            for symbol in symbols:
                worker = self.workers.pop(symbol, None)
                if worker:
                    worker.stop()
            self.control_client.update_command(
                command_id,
                "SUCCEEDED",
                result={"symbols": symbols},
            )
        elif action == "RESUME":
            if command.get("market_feed_id"):
                self.paused.difference_update(symbols)
            else:
                self.globally_paused = False
                self.paused.clear()
            self.control_client.update_command(
                command_id,
                "SUCCEEDED",
                result={"symbols": symbols},
            )
        elif action == "RECONNECT":
            for symbol in symbols:
                worker = self.workers.pop(symbol, None)
                if worker:
                    worker.stop()
            self.control_client.update_command(
                command_id,
                "SUCCEEDED",
                result={"symbols": symbols},
            )
        elif action == "BACKFILL":
            active_thread = self.backfill_threads.get(symbols[0])
            if active_thread and active_thread.is_alive():
                self.control_client.update_command(
                    command_id,
                    "FAILED",
                    error="Another backfill is active for this feed",
                )
                return
            thread = threading.Thread(
                target=self.execute_backfill,
                args=(command, symbols[0]),
                name=f"collector-manual-backfill-{symbols[0].lower()}",
                daemon=True,
            )
            self.backfill_threads[symbols[0]] = thread
            thread.start()

    def heartbeat(self) -> None:
        statuses = {symbol: worker.status for symbol, worker in self.workers.items()}
        errors = {
            symbol: worker.last_error
            for symbol, worker in self.workers.items()
            if worker.last_error
        }
        if self.globally_paused:
            status = "PAUSED"
        elif errors:
            status = "DEGRADED"
        else:
            status = "ONLINE"
        self.control_client.instance_heartbeat(
            self.instance_id,
            status,
            self.applied_version,
            {
                "worker_count": len(self.workers),
                "workers": statuses,
                "paused_symbols": sorted(self.paused),
                "errors": errors,
                "read_only": True,
            },
        )

    def run(self) -> None:
        while True:
            try:
                control = self.control_client.poll_control(self.instance_id)
                for instrument in control["instruments"]:
                    if instrument.get("market_feed_id"):
                        self.feed_symbols[instrument["market_feed_id"]] = instrument[
                            "provider_symbol"
                        ]
                for command in control["commands"]:
                    self.handle_command(command)
                self.reconcile(control)
                self.heartbeat()
                self.last_error = None
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Collector control loop failed")
            time.sleep(5)


def main() -> None:
    CollectorSupervisor(CollectorSettings()).run()


if __name__ == "__main__":
    main()
