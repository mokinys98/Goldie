import os
import time

from redis import Redis
from redis.exceptions import RedisError

from goldie_api.db import SessionLocal
from goldie_api.optimizations import (
    claim_next_optimization,
    execute_optimization,
    reset_interrupted_optimizations,
)


def main() -> None:
    client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    with SessionLocal() as db:
        reset_interrupted_optimizations(db)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe("goldie:optimizations")
    except RedisError:
        pubsub = None
    while True:
        try:
            client.set("goldie:optuna-worker:heartbeat", str(time.time()), ex=30)
        except RedisError:
            pass
        optimization_id = None
        with SessionLocal() as db:
            optimization_id = claim_next_optimization(db)
        if optimization_id is not None:
            with SessionLocal() as db:
                execute_optimization(db, optimization_id)
            continue
        if pubsub is not None:
            try:
                pubsub.get_message(timeout=2)
                continue
            except RedisError:
                pubsub = None
        time.sleep(2)


if __name__ == "__main__":
    main()
