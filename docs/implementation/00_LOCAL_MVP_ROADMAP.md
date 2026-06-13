# Local MVP roadmap

## Goal

Deliver a hosted, read-only vertical slice: login, bot creation, versioned
configuration, OANDA market data, monitoring, and theoretical signals.

## Delivery gates

1. **Platform:** Docker services are healthy and migrations complete.
2. **Configuration:** a bot can activate an immutable validated config.
3. **Collector:** OANDA quotes and completed M1 candles use canonical models.
4. **Signals:** only completed M1 candles can produce a decision.
5. **UI:** stale/offline state is visible and no execution action exists.
6. **Acceptance:** restart preserves state and the full demo flow passes.

Deferred: orders, positions, live/demo execution, portfolio risk, backtests,
OIDC, production hosting, and full incident management.

## Hosted shadow/paper continuation

The control plane and OANDA Practice market-data collector run continuously on
Railway. Market data is stored once per provider feed and shared by bots.
Execution remains out of scope until a separate provider-neutral paper/live
execution design is approved.
