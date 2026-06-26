from goldie_collector.__main__ import CollectorSupervisor


class FakeControlClient:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str, str | None]] = []

    def update_command(
        self,
        command_id: str,
        status: str,
        *,
        error: str | None = None,
        **_kwargs,
    ) -> None:
        self.updates.append((command_id, status, error))


class FakeThread:
    def __init__(self, *, target, args, name: str, daemon: bool) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started


def command(command_id: str, feed_id: str) -> dict:
    return {
        "id": command_id,
        "command": "BACKFILL",
        "market_feed_id": feed_id,
        "payload": {
            "start": "2026-06-01T00:00:00+00:00",
            "end": "2026-06-02T00:00:00+00:00",
        },
    }


def resume_command(command_id: str, feed_id: str | None = None) -> dict:
    return {
        "id": command_id,
        "command": "RESUME",
        "market_feed_id": feed_id,
        "payload": {},
    }


def test_backfills_can_run_for_different_feeds(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldie_collector.__main__.threading.Thread",
        FakeThread,
    )
    supervisor = object.__new__(CollectorSupervisor)
    supervisor.feed_symbols = {
        "feed-usd-jpy": "USD_JPY",
        "feed-usd-chf": "USD_CHF",
    }
    supervisor.workers = {}
    supervisor.backfill_threads = {}
    supervisor.control_client = FakeControlClient()

    supervisor.handle_command(command("jpy-command", "feed-usd-jpy"))
    supervisor.handle_command(command("chf-command", "feed-usd-chf"))

    assert set(supervisor.backfill_threads) == {"USD_JPY", "USD_CHF"}
    assert supervisor.control_client.updates == []


def test_second_backfill_for_same_feed_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldie_collector.__main__.threading.Thread",
        FakeThread,
    )
    supervisor = object.__new__(CollectorSupervisor)
    supervisor.feed_symbols = {"feed-usd-chf": "USD_CHF"}
    supervisor.workers = {}
    supervisor.backfill_threads = {}
    supervisor.control_client = FakeControlClient()

    supervisor.handle_command(command("first-command", "feed-usd-chf"))
    supervisor.handle_command(command("second-command", "feed-usd-chf"))

    assert supervisor.control_client.updates == [
        (
            "second-command",
            "FAILED",
            "Another backfill is active for this feed",
        )
    ]


def test_single_feed_resume_clears_global_pause_in_supervisor() -> None:
    supervisor = object.__new__(CollectorSupervisor)
    supervisor.feed_symbols = {"feed-eur-usd": "oanda:practice:EUR_USD"}
    supervisor.workers = {}
    supervisor.backfill_threads = {}
    supervisor.control_client = FakeControlClient()
    supervisor.globally_paused = True
    supervisor.paused = {"oanda:practice:EUR_USD"}

    supervisor.handle_command(resume_command("resume-command", "feed-eur-usd"))

    assert supervisor.globally_paused is False
    assert supervisor.paused == set()
    assert supervisor.control_client.updates == [
        ("resume-command", "SUCCEEDED", None)
    ]
