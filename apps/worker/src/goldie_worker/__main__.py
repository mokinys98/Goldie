import os
import time

from redis import Redis


def main() -> None:
    client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    while True:
        client.set("goldie:worker:heartbeat", str(time.time()), ex=30)
        time.sleep(10)


if __name__ == "__main__":
    main()
