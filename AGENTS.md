# Codex Project Rules

## Windows / Dev Server Safety

- Do not use `Start-Process -FilePath pnpm`, `npm`, or other commands that can resolve to `.ps1` files on Windows.
- When running pnpm on Windows, use a normal shell command or explicit `pnpm.cmd`.
- Do not start background dev servers unless the user asks or browser verification is truly required.
- For frontend changes, prefer `pnpm run build` as the default verification.
- If Browser, localhost, or dev server verification fails because of environment issues, stop and report briefly instead of repeatedly restarting processes.
- Before launching any background process, explain why it is needed.
- Avoid process inspection/restart loops on Windows unless the user explicitly approves that troubleshooting step.
