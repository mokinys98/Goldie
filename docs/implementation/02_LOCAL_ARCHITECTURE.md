# Local architecture

```text
OANDA Practice API -> market-data collector -> FastAPI -> PostgreSQL
Browser -> Next.js ----------------------------^   |
                                                   +-> WebSocket broadcast
```

PostgreSQL is the source of truth. WebSocket messages are transient
notifications; clients recover through REST. The collector is read-only and
has no trading command interface.

Startup order: PostgreSQL, API/migrations, web, then collector.
Shutdown order: collector, web/API, then PostgreSQL.

## Hosted architecture

```text
OANDA Practice API -> Railway market-data collector -> FastAPI -> PostgreSQL
                                                        |
Browser -> Railway Next.js -----------------------------+
```

Strategies consume canonical database models and never call OANDA directly.
Any future execution capability must be a separate provider-neutral subsystem
behind centralized risk controls.
