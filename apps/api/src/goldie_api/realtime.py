import asyncio
import json
import logging
from collections.abc import Mapping

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from .settings import get_settings
from .websocket import manager

EVENT_CHANNEL = "goldie:events"
OVERVIEW_CACHE_KEY = "collector:overview:v2"
logger = logging.getLogger(__name__)


def redis_client() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )


def invalidate_collector_overview() -> None:
    try:
        redis_client().delete(OVERVIEW_CACHE_KEY)
    except RedisError:
        pass


def publish_event_sync(payload: Mapping) -> bool:
    try:
        redis_client().publish(EVENT_CHANNEL, json.dumps(dict(payload)))
        return True
    except RedisError:
        return False


async def publish_event(payload: Mapping) -> None:
    published = await asyncio.to_thread(publish_event_sync, payload)
    if not published:
        await manager.broadcast(payload)


async def relay_redis_events(stop: asyncio.Event) -> None:
    while not stop.is_set():
        client = AsyncRedis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=1,
        )
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(EVENT_CHANNEL)
            while not stop.is_set():
                message = await pubsub.get_message(timeout=1)
                if message and message.get("data"):
                    await manager.broadcast(json.loads(message["data"]))
        except (RedisError, OSError, ValueError):
            logger.warning("Redis event relay unavailable; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
        finally:
            await pubsub.aclose()
            await client.aclose()
