# Local architecture

```text
Browser -> Next.js -> FastAPI -> PostgreSQL
                      |   |
                      |   +-> Redis (reserved for jobs/fan-out)
                      |
Windows agent --------+-> REST ingest + WebSocket broadcast
  Fake adapter or MetaTrader 5 terminal
```

PostgreSQL is the source of truth. WebSocket messages are transient
notifications; clients recover through REST. The agent is read-only and
cannot receive or submit trading commands.

Startup order: PostgreSQL/Redis, API/migrations, web, then Windows agent.
Shutdown order: agent, web/worker/API, then data services.

