# Railway hosted shadow/paper

## Architecture

Create one Railway project with eight services:

1. PostgreSQL.
2. Redis.
3. `api` using `railway/api.toml`.
4. `web` using Config File `/railway/web.toml`, with Railway Root Directory
   set to `/apps/web`.
5. `market-data-collector` using `railway/collector.toml`.
6. `ingestion-worker` using `railway/ingestion-worker.toml`.
7. `worker` using `railway/worker.toml`.
8. `maintenance` using `railway/maintenance.toml`.

PostgreSQL is the system of record. Redis is used for market-data transport,
short-lived dashboard cache, backtest wake-ups, and WebSocket event fan-out.

The collector can use HTTP or Redis Streams. The dedicated ingestion worker
consumes Stream events and writes them to PostgreSQL. The separate `worker`
service executes asynchronous backtests, so long backtests cannot block market
data ingestion.

Keep one collector replica per configured feed set. Start API, ingestion
worker, backtest worker, and maintenance with one replica each. Scale only
after checking PostgreSQL connections and Redis consumer behavior.

## Variables

Use Railway reference variables from autocomplete instead of manually copying
private PostgreSQL or Redis credentials.

API:

```text
DATABASE_URL=<Railway PostgreSQL URL using postgresql+psycopg://>
REDIS_URL=<Railway private Redis URL>
JWT_SECRET=<long random value>
LOCAL_ADMIN_EMAIL=<admin email>
LOCAL_ADMIN_PASSWORD=<strong password>
AGENT_SERVICE_TOKEN=<long random shared service token>
CORS_ORIGINS=https://<web-domain>
QUOTE_RETENTION_DAYS=30
```

The API startup command runs `alembic upgrade head` before Uvicorn. Confirm
that migration `0007` created `ingestion_events` before enabling Redis
ingestion.

Backtest worker:

```text
DATABASE_URL=<same private PostgreSQL URL as API>
REDIS_URL=<same private Redis URL as API>
```

Ingestion worker:

```text
DATABASE_URL=<same private PostgreSQL URL as API>
REDIS_URL=<same private Redis URL as API>
INGESTION_CONSUMER_NAME=railway-ingestion-1
```

`INGESTION_CONSUMER_NAME` is optional with one replica. Every horizontally
scaled ingestion worker must have a unique consumer name.

Web:

```text
NEXT_PUBLIC_API_URL=https://<api-domain>
NEXT_PUBLIC_WS_URL=wss://<api-domain>
```

Collector, assuming the API service is named `api`:

```text
GOLDIE_API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
GOLDIE_AGENT_TOKEN=<same value as AGENT_SERVICE_TOKEN>
GOLDIE_PROVIDER_ENVIRONMENT=practice
GOLDIE_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY,USD_CHF,USD_CAD,AUD_USD,NZD_USD,EUR_GBP,EUR_JPY,GBP_JPY
GOLDIE_QUOTE_INTERVAL_SECONDS=5
GOLDIE_CANDLE_POLL_SECONDS=15
GOLDIE_BACKFILL_DAYS=30
GOLDIE_BACKFILL_BATCH_SIZE=250
GOLDIE_REQUEST_TIMEOUT_SECONDS=60
GOLDIE_CONFIGURATION_RETRY_SECONDS=900
GOLDIE_OANDA_API_TOKEN=<OANDA practice token>
GOLDIE_OANDA_ACCOUNT_ID=<OANDA practice account ID>
GOLDIE_OANDA_REST_URL=https://api-fxpractice.oanda.com
GOLDIE_OANDA_STREAM_URL=https://stream-fxpractice.oanda.com

INGESTION_TRANSPORT=http
INGESTION_REDIS_URL=<Railway private Redis URL>
GOLDIE_QUOTE_BATCH_SECONDS=1
GOLDIE_QUOTE_BATCH_SIZE=250
GOLDIE_CANDLE_BATCH_SIZE=500
```

Keep `INGESTION_TRANSPORT=http` during the initial deployment. Set it to
`redis` only after the ingestion worker is healthy and HTTP ingestion has been
verified.

`GOLDIE_API_URL` must point to the API service, never the Web service. In the
same Railway project and environment, use API private networking as shown
above. If the service has another name, select its `RAILWAY_PRIVATE_DOMAIN`
and `PORT` reference variables from Railway autocomplete. A wrong Web URL
returns HTTP 404 for `/api/v1/market-feeds/register`.

