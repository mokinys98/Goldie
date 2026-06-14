import json
import logging
import os
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

from goldie_api.ingestion import process_candle_batch, process_quote_batch
from goldie_api.realtime import publish_event_sync
from goldie_api.schemas import FeedCandleBatch, FeedQuoteBatch
from fastapi import HTTPException
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError, ResponseError

STREAM = "goldie:ingestion:v1"
GROUP = "goldie-ingestion"
DEAD_LETTER_STREAM = "goldie:ingestion:dead-letter:v1"
logger = logging.getLogger("goldie-ingestion-worker")


def ensure_group(client: Redis) -> None:
    try:
        client.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def decode(fields: dict) -> tuple[uuid.UUID, str, FeedQuoteBatch | FeedCandleBatch]:
    event_type = fields["event_type"]
    feed_id = uuid.UUID(fields["market_feed_id"])
    payload = json.loads(fields["payload"])
    if event_type == "quote_batch":
        return feed_id, event_type, FeedQuoteBatch.model_validate(payload)
    if event_type == "candle_batch":
        return feed_id, event_type, FeedCandleBatch.model_validate(payload)
    raise ValueError(f"Unsupported ingestion event type: {event_type}")


def process_message(client: Redis, message_id: str, fields: dict) -> None:
    try:
        feed_id, event_type, payload = decode(fields)
        if event_type == "quote_batch":
            _, event = process_quote_batch(feed_id, payload)
        else:
            _, event = process_candle_batch(feed_id, payload)
        if event:
            publish_event_sync(event)
        client.xack(STREAM, GROUP, message_id)
    except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.exception("Failed to process ingestion event %s", message_id)
        client.xadd(
            DEAD_LETTER_STREAM,
            {
                "source_stream": STREAM,
                "source_id": message_id,
                "failed_at": datetime.now(UTC).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
                "fields": json.dumps(fields),
            },
        )
        client.xack(STREAM, GROUP, message_id)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        logger.error("Rejected ingestion event %s: %s", message_id, exc.detail)
        client.xadd(
            DEAD_LETTER_STREAM,
            {
                "source_stream": STREAM,
                "source_id": message_id,
                "failed_at": datetime.now(UTC).isoformat(),
                "error": f"HTTP {exc.status_code}: {exc.detail}",
                "fields": json.dumps(fields),
            },
        )
        client.xack(STREAM, GROUP, message_id)


def reclaim_pending(client: Redis, consumer: str) -> None:
    start = "0-0"
    while True:
        next_id, messages, _ = client.xautoclaim(
            STREAM,
            GROUP,
            consumer,
            min_idle_time=60_000,
            start_id=start,
            count=100,
        )
        for message_id, fields in messages:
            try:
                process_message(client, message_id, fields)
            except Exception:
                logger.exception("Pending ingestion event remains unacknowledged")
        if not messages or next_id == "0-0":
            return
        start = next_id


def trim_acknowledged(client: Redis) -> None:
    cutoff_ms = int((datetime.now(UTC) - timedelta(hours=72)).timestamp() * 1000)
    pending = client.xpending_range(STREAM, GROUP, "-", "+", 1)
    threshold_ms = cutoff_ms
    if pending:
        threshold_ms = min(threshold_ms, int(str(pending[0]["message_id"]).split("-", 1)[0]))
    client.xtrim(STREAM, minid=f"{threshold_ms}-0", approximate=False)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    consumer = os.getenv("INGESTION_CONSUMER_NAME", socket.gethostname())
    ensure_group(client)
    reclaim_pending(client, consumer)
    last_trim = 0.0
    last_reclaim = time.monotonic()
    while True:
        try:
            client.set("goldie:ingestion-worker:heartbeat", str(time.time()), ex=30)
            messages = client.xreadgroup(
                GROUP,
                consumer,
                {STREAM: ">"},
                count=100,
                block=2_000,
            )
            for _, entries in messages:
                for message_id, fields in entries:
                    try:
                        process_message(client, message_id, fields)
                    except Exception:
                        logger.exception("Ingestion event remains unacknowledged")
            if time.monotonic() - last_reclaim >= 60:
                reclaim_pending(client, consumer)
                last_reclaim = time.monotonic()
            if time.monotonic() - last_trim >= 3600:
                trim_acknowledged(client)
                last_trim = time.monotonic()
        except RedisError:
            logger.exception("Redis ingestion loop failed")
            time.sleep(2)


if __name__ == "__main__":
    main()
