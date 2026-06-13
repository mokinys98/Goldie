# Test and acceptance runbook

## Automated

- Python domain and API tests
- TypeScript unit tests and production build
- config validation parity fixtures
- OANDA provider contract tests
- stale data and completed-candle tests

## Demo

1. Log in.
2. Create a bot.
3. Validate and activate its config.
4. Start the OANDA collector.
5. Assign its feed and observe heartbeat, quotes, candles, and signals.
6. Stop the collector and verify `OFFLINE/STALE`.
7. Restart Docker services and verify persistent bot/config/signal history.

Acceptance requires that no endpoint, UI action, or agent interface can place
or mutate an order.
