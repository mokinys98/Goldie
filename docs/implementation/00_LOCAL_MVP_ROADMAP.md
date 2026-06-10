# Local MVP roadmap

## Goal

Deliver a local, read-only vertical slice: login, bot creation, versioned
configuration, MT5/fake market data, monitoring, and theoretical signals.

## Delivery gates

1. **Platform:** Docker services are healthy and migrations complete.
2. **Configuration:** a bot can activate an immutable validated config.
3. **Agent:** fake and MT5 adapters publish the same canonical data models.
4. **Signals:** only completed M1 candles can produce a decision.
5. **UI:** stale/offline state is visible and no execution action exists.
6. **Acceptance:** restart preserves state and the full demo flow passes.

Deferred: orders, positions, live/demo execution, portfolio risk, backtests,
OIDC, production hosting, and full incident management.

