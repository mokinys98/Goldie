# Railway hosted shadow/paper

## Architecture

Create one Railway project with five services:

1. PostgreSQL.
2. `api` using `railway/api.toml`.
3. `web` using Config File `/railway/web.toml`, with Railway Root Directory
   set to `/apps/web`.
4. `market-data-collector` using `railway/collector.toml`.
5. `maintenance` using `railway/maintenance.toml`.

Keep the API and collector at one replica. WebSocket fan-out is currently held
in API process memory, and multiple collectors would duplicate ingestion.

## Variables

API:

```text
DATABASE_URL=<Railway PostgreSQL URL using postgresql+psycopg://>
JWT_SECRET=<long random value>
LOCAL_ADMIN_EMAIL=<admin email>
LOCAL_ADMIN_PASSWORD=<strong password>
AGENT_SERVICE_TOKEN=<long random shared service token>
CORS_ORIGINS=https://<web-domain>
QUOTE_RETENTION_DAYS=30
```

Web:

```text
NEXT_PUBLIC_API_URL=https://<api-domain>
NEXT_PUBLIC_WS_URL=wss://<api-domain>
```

Collector (assuming the API service is named `api`):

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
```

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

## Startup and acceptance

1. Deploy PostgreSQL and API; API runs Alembic before Uvicorn.
2. Deploy the collector and verify its feed appears in the UI.
3. Create a SHADOW or PAPER bot and assign the OANDA feed.
4. Activate a validated config.
5. Verify quotes arrive approximately every five seconds and completed M1
   candles produce theoretical signals.
6. Restart the collector and verify missing candles are backfilled without
   duplicates.
7. Confirm PAPER starts at 10,000 USD and SHADOW has no paper account.

The collector is read-only. There are no OANDA order credentials, order
endpoints, or execution interfaces in this stage. FX updates are expected
24/5; weekend heartbeat status is `MARKET_CLOSED`.

Railway config-as-code files must be selected as each service's config file in
the Railway service settings. The maintenance cron runs daily at 02:15 UTC and
removes quotes older than 30 days; M1 candles are retained.
