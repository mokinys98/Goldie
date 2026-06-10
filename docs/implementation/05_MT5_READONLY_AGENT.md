# MT5 read-only agent

The agent registers with a service token and bot ID, sends heartbeat, account
snapshot, symbol specification, tick, and completed M1 candles.

Adapters:

- `FakeBrokerAdapter` for deterministic local development.
- `Mt5ReadOnlyAdapter` for the installed Windows terminal.

The MT5 adapter uses account, symbol, tick, and rates read APIs only. There is
no order, position mutation, or execution interface in this MVP.

On failure it reports an unhealthy heartbeat, backs off, reconnects, and never
fabricates fresh market data.

