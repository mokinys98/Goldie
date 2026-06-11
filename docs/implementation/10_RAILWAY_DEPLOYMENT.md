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

## GitHub automatic deployments

Railway automatic deployments are configured per service in the Railway
dashboard. Configure all three application services (`goldie-api`,
`goldie-worker`, and `goldie-web`) as follows:

1. Open the service and go to **Settings > Source**.
2. Connect the `mokinys98/Goldie` GitHub repository.
3. Set the deployment trigger branch to `main`.
4. Set **Autodeploy** to **Enabled**.
5. Leave **Watch Paths** empty.

With this configuration, every commit pushed to GitHub `main` triggers a new
deployment of API, worker, and Web. PostgreSQL and Redis are managed data
services and are not redeployed from GitHub.

Do not add service-specific Watch Paths when the requirement is to redeploy
the whole platform after every push. Watch Paths can cause Railway to skip a
service when a commit changes files outside its configured patterns.

Verify the integration with a normal push to `main`, then confirm that all
three application services show a deployment for the same commit SHA. If a
service does not deploy, open its **Settings > Source** page and check that
the repository, branch, and Autodeploy state match the values above.

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
| Root directory | leave empty (repository root) |
| `RAILWAY_DOCKERFILE_PATH` | `/apps/api/Dockerfile` |
| Healthcheck path | `/health/ready` |
| Restart policy | `On Failure`, maximum 10 retries |

Do not set the API Root Directory to `/apps/api`. The API Dockerfile needs the
full repository build context because it copies both `apps/api` and the shared
`packages/trading-domain` package.

### Where to add API variables

Open the Railway project, select the **Goldie API** service, and open the
**Variables** tab. The variables must be added under **Service Variables**,
not under the PostgreSQL or Redis service.

The quickest method is:

1. Click **Raw Editor** in `Goldie API > Variables`.
2. Paste the block below.
3. Replace the four `<...>` placeholders with the real values.
4. Click the Railway save/update button.
5. Open **Deployments** and redeploy the latest deployment if Railway does not
   start a deployment automatically.

Paste into **Raw Editor**:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
JWT_SECRET=<first generated random value>
LOCAL_ADMIN_EMAIL=<your login email>
LOCAL_ADMIN_PASSWORD=<second generated random value>
AGENT_SERVICE_TOKEN=<third generated random value>
CORS_ORIGINS=https://<exact Goldie Web Railway domain>
```

If the Web service has not been created yet, temporarily use:

```text
CORS_ORIGINS=http://localhost:3000
```

Replace it with the exact `goldie-web` Railway domain after the Web service
exists, then redeploy the API.

The collapsed **variables added by Railway** section contains platform
variables such as `PORT` and Railway service metadata. Do not edit or copy
those values. `PORT` is supplied automatically and must not be added manually.

Generate a Railway domain for the API. The container runs
`alembic upgrade head` before Uvicorn, uses Railway's dynamic `PORT`, creates
the schema, and seeds the admin account when it does not exist.

## Worker service

Create `goldie-worker` from the same repository:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Root directory | leave empty (repository root) |
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
NEXT_PUBLIC_API_URL=https://<exact Goldie API Railway domain>
NEXT_PUBLIC_WS_URL=wss://<exact Goldie API Railway domain>
```

Generate a Railway domain for Web. `NEXT_PUBLIC_*` values are embedded during
`next build`, so changing either URL requires a Web redeploy.

Use literal public domain values for these Web build variables. A Railway
service reference can resolve to an empty value during the Web image build,
which produces an invalid `https:///api/...` URL in the browser bundle.

Example:

```text
NEXT_PUBLIC_API_URL=https://goldie-api-production.up.railway.app
NEXT_PUBLIC_WS_URL=wss://goldie-api-production.up.railway.app
```

Do not add `/` at the end of either URL. The Web client also strips trailing
slashes defensively, but keeping the Railway values canonical avoids stale
build confusion.

After both domains exist, set the API CORS value to the literal Web origin:

```text
CORS_ORIGINS=https://goldie-web-production.up.railway.app
```

Redeploy API and Web. Redeploying Web is mandatory because the public URL
values are embedded during the Docker build.

## Windows agent

The agent remains on the Windows computer and connects outbound to Railway.
Complete the fake adapter test before configuring MetaTrader 5. The full
installation and troubleshooting guide is
[`11_WINDOWS_AGENT_SETUP.md`](11_WINDOWS_AGENT_SETUP.md).

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
