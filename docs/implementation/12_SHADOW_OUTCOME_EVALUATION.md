# Shadow outcome evaluation

## Scope

Goldie evaluates every new `BUY` or `SELL` signal as a theoretical trade:

```text
Signal -> virtual position -> outcome -> performance metrics
```

This subsystem never sends an order to MT5 or to a broker. Web results are
labelled `SHADOW / THEORETICAL`.

## Version 1 rules

- one open shadow position per bot;
- risk is `0.25%` of `min(balance, equity)`;
- BUY opens at ask and closes at bid;
- SELL opens at bid and closes at ask;
- volume is floored to the broker `volume_step`;
- a volume below `volume_min` is skipped;
- SL and TP are evaluated before the five-minute timeout;
- a data gap longer than `stale_after_seconds` closes conservatively at SL;
- commission and additional slippage are zero in this version.

Existing configuration rows receive the new defaults when read. They are not
rewritten. Signals created before migration `0002` are not backfilled.

## Railway deployment

1. Deploy the API revision containing migration `0002`.
2. Confirm API startup completes `alembic upgrade head`.
3. Check `GET /health/ready`.
4. Redeploy the Web service with the same API URL.
5. Start the Windows agent and confirm fresh account, symbol, tick and candle data.
6. Open a bot and confirm the `Performance` tab shows `SHADOW / THEORETICAL`.

PostgreSQL verification:

```sql
select version_num from alembic_version;
select count(*) from signal_outcomes;
select bot_id, count(*)
from signal_outcomes
where status = 'OPEN'
group by bot_id
having count(*) > 1;
```

The migration is healthy when the Alembic version is `0002`, the table is
queryable and the duplicate-open-position query returns no rows.

## Observation period

Record the UTC deployment time and freeze strategy parameters for at least two
weeks. Do not compare pre-migration signals with evaluated signals.

Wait for at least 100 closed shadow trades before drawing a technical strategy
conclusion. Review:

- outcome count by run and configuration version;
- data gaps and other technical incidents;
- spread impact;
- profit factor and expectancy in money and R;
- max drawdown and consecutive losses;
- concentration by day, hour, direction or a single trade.

Treat `DATA_GAP` losses as technical quality evidence as well as conservative
performance results. Investigate them before changing strategy parameters.

## Quality gates

Progress to backtest parity only when:

- every evaluated signal links to a run and configuration version;
- no bot has more than one open shadow position;
- repeated ticks and service restarts do not duplicate outcomes;
- data-gap closures are explicit;
- outcome calculations have no unresolved critical defects;
- performance is not dominated by one day or one trade;
- the sample is large enough for profit factor and expectancy to be meaningful.

Demo execution remains out of scope until Shadow, backtest parity, cost model
and risk-manager stages are complete.
