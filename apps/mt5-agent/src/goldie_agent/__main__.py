import logging
import time
from datetime import UTC, datetime

from .adapters import create_adapter
from .client import ApiClient
from .settings import AgentSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("goldie-agent")


def with_identity(model, agent_id, bot_id) -> dict:
    return {
        "agent_id": str(agent_id),
        "bot_id": str(bot_id),
        **model.model_dump(mode="json"),
    }


def run() -> None:
    settings = AgentSettings()
    client = ApiClient(settings)
    adapter = create_adapter(settings)
    agent_id = client.register(settings.bot_id, settings.agent_name, settings.agent_mode)
    sent_candles: set[tuple[str, str, str]] = set()
    last_heartbeat = 0.0
    last_metadata = 0.0

    while True:
        try:
            adapter.connect()
            logger.info("Connected using %s adapter", settings.agent_mode)
            while True:
                now = time.monotonic()
                if now - last_heartbeat >= settings.heartbeat_seconds:
                    client.post(
                        f"/api/v1/agents/{agent_id}/heartbeat",
                        {
                            "status": "ONLINE",
                            "details": {"read_only": True},
                            "observed_at": datetime.now(UTC).isoformat(),
                        },
                    )
                    last_heartbeat = now
                if now - last_metadata >= settings.metadata_seconds:
                    client.post(
                        "/api/v1/market/account-snapshots",
                        with_identity(adapter.account(), agent_id, settings.bot_id),
                    )
                    client.post(
                        "/api/v1/market/symbol-specifications",
                        with_identity(adapter.symbol(), agent_id, settings.bot_id),
                    )
                    last_metadata = now
                client.post(
                    "/api/v1/market/ticks",
                    with_identity(adapter.tick(), agent_id, settings.bot_id),
                )
                for candle in adapter.completed_m1_candles(10):
                    candle_key = (
                        candle.symbol,
                        candle.timeframe,
                        candle.opened_at.isoformat(),
                    )
                    if candle_key in sent_candles:
                        continue
                    client.post(
                        "/api/v1/market/candles",
                        with_identity(candle, agent_id, settings.bot_id),
                    )
                    sent_candles.add(candle_key)
                time.sleep(settings.poll_seconds)
        except KeyboardInterrupt:
            adapter.close()
            return
        except Exception as exc:
            logger.exception("Agent loop failed: %s", exc)
            try:
                client.post(
                    f"/api/v1/agents/{agent_id}/heartbeat",
                    {
                        "status": "ERROR",
                        "details": {"error": type(exc).__name__},
                        "observed_at": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception:
                logger.warning("Could not report agent error")
            adapter.close()
            time.sleep(min(max(settings.heartbeat_seconds, 5), 30))


if __name__ == "__main__":
    run()
