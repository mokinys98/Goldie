# Goldie

Read-only XAU/USD trading research platform. The hosted shadow/paper platform
provides a Next.js control UI, FastAPI API, PostgreSQL persistence, a
deterministic signal engine, and a 24/7 OANDA market-data collector.

No order placement API or execution code exists in this phase.

## Quick start

1. Copy `.env.example` to `.env` and change all secrets.
2. Start the platform:

   ```powershell
   docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
   ```

3. Open `http://localhost:3000`.
4. Create a bot and activate its configuration.
5. Start the OANDA collector after configuring its credentials:

   ```powershell
   uv sync --all-packages
   $env:GOLDIE_API_URL="http://localhost:8000"
   $env:GOLDIE_AGENT_TOKEN="<same value as AGENT_SERVICE_TOKEN>"
   $env:GOLDIE_OANDA_API_TOKEN="<OANDA practice token>"
   $env:GOLDIE_OANDA_ACCOUNT_ID="<OANDA practice account ID>"
   uv run --package goldie-market-data-collector python -m goldie_collector
   ```

Detailed setup and acceptance checks are in
[`docs/implementation`](docs/implementation/00_LOCAL_MVP_ROADMAP.md).

Railway deployment is documented in
[`09_RAILWAY_HOSTED_SHADOW.md`](docs/implementation/09_RAILWAY_HOSTED_SHADOW.md).
