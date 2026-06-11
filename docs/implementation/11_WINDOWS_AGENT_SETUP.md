# Windows market-data agent setup

The Goldie agent runs on the Windows computer that has access to MetaTrader 5.
It connects outbound to the public Railway API over HTTPS. No inbound Windows
port, public IP address, or Railway deployment is required for the agent.

Start with the fake adapter. Configure the real MT5 adapter only after the
fake test works.

## 1. Collect the required values

Prepare these three values before opening PowerShell:

| Value | Where to find it |
| --- | --- |
| API URL | Railway `Goldie API` service, **Settings > Networking > Public Networking** |
| Agent token | The exact `AGENT_SERVICE_TOKEN` value set in `Goldie API > Variables` |
| Bot ID | Open a bot in Goldie Web and copy the UUID from `/bots/<UUID>` in the browser URL |

The API URL must start with `https://` and must not end with an API path.
Example:

```text
https://goldie-api-production.up.railway.app
```

Before continuing, open these addresses in a browser:

```text
https://<goldie-api-domain>/health/live
https://<goldie-api-domain>/health/ready
```

Both requests must succeed, and the ready response must contain
`"database":"ok"`.

In Goldie Web, create a bot if one does not exist. Validate and activate its
configuration before starting the agent.

## 2. Install `uv` and Python

Open a new regular PowerShell window and run:

```powershell
winget install --id=astral-sh.uv -e
```

Close and reopen PowerShell, then verify:

```powershell
uv --version
uv python install 3.12
```

The official alternative installer is:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Use only one installation method.

## 3. Install the fake agent

In PowerShell, change to the Goldie repository directory:

```powershell
Set-Location "C:\Users\Administrator\Documents\Goldie"
uv sync --all-packages
```

This creates the local Python environment and installs the workspace packages.
Docker is not required for the Windows agent.

## 4. Run the fake Railway connection test

Set the values only in the current PowerShell window:

```powershell
$env:GOLDIE_API_URL="https://<goldie-api-domain>"
$env:GOLDIE_AGENT_TOKEN="<same AGENT_SERVICE_TOKEN as Railway API>"
$env:GOLDIE_BOT_ID="<bot UUID>"
$env:GOLDIE_AGENT_MODE="fake"
$env:GOLDIE_AGENT_NAME="windows-fake-agent"
```

Start the agent:

```powershell
uv run --package goldie-mt5-agent python -m goldie_agent
```

Expected log:

```text
Connected using fake adapter
```

Keep the PowerShell window open. The process sends:

- heartbeat every 5 seconds;
- a tick every 2 seconds;
- account and symbol metadata every 30 seconds;
- completed M1 candles.

Open the bot in Goldie Web and confirm that the agent is online and market
data appears. Stop the agent with `Ctrl+C`.

The `$env:` values above exist only in that PowerShell process. They are not
committed to Git and disappear when the window is closed.

## 5. Install and prepare MetaTrader 5

Do this section only after the fake test succeeds.

1. Install the broker-provided 64-bit MetaTrader 5 terminal.
2. Sign in to a **demo account**.
3. Confirm that live quotes are visible.
4. Add the broker's XAU/USD symbol to Market Watch.
5. Record the exact account number and server name shown in MT5.
6. Locate `terminal64.exe`. A typical path is:

```text
C:\Program Files\<Broker MetaTrader 5>\terminal64.exe
```

Install the MT5 Python dependency:

```powershell
Set-Location "C:\Users\Administrator\Documents\Goldie"
uv sync --package goldie-mt5-agent --extra mt5
```

## 6. Run the read-only MT5 agent

The safest initial setup is to log in through the MT5 terminal and let the
Python integration reuse the terminal's saved session. Then no MT5 password is
placed in PowerShell:

