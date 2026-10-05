# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the OpenAI Codex CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The bug-bash fork selects Phoenix at `https://task-eval-mvp.vercel.app` and project
`tasks-bug-bash`. Paste the shared API key supplied by the organizer and choose
whether to capture prompts, tool commands, and tool outputs. No Phoenix account
or email is required. The installer assigns an anonymous participant ID and
saves the key privately in `~/.arize/harness/config.json`.

Quit Codex before installing, then reopen it. The installer registers a `notify`
callback in `~/.codex/config.toml`; it reads prompts and tool calls from the local
Codex rollout after each completed turn. No `/hooks` approval is required.

Workshop exports always use the shared endpoint, even when your shell contains
Arize AX or local Phoenix credentials. The exporter uses the Python standard
library and sends no Arize usage analytics. Setup and the Codex env file set
`PHOENIX_TELEMETRY_ENABLED=false`. The organizer must also disable telemetry on
the Phoenix server; this client's setting cannot change a remote server.

For a fresh local Phoenix or Arize AX setup, pass `--advanced` to use the original
configuration wizard. Updating an existing installation preserves its profile,
anonymous ID, content-logging choice, and paused state.

Pass `--with-skills` to also symlink the `manage-codex-tracing` skill into the current directory's `.agents/skills/` so coding agents in this workspace can help manage Codex tracing configuration.

### Existing notification commands

If `notify` already contains a command, the installer preserves it using `--previous-notify` chaining. Recognized Codex desktop callbacks remain outermost. Reinstall keeps a single Arize callback; uninstall restores the previous command.

The rollout reader also recognizes user prompts stored as `response_item` messages. When content provenance is available, it excludes injected repository instructions and environment content.

### Pause and resume exports

After installing the bug-bash fork, run these commands in Terminal:

```sh
bash ~/.arize/harness/install.sh pause codex
bash ~/.arize/harness/install.sh resume codex
bash ~/.arize/harness/install.sh trace-status codex
```

Pause and resume apply to all chats using your Codex home. The hook reads the
switch at each completed turn, so you do not need to restart Codex. An export
already in progress may finish. Updating the installer preserves a paused state.
These commands do not delete existing Phoenix traces or Codex transcripts.

The package also installs `codex-tracing off`, `on`, and `status` in
`~/.arize/harness/venv/bin`. The shell commands above do not require a PATH change.

To stop acceptance from Phoenix, an admin can revoke the workshop system API key
in Settings. A shared key stops uploads for every participant using it. Resume
requires a replacement key. Local resume cannot restore a revoked key.

### Remote setup

#### macOS / Linux

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/rbavery/coding-harness-tracing/codex/bug-bash-installer/install.sh | bash -s -- codex
```

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/rbavery/coding-harness-tracing/codex/bug-bash-installer/install.sh | bash -s -- uninstall codex
```

#### Windows (PowerShell)

The workshop shell installer is for macOS and Linux. These Windows commands use
the upstream configuration wizard.

Install:

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat codex
```

Uninstall:

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall codex
```

### Local setup

```bash
git clone https://github.com/Arize-ai/coding-harness-tracing.git
cd coding-harness-tracing
```

**macOS / Linux**

Install:

```bash
./install.sh codex
```

Uninstall:

```bash
./install.sh uninstall codex
```

**Windows (PowerShell)**

Install:

```powershell
install.bat codex
```

Uninstall:

```powershell
install.bat uninstall codex
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `codex` |
| Project name | `tasks-bug-bash` |
| Phoenix endpoint | `https://task-eval-mvp.vercel.app` |
| Participant identity | Generated anonymous ID, no email |
| Phoenix usage telemetry | Disabled; disable separately on the server |
| Hook config file | `~/.codex/config.toml` |
| Hook events handled | `agent-turn-complete` via `notify`, with prompts and tool calls read from the rollout |
| Env override file | `~/.codex/arize-env.sh` |
| State directory | `~/.arize/harness/state/codex/` (state files + tool span JSONLs) |
| Log file | `~/.arize/harness/logs/codex.log` |

## Verifying tracing

Run any Codex command:

```bash
codex exec "explain what this file does" path/to/file.py
```

Then check:

- Hook activity in `~/.arize/harness/logs/codex.log`.
- Per-thread state files in `~/.arize/harness/state/codex/` show recent activity.
- Spans appear in your configured project in Arize AX or Phoenix.

Errors are always logged. For routine hook activity, add `export ARIZE_VERBOSE=true` to `~/.codex/arize-env.sh` (or your shell) and re-run. See the [main README's Environment variables section](../../README.md#environment-variables) for the full list of runtime overrides (`ARIZE_TRACE_ENABLED`, `ARIZE_DRY_RUN`, `ARIZE_TRACE_DEBUG`, etc.).

## Troubleshooting

**Hooks not firing.** Run `codex` → `/hooks` and confirm the `arize-hook-codex-*` entries are listed and trusted. If they aren't listed at all, re-run the installer.

**No spans appear.** Re-source your shell profile (or open a new terminal) so `~/.codex/arize-env.sh` is loaded. Check `~/.arize/harness/logs/codex.log` for backend/auth errors. Confirm the hooks are trusted via `/hooks`.

**Disable temporarily.** Untrust the entries via `codex` → `/hooks`, or set `ARIZE_TRACE_ENABLED=false` in `~/.codex/arize-env.sh` and restart Codex. Full uninstall: `./install.sh uninstall codex`.
