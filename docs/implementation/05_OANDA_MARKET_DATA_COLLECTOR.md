# OANDA market-data collector

The collector registers one OANDA Practice feed and publishes:

- collector and market heartbeat;
- provider-neutral instrument specification;
- throttled bid/ask quotes;
- completed midpoint M1 candles.

On first startup it backfills up to 30 days of M1 history. Later restarts begin
after the newest stored candle, and the API deduplicates candles by feed,
symbol, timeframe, and opening time.

The pricing stream is sampled at five-second intervals before persistence.
When the market is closed, heartbeat status is `MARKET_CLOSED`. On failures the
collector reports `DEGRADED`, reconnects with exponential backoff and jitter,
and never fabricates fresh data.

The collector contains no account balance import, order, position, or execution
interface. PAPER balances belong to Goldie paper accounts.
