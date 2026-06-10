# Test and acceptance runbook

## Automated

- Python domain and API tests
- TypeScript unit tests and production build
- config validation parity fixtures
- adapter contract tests
- stale data and completed-candle tests

## Demo

1. Log in.
2. Create a bot.
3. Validate and activate its config.
4. Start the fake or MT5 agent with the bot ID.
5. Observe heartbeat, account, symbol, ticks, candles, and signals.
6. Stop the agent and verify `OFFLINE/STALE`.
7. Restart Docker services and verify persistent bot/config/signal history.

Acceptance requires that no endpoint, UI action, or agent interface can place
or mutate an order.

