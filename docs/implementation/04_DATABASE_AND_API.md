# Database and API

Core tables: users, bots, config_versions, runs, agents, account_snapshots,
symbol_specifications, ticks, candles, signals, and audit_events.

All IDs are UUID, timestamps are UTC, and financial values use decimal
columns. Config versions, signals, and audit events are append-only.

REST is authoritative for commands and history. WebSocket `/api/v1/stream`
publishes heartbeat, tick, candle, signal, and bot-status events.

Errors use:

```json
{"error":{"code":"stable_code","message":"Human readable message","details":{}}}
```

