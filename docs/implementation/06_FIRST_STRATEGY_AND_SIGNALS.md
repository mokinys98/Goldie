# First strategy and signals

`basic_momentum` compares the latest completed M1 close with the close
`lookback_candles` earlier.

- positive threshold: `BUY`
- negative threshold: `SELL`
- otherwise: `NO_TRADE`

Data staleness, excessive spread, and inactive session override the strategy
with `NO_TRADE`. Proposed SL/TP are theoretical and no order is created.
Every decision stores inputs, reason code, config version, and timestamp.

