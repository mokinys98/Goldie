import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from goldie_api.ingestion import process_candle_batch, process_quote_batch
from goldie_api.realtime import publish_event_sync
from goldie_api.schemas import FeedCandleBatch, FeedQuoteBatch
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError, ResponseError

STREAM = "goldie:ingestion:v1"
QUOTE_STREAM = "goldie:ingestion:quotes:v2"
CANDLE_STREAM = "goldie:ingestion:candles:v2"
GROUP = "goldie-ingestion"
DEAD_LETTER_STREAM = "goldie:ingestion:dead-letter:v1"
logger = logging.getLogger("goldie-ingestion-worker")


def ensure_group(client: Redis, stream: str = STREAM) -> None:
    try:
        client.xgroup_create(stream, GROUP, id="0-0", mkstream=True)
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


def process_message(
    client: Redis,
    message_id: str,
    fields: dict,
    stream: str = STREAM,
) -> None:
    started = time.monotonic()
    try:
        feed_id, event_type, payload = decode(fields)
        queue_delay_ms = max(
            0.0,
            (datetime.now(UTC) - payload.sent_at).total_seconds() * 1000,
        ) if payload.sent_at else 0.0
        if event_type == "quote_batch":
            result, event = process_quote_batch(feed_id, payload)
        else:
            result, event = process_candle_batch(feed_id, payload)
        committed_ms = (time.monotonic() - started) * 1000
        if event:
            publish_event_sync(event)
        total_ms = (time.monotonic() - started) * 1000
        log = logger.warning if event_type == "candle_batch" and total_ms > 1000 else logger.info
        log(
            "ingestion_timing event_type=%s feed_id=%s queue_delay_ms=%.2f "
            "commit_ms=%.2f publish_ms=%.2f total_ms=%.2f active_bot_count=%s dropped=%s",
            event_type,
            feed_id,
            queue_delay_ms,
            committed_ms,
            total_ms - committed_ms,
            total_ms,
            len(event.get("bot_instance_ids", [])) if event else 0,
            result.get("dropped", False),
        )
        client.xack(stream, GROUP, message_id)
    except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.exception("Failed to process ingestion event %s", message_id)
        client.xadd(
            DEAD_LETTER_STREAM,
            {
                "source_stream": stream,
                "source_id": message_id,
                "failed_at": datetime.now(UTC).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
                "fields": json.dumps(fields),
            },
        )
        client.xack(stream, GROUP, message_id)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        logger.error("Rejected ingestion event %s: %s", message_id, exc.detail)
        client.xadd(
            DEAD_LETTER_STREAM,
            {
                "source_stream": stream,
                "source_id": message_id,
                "failed_at": datetime.now(UTC).isoformat(),
                "error": f"HTTP {exc.status_code}: {exc.detail}",
                "fields": json.dumps(fields),
            },
        )
        client.xack(stream, GROUP, message_id)


def reclaim_pending(client: Redis, consumer: str, stream: str = STREAM) -> None:
    start = "0-0"
    while True:
        next_id, messages, _ = client.xautoclaim(
            stream,
            GROUP,
            consumer,
            min_idle_time=60_000,
            start_id=start,
            count=100,
        )
        for message_id, fields in messages:
            try:
                process_message(client, message_id, fields, stream)
            except Exception:
                logger.exception("Pending ingestion event remains unacknowledged")
        if not messages or next_id == "0-0":
            return
        start = next_id


def trim_acknowledged(client: Redis, stream: str = STREAM) -> None:
    cutoff_ms = int((datetime.now(UTC) - timedelta(hours=72)).timestamp() * 1000)
    pending = client.xpending_range(stream, GROUP, "-", "+", 1)
    threshold_ms = cutoff_ms
    if pending:
        threshold_ms = min(threshold_ms, int(str(pending[0]["message_id"]).split("-", 1)[0]))
    client.xtrim(stream, minid=f"{threshold_ms}-0", approximate=False)


def redis_connection() -> Redis:
    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )


def log_stream_backlog(client: Redis, stream: str) -> None:
    groups = client.xinfo_groups(stream)
    state = next((group for group in groups if group.get("name") == GROUP), None)
    lag = int((state or {}).get("lag") or 0)
    pending = int((state or {}).get("pending") or 0)
    if lag > 100 or pending > 100:
        logger.warning(
            "ingestion_backlog stream=%s lag=%s pending=%s",
            stream,
            lag,
            pending,
        )


def consume_stream(stream: str, consumer: str, *, heartbeat: bool = False) -> None:
    client = redis_connection()
    ensure_group(client, stream)
    reclaim_pending(client, consumer, stream)
    last_trim = 0.0
    last_reclaim = time.monotonic()
    while True:
        try:
            if heartbeat:
                client.set("goldie:ingestion-worker:heartbeat", str(time.time()), ex=30)
            messages = client.xreadgroup(
                GROUP,
                consumer,
                {stream: ">"},
                count=100,
                block=2_000,
            )
            for _, entries in messages:
                for message_id, fields in entries:
                    try:
                        process_message(client, message_id, fields, stream)
                    except Exception:
                        logger.exception("Ingestion event remains unacknowledged")
            if time.monotonic() - last_reclaim >= 60:
                reclaim_pending(client, consumer, stream)
                log_stream_backlog(client, stream)
                last_reclaim = time.monotonic()
            if time.monotonic() - last_trim >= 3600:
                trim_acknowledged(client, stream)
                last_trim = time.monotonic()
        except RedisError:
            logger.exception("Redis ingestion loop failed for %s", stream)
            time.sleep(2)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    consumer = os.getenv("INGESTION_CONSUMER_NAME", socket.gethostname())
    for stream, suffix in ((CANDLE_STREAM, "candles"), (STREAM, "legacy")):
        threading.Thread(
            target=consume_stream,
            args=(stream, f"{consumer}-{suffix}"),
            daemon=True,
            name=f"ingestion-{suffix}",
        ).start()
    consume_stream(QUOTE_STREAM, f"{consumer}-quotes", heartbeat=True)


if __name__ == "__main__":
    main()