```powershell
$env:GOLDIE_API_URL="https://<goldie-api-domain>"
$env:GOLDIE_AGENT_TOKEN="<same AGENT_SERVICE_TOKEN as Railway API>"
$env:GOLDIE_BOT_ID="<bot UUID>"
$env:GOLDIE_AGENT_MODE="mt5"
$env:GOLDIE_AGENT_NAME="windows-mt5-agent"
$env:GOLDIE_MT5_TERMINAL_PATH="C:\Program Files\<Broker MetaTrader 5>\terminal64.exe"
$env:GOLDIE_MT5_SYMBOL="XAUGOLD"

Remove-Item Env:GOLDIE_MT5_LOGIN -ErrorAction SilentlyContinue
Remove-Item Env:GOLDIE_MT5_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:GOLDIE_MT5_SERVER -ErrorAction SilentlyContinue

uv run --package goldie-mt5-agent python -m goldie_agent
```

Expected log:

```text
Selected MT5 symbol XAUGOLD
Connected using mt5 adapter
```

The adapter reads account information, symbol metadata, ticks, and completed
M1 candles. The current Goldie agent has no order placement call.

If MT5 cannot reuse the saved session, set the optional values in the current
PowerShell window:

```powershell
$env:GOLDIE_MT5_LOGIN="<demo account number>"
$env:GOLDIE_MT5_PASSWORD="<demo account password>"
$env:GOLDIE_MT5_SERVER="<exact MT5 server name>"
```

Do not put the MT5 password in `.env.example`, Git, Railway, screenshots, or
the setup documentation.

## 7. Acceptance checklist

- Railway API `/health/ready` reports `database=ok`.
- Fake mode connects without `401`, `404`, or connection errors.
- Goldie Web reports the agent as online.
- Account, symbol, tick, and candle data appear for the selected bot.
- Fake mode is stopped before MT5 mode starts.
- MT5 uses a demo account for the first test.
- The symbol selected by the agent is the broker's intended XAU/USD symbol.
- Stopping the process with `Ctrl+C` eventually changes the agent to offline
  in Goldie Web.

## Troubleshooting

### `uv` is not recognized

Close and reopen PowerShell after installation. If needed, reinstall with the
official installer shown above.

### HTTP 401

`GOLDIE_AGENT_TOKEN` does not exactly match the API service's
`AGENT_SERVICE_TOKEN`. Update the current PowerShell value and restart the
agent.

### HTTP 404 when registering

Check that `GOLDIE_API_URL` is the Goldie API Railway domain, not the Web
domain, and that it contains no `/api/v1` suffix.

### Bot not found or foreign-key error

Copy the UUID from the selected Railway Goldie Web bot URL. A local-development
bot UUID does not exist in the clean Railway database.

If the agent reports `404 Not Found for /api/v1/agents/register: Bot not
found`, log in to the deployed Railway Goldie Web application, create a new
bot there, open that bot, and copy the UUID from the Railway Web URL. Do not
reuse an ID from `localhost`, an older Railway database, or a previous
PostgreSQL service.

### `No symbol contains hint 'XAU'`

Prefer setting the broker's exact symbol:

```powershell
$env:GOLDIE_MT5_SYMBOL="XAUGOLD"
```

Stop the running agent with `Ctrl+C` and start it again after changing the
symbol. Market Watch changes do not switch the running agent automatically:
the agent selects its symbol once when it connects and can enable that symbol
again through the MT5 API.

If the exact broker symbol is unknown, remove `GOLDIE_MT5_SYMBOL` and use the
fallback search:

```powershell
Remove-Item Env:GOLDIE_MT5_SYMBOL -ErrorAction SilentlyContinue
$env:GOLDIE_MT5_SYMBOL_HINT="XAUUSD"
```

The fallback chooses the shortest symbol containing the hint. For brokers with
both `XAUG` and `XAUGOLD`, always use the exact `GOLDIE_MT5_SYMBOL` setting.

### `MT5 initialization failed`

Confirm that:

- the 64-bit terminal is installed and can log in manually;
- `GOLDIE_MT5_TERMINAL_PATH` points to `terminal64.exe`;
- the terminal and PowerShell run under the same Windows user;
- the server name exactly matches the value displayed by MT5.

## References

- `uv` Windows installation:
  https://docs.astral.sh/uv/getting-started/installation/
- MetaTrader 5 Python `initialize`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
