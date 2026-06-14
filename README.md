# Goldie

Read-only multi-market trading research platform. The hosted shadow/paper
platform provides a Next.js control UI, FastAPI API, PostgreSQL persistence, a
deterministic signal engine, and a 24/7 OANDA market-data collector.
Historical M1 backtests run asynchronously through a PostgreSQL-backed worker
and use the same strategy domain as hosted shadow evaluation.

No order placement API or execution code exists in this phase.

## Custom strategies

Strategies live in
`packages/trading-domain/src/goldie_domain/strategies/`. Each module defines:

- a Pydantic parameter model with defaults and validation bounds;
- a unique `name`, description, and `required_candles` calculation;
- `evaluate(context, config)`, returning a `SignalDecision`;
- diagnostic indicator values in `SignalDecision.inputs`.

Register the strategy once in
`packages/trading-domain/src/goldie_domain/registry.py`. It then appears in
`GET /api/v1/strategies` and is available without a database migration in the
bot editor, Shadow/Paper evaluation, and Backtests. Shared SMA, EMA, RSI, ATR,
Bollinger Bands, momentum, and percentage-change helpers are in
`goldie_domain.indicators`.

## Redis ingestion

Deploy `railway/ingestion-worker.toml` as a separate Railway service with the
same `DATABASE_URL` and `REDIS_URL` as the API. Keep the collector on
`INGESTION_TRANSPORT=http` during deployment, then switch it to `redis` after
the `goldie:ingestion-worker:heartbeat` key appears. `INGESTION_REDIS_URL`
should use Railway private networking. HTTP remains the automatic fallback if
Redis is unavailable.

## Quick start

1. Copy `.env.example` to `.env` and change all secrets.
2. Start the platform:

   ```powershell
   docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
   ```

3. Open `http://localhost:3000`.
4. Create a bot and activate its configuration.
5. Open `Backtests` to queue a historical experiment from stored M1 candles.
6. Start the OANDA collector after configuring its credentials:

   ```powershell
   uv sync --all-packages
   $env:GOLDIE_API_URL="http://localhost:8000"
   $env:GOLDIE_AGENT_TOKEN="<same value as AGENT_SERVICE_TOKEN>"
   $env:GOLDIE_INSTRUMENTS="EUR_USD,GBP_USD,USD_JPY"
   $env:GOLDIE_OANDA_API_TOKEN="<OANDA practice token>"
   $env:GOLDIE_OANDA_ACCOUNT_ID="<OANDA practice account ID>"
   uv run --package goldie-market-data-collector python -m goldie_collector
   ```

Detailed setup and acceptance checks are in
[`docs/implementation`](docs/implementation/00_LOCAL_MVP_ROADMAP.md).

Railway deployment is documented in
[`09_RAILWAY_HOSTED_SHADOW.md`](docs/implementation/09_RAILWAY_HOSTED_SHADOW.md).

Stage II managed database purchasing requirements are in
[`docs/implementation/09_STAGE_II_MANAGED_DATABASE_REQUIREMENTS.md`](docs/implementation/09_STAGE_II_MANAGED_DATABASE_REQUIREMENTS.md).

Railway Hobby deployment instructions are in
[`docs/implementation/10_RAILWAY_DEPLOYMENT.md`](docs/implementation/10_RAILWAY_DEPLOYMENT.md).

Shadow trade outcome rules, Railway migration checks and quality gates are in
[`docs/implementation/12_SHADOW_OUTCOME_EVALUATION.md`](docs/implementation/12_SHADOW_OUTCOME_EVALUATION.md).
