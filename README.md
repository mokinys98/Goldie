# Goldie

Read-only XAU/USD trading research platform. The local MVP provides a
Next.js control UI, FastAPI API, PostgreSQL persistence, a deterministic
paper signal engine, and a Windows market-data agent.

No order placement API or execution code exists in this phase.

## Quick start

1. Copy `.env.example` to `.env` and change all secrets.
2. Start the platform:

   ```powershell
   docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
   ```

3. Open `http://localhost:3000`.
4. Create a bot and activate its configuration.
5. Start the Windows fake agent:

   ```powershell
   uv sync --all-packages
   $env:GOLDIE_AGENT_MODE="fake"
   $env:GOLDIE_BOT_ID="<bot UUID>"
   uv run --package goldie-mt5-agent python -m goldie_agent
   ```

Detailed setup and acceptance checks are in
[`docs/implementation`](docs/implementation/00_LOCAL_MVP_ROADMAP.md).

Stage II managed database purchasing requirements are in
[`docs/implementation/09_STAGE_II_MANAGED_DATABASE_REQUIREMENTS.md`](docs/implementation/09_STAGE_II_MANAGED_DATABASE_REQUIREMENTS.md).

Railway Hobby deployment instructions are in
[`docs/implementation/10_RAILWAY_DEPLOYMENT.md`](docs/implementation/10_RAILWAY_DEPLOYMENT.md).

Windows fake and MT5 agent setup is in
[`docs/implementation/11_WINDOWS_AGENT_SETUP.md`](docs/implementation/11_WINDOWS_AGENT_SETUP.md).

Shadow trade outcome rules, Railway migration checks and quality gates are in
[`docs/implementation/12_SHADOW_OUTCOME_EVALUATION.md`](docs/implementation/12_SHADOW_OUTCOME_EVALUATION.md).
