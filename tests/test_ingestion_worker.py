import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
sys.path.insert(
    0,
    str(Path(__file__).parents[1] / "apps" / "ingestion-worker" / "src"),
)

from goldie_ingestion_worker import __main__ as worker


class FakeRedis:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def xack(self, *_args) -> None:
        self.events.append("ack")

    def xadd(self, *_args, **_kwargs) -> None:
        self.events.append("dead-letter")


def quote_fields() -> dict[str, str]:
    event_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    return {
        "event_type": "quote_batch",
        "market_feed_id": str(uuid.uuid4()),
        "payload": json.dumps(
            {
                "event_id": str(event_id),
                "agent_id": str(agent_id),
                "sent_at": datetime.now(UTC).isoformat(),
                "quotes": [
                    {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "bid": "1.08",
                        "ask": "1.081",
                    }
                ],
            }
        ),
    }


def test_worker_acknowledges_only_after_commit_and_publish(monkeypatch) -> None:
    events: list[str] = []

    def process(*_args):
        events.append("commit")
        return {"accepted": True}, {"event_type": "market.quote"}

    monkeypatch.setattr(worker, "process_quote_batch", process)
    monkeypatch.setattr(worker, "publish_event_sync", lambda _event: events.append("publish"))

    worker.process_message(FakeRedis(events), "1-0", quote_fields())

    assert events == ["commit", "publish", "ack"]


def test_transient_failure_remains_pending(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        worker,
        "process_quote_batch",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        worker.process_message(FakeRedis(events), "1-0", quote_fields())

    assert "ack" not in events


def test_invalid_event_is_dead_lettered_and_acknowledged() -> None:
    events: list[str] = []
    worker.process_message(FakeRedis(events), "1-0", {"event_type": "unknown"})
    assert events == ["dead-letter", "ack"]
