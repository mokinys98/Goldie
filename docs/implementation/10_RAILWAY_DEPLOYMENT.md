# Railway Hobby deployment

This runbook deploys the Goldie `main` branch as five Railway services:
PostgreSQL, Redis, API, worker, and Web. It starts with a clean production
database and uses Railway-provided domains.

## Before deployment

1. Push the deployment-ready commit to
   `https://github.com/mokinys98/Goldie` on the `main` branch.
2. Create a Railway project in an EU region.
3. Enable MFA on the Railway account.
4. Prepare unique random values for `JWT_SECRET`, `LOCAL_ADMIN_PASSWORD`, and
   `AGENT_SERVICE_TOKEN`. Use at least 32 random bytes for each secret.

The variable template is
[`infrastructure/railway.env.example`](../../infrastructure/railway.env.example).
Never store actual production values in Git.

## Data services

Add PostgreSQL and Redis from Railway templates. Keep both services private:
do not generate public TCP proxies unless temporary administrative access is
required.

Use the service names `Postgres` and `Redis` so the reference variables below
match exactly. Enable PostgreSQL volume backups before sending real market
data.

## API service

Create `goldie-api` from the GitHub repository and configure:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Root directory | repository root |
| `RAILWAY_DOCKERFILE_PATH` | `/apps/api/Dockerfile` |
| Healthcheck path | `/health/ready` |
| Restart policy | `On Failure`, maximum 10 retries |

Set these variables:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
JWT_SECRET=<random secret>
LOCAL_ADMIN_EMAIL=<production admin email>
LOCAL_ADMIN_PASSWORD=<random password>
AGENT_SERVICE_TOKEN=<random agent token>
CORS_ORIGINS=https://${{goldie-web.RAILWAY_PUBLIC_DOMAIN}}
```

Generate a Railway domain for the API. The container runs
`alembic upgrade head` before Uvicorn, uses Railway's dynamic `PORT`, creates
the schema, and seeds the admin account when it does not exist.

## Worker service

Create `goldie-worker` from the same repository:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Root directory | repository root |
| `RAILWAY_DOCKERFILE_PATH` | `/apps/worker/Dockerfile` |
| Restart policy | `On Failure`, maximum 10 retries |

Set:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
```

Do not generate a public domain. The current worker only writes
`goldie:worker:heartbeat` to Redis.

## Web service

Create `goldie-web` from the same repository:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Root directory | `/apps/web` |
| Dockerfile | `/apps/web/Dockerfile` |
| Restart policy | `On Failure`, maximum 10 retries |

Set the build-time variables before deploying:

```text
NEXT_PUBLIC_API_URL=https://${{goldie-api.RAILWAY_PUBLIC_DOMAIN}}
NEXT_PUBLIC_WS_URL=wss://${{goldie-api.RAILWAY_PUBLIC_DOMAIN}}
```

Generate a Railway domain for Web. `NEXT_PUBLIC_*` values are embedded during
`next build`, so changing either URL requires a Web redeploy.

After both domains exist, confirm the API `CORS_ORIGINS` reference resolves to
the exact Web origin, then redeploy API and Web.

## Windows agent

The MT5 agent remains on Windows and connects outbound to Railway:

```powershell
$env:GOLDIE_API_URL="https://<goldie-api-domain>"
$env:GOLDIE_AGENT_TOKEN="<same value as API AGENT_SERVICE_TOKEN>"
$env:GOLDIE_BOT_ID="<bot UUID created in Web>"
$env:GOLDIE_AGENT_MODE="fake" # Change to mt5 after the fake acceptance test.
uv run --package goldie-mt5-agent python -m goldie_agent
```

Do not put MT5 credentials in Railway or Git because the MT5 terminal and
agent run locally on Windows.

## Acceptance checks

1. Open `https://<api-domain>/health/live` and confirm `status=ok`.
2. Open `https://<api-domain>/health/ready` and confirm `database=ok`.
3. Log in through Web with `LOCAL_ADMIN_EMAIL` and
   `LOCAL_ADMIN_PASSWORD`.
4. Create a bot, validate its draft configuration, and activate it.
5. Start the fake Windows agent and verify account, symbol, tick, candle,
   signal, and heartbeat data in Web.
6. Redeploy the API and confirm the bot and collected data remain.
7. Confirm the worker deployment remains healthy and Redis contains a fresh
   `goldie:worker:heartbeat`.
8. Create a PostgreSQL backup and confirm it appears in Railway.
9. Set Railway usage alerts at USD 10 and USD 15 for the Hobby project.

If `/health/ready` fails, inspect the API deployment logs first. Typical
causes are an unresolved `DATABASE_URL` service reference or PostgreSQL not
being ready when the first deployment starts.