If OANDA returns HTTP 403, verify that:

1. the token and account ID belong to the same OANDA login;
2. `practice` accounts use `api-fxpractice` and `stream-fxpractice`;
3. the account appears in OANDA `GET /v3/accounts` for that token;
4. the account is enabled for the v20 API.

If `/v3/accounts` succeeds but
`/v3/accounts/{accountID}/instruments` returns 403, the token can see the
account but OANDA has not allowed account-scoped instrument/pricing access.
Send the OANDA `RequestID` from the collector log to `api@oanda.com`.

`GOLDIE_INSTRUMENTS` is a comma-separated list of OANDA symbols. The collector
starts an isolated worker and creates one shared Goldie feed for each symbol.
One failing symbol does not stop the remaining feeds. Keep the list to markets
that will actually have bots; one collector supports at most 20 instruments.
Initial history is serialized between instruments and uploaded in smaller
batches so one API replica is not overloaded during a 30-day backfill.

If a configured instrument is unavailable for the account, its feed heartbeat
is set to `ERROR`, the log reports the first 50 available instruments, and that
worker retries every 15 minutes instead of producing a retry storm.

Maintenance needs only `DATABASE_URL` and `QUOTE_RETENTION_DAYS`.

## Deployment order

1. Deploy PostgreSQL and Redis.
2. Deploy API and confirm that all Alembic migrations completed.
3. Deploy Web and the backtest worker.
4. Deploy the ingestion worker.
5. Deploy the collector with `INGESTION_TRANSPORT=http`.
6. Verify collector heartbeat, quotes, candles, and shadow evaluation.
7. Change collector `INGESTION_TRANSPORT` to `redis` and redeploy it.
8. Verify Stream consumption, PostgreSQL writes, and dashboard updates.
9. Deploy maintenance.

Railway config-as-code files must be selected as each service's Config File in
the Railway service settings. The maintenance cron runs daily at 02:15 UTC and
removes quotes older than 30 days; M1 candles are retained.

## Acceptance checks

Before Redis cutover:

1. `/health/live` and `/health/ready` return HTTP 200.
2. API logs confirm that migration `0007` completed.
3. Login succeeds through the Web dashboard.
4. Collector heartbeat appears as `ONLINE` or `MARKET_CLOSED`.
5. HTTP ingestion stores quotes and completed M1 candles in PostgreSQL.
6. A SHADOW or PAPER bot produces the expected signals.
7. Restarting the collector backfills missing candles without duplicates.

After Redis cutover:

1. Ingestion worker logs show the `goldie-ingestion` consumer group consuming
   `goldie:ingestion:v1`.
2. `goldie:ingestion-worker:heartbeat` updates continuously.
3. Stream pending entries do not grow continuously.
4. Repeated `event_id` values do not create duplicate market data.
5. Quotes, candles, signals, and paper positions continue appearing in the UI.
6. WebSocket updates work through Redis Pub/Sub channel `goldie:events`.
7. `/health/live` remains below 250 ms during ingestion.
8. Cached collector overview is below 500 ms and its p95 is below 1 second.
9. A backtest reaches a terminal state without delaying ingestion.

Use an authenticated request when measuring
`/api/v1/collector/overview`; browser page-load time alone does not isolate API
or cache performance.

The collector is read-only. There are no OANDA order credentials, order
endpoints, or execution interfaces in this stage. FX updates are expected
24/5; weekend heartbeat status is `MARKET_CLOSED`.

## Rollback

If Redis ingestion becomes unhealthy:

1. Set collector `INGESTION_TRANSPORT=http`.
2. Redeploy only the collector.
3. Keep the ingestion worker running until already queued events are drained.
4. Confirm PostgreSQL writes and collector overview updates through HTTP.

The existing HTTP endpoints remain the supported fallback. Do not delete the
Stream or consumer group during rollback because pending events may still
require processing.

## Scaling notes

Redis Pub/Sub distributes UI events between API replicas, so WebSocket fan-out
is no longer limited to one API process. Scale the API only after measuring
database connection-pool capacity.

Backtest workers can scale horizontally because PostgreSQL job claims are
atomic. Ingestion workers can scale through their Redis consumer group, but
each replica must use a unique consumer name.
