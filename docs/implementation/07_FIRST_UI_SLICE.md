# First UI slice

Routes:

- `/login`
- `/bots`
- `/bots/new`
- `/bots/[id]`

The bot detail page contains Overview, Configuration, Live Monitor, Signals,
and Run History. Every page shows a persistent `READ ONLY / NO ORDER
EXECUTION` badge. REST loads authoritative state; WebSocket refreshes live
status. Disconnected or old data is labelled `STALE`.

