import os
import time

from redis import Redis
from redis.exceptions import RedisError

from goldie_api.backtests import (
    claim_next_backtest,
    execute_backtest,
    reset_interrupted_backtests,
)
from goldie_api.db import SessionLocal


def main() -> None:
    client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    with SessionLocal() as db:
        reset_interrupted_backtests(db)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe("goldie:backtests")
    except RedisError:
        pubsub = None
    while True:
        try:
            client.set("goldie:worker:heartbeat", str(time.time()), ex=30)
        except RedisError:
            pass
        experiment_id = None
        with SessionLocal() as db:
            experiment_id = claim_next_backtest(db)
        if experiment_id is not None:
            with SessionLocal() as db:
                execute_backtest(db, experiment_id)
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
