**English** | [中文](README.zh-CN.md)

# CoSight Viewer

CoSight Viewer is the **session monitoring component** of Co-Sight Harness: it gives you a real-time view of Claude Code session activity, event streams and run status. It captures Claude Code's execution through a hook mechanism and provides a web UI for visual monitoring.

## Core capabilities

| Capability          | Description                                                           |
| ------------------- | --------------------------------------------------------------------- |
| Session list        | Browse all Claude Code sessions, with search and filtering            |
| Session details     | Inspect a single session's full event stream, tool calls and token usage |
| Live monitoring     | WebSocket push keeps session status updated in real time              |
| Project monitoring  | Project paths (cwd) are captured automatically and grouped by project  |

## Quick start

```bash
# Option 1: one-command start (recommended)
./scripts/start.sh

# Option 2: manual start
npm install        # install dependencies (starts the service automatically)
npm run start      # start the service if it is not already running
```

URL: http://localhost:4830

**Notes**:

- `npm install` triggers the `postinstall` script, which builds the client and starts the service
- `./scripts/start.sh` checks dependency state: it runs `npm install` if dependencies are missing, otherwise it starts the service directly

## Commands and scripts

### NPM commands

| Command                   | Purpose                                             |
| ------------------------- | --------------------------------------------------- |
| `npm run setup`         | Install all dependencies (server + client)          |
| `npm run build`         | Build the client (produces `dist`)                  |
| `npm run start`         | Start the service (runs in the background)          |
| `npm run stop`          | Stop the service                                    |
| `npm run install-hooks` | Install Claude Code hooks                           |
| `npm run selfcheck`     | Environment diagnostics                             |

### CLI commands

```bash
# Start the service
npx co-sight-viewer start

# Stop the service
npx co-sight-viewer stop

# Show status
npx co-sight-viewer status

# Environment diagnostics
npx co-sight-viewer selfcheck

# Full uninstall
npx co-sight-viewer uninstall
```

### Standalone scripts

| Script                       | Purpose                                          |
| ---------------------------- | ------------------------------------------------ |
| `scripts/start.sh`         | One-command start (check deps → install/start)  |
| `scripts/cli.js`           | CLI entry point                                  |
| `scripts/install-hooks.js` | Install hooks                                    |
| `scripts/selfcheck.js`     | Environment diagnostics                          |
| `scripts/uninstall.js`     | Full uninstall                                   |

## Configuration

### Environment variables

| Variable          | Default  | Description   |
| ----------------- | -------- | ------------- |
| `CO_SIGHT_PORT` | `4830` | Service port  |

## Data storage

CoSight Viewer stores its data in the following directory:

**Data directory:**

```
~/.cosight-harness/cosight-viewer/
```

**File layout:**

```
~/.cosight-harness/cosight-viewer/
├── dashboard.db          # Main database (sessions, events, tokens, etc.)
├── settings.json         # Viewer settings (auto-cleanup, etc.; sectioned for future options)
├── state.json            # Runtime state (e.g. last auto-cleanup result)
└── transcripts/          # Transcript snapshots (backup of imported sessions)
```

**Notes:**

- The directory is created automatically if it does not exist
- Database file: `dashboard.db`
- The directory sits alongside Claude Code's data directory (`~/.claude/`)

## Stop and uninstall

```bash
# Stop the service
npm run stop

# Full uninstall (cleans up hooks, data and logs)
npx co-sight-viewer uninstall
```

## Acknowledgements

The design and implementation of this project reference and reuse portions of the open-source project [**Claude-Code-Agent-Monitor**](https://github.com/hoangsonww/Claude-Code-Agent-Monitor). We are grateful to its author and community.

- Upstream license: MIT
- Upstream copyright: Copyright (c) 2026 - Now, Son Nguyen
- The upstream copyright and permission notice is retained in full in [NOTICE](NOTICE), as required by the MIT License.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

Portions of this project are derived from [Claude-Code-Agent-Monitor](https://github.com/hoangsonww/Claude-Code-Agent-Monitor), which is licensed under the MIT License. The upstream copyright and permission notice is retained in full in [NOTICE](NOTICE).
