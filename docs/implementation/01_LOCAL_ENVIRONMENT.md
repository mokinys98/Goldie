# Local environment

## Prerequisites

- Windows 11 and Docker Desktop with Compose
- Node.js 22
- Python 3.12 or 3.13 for development
- `pnpm` through Corepack and `uv`
- OANDA Practice account and API token

## Platform startup

```powershell
Copy-Item .env.example .env
# Edit all secrets in .env.
uv sync --all-packages
corepack pnpm --dir apps/web install
docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
```

Ports: UI `3000`, API `8000`, PostgreSQL `5432`, Redis `6379`.

## OANDA collector setup

Set `GOLDIE_OANDA_API_TOKEN`, `GOLDIE_OANDA_ACCOUNT_ID`,
`GOLDIE_API_URL`, and `GOLDIE_AGENT_TOKEN`, then run:

```powershell
uv run --package goldie-market-data-collector python -m goldie_collector
```

The collector connects outbound to OANDA and Goldie API. It never submits
orders.

## Diagnostics

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
docker compose -f infrastructure/docker/compose.yml ps
```
