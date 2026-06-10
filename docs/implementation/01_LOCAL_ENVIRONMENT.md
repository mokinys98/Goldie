# Local environment

## Prerequisites

- Windows 11 and Docker Desktop with Compose
- Node.js 22
- Python 3.12 or 3.13 for development
- `pnpm` through Corepack and `uv`
- MetaTrader 5 demo terminal for the real read-only adapter

## Platform startup

```powershell
Copy-Item .env.example .env
# Edit all secrets in .env.
uv sync --all-packages
corepack pnpm --dir apps/web install
docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
```

Ports: UI `3000`, API `8000`, PostgreSQL `5432`, Redis `6379`.

## MT5 setup

Install the broker-provided MT5 terminal, create a demo account, add XAU/USD
to Market Watch, and record the terminal path, login, server, and actual
broker symbol. Credentials remain in local environment variables.

The Windows agent connects outbound to `http://localhost:8000`; no inbound
Windows port is needed.

## Diagnostics

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
docker compose -f infrastructure/docker/compose.yml ps
```
