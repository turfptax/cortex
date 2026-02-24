# Cortex - Wearable AI Memory

Cortex is a wearable AI memory system that gives any AI agent persistent memory across sessions. It consists of a Pi Zero 2 W (Cortex Core) that stores notes, sessions, activities, searches, and files in a local SQLite database, with an ESP32-S3 USB dongle (Cortex Link) providing BLE connectivity as a fallback.

```
WiFi (preferred):  AI Agent <--MCP--> cortex-mcp ──HTTP──> Cortex Core (Pi Zero)
BLE (fallback):    AI Agent <--MCP--> cortex-mcp ──TCP──> daemon ──USB──> ESP32 ──BLE──> Pi Zero
```

Transport is selected automatically. WiFi is 10-100x faster than BLE and supports file transfer. Multiple AI sessions share the same ESP32 through the daemon — no serial port conflicts.

## Quick Start

```bash
pip install git+https://github.com/turfptax/cortex.git
python -m cortex_mcp ping
```

## Setup

### Automatic setup (recommended)

The setup command writes the correct config for you. It uses the full Python path, so it works even when pip's Scripts directory isn't on PATH (common on Windows):

```bash
# Configure Claude Code
python -m cortex_mcp setup

# Configure Claude Desktop
python -m cortex_mcp setup --target claude-desktop

# Configure both at once
python -m cortex_mcp setup && python -m cortex_mcp setup --target claude-desktop
```

> **Tip:** `cortex-cli setup` also works if pip's Scripts dir is on your PATH.

### Claude Code (manual)

From a terminal (not inside Claude Code):

```bash
claude mcp add cortex -- python -m cortex_mcp.server
```

Or edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "python",
      "args": ["-m", "cortex_mcp.server"]
    }
  }
}
```

### Claude Desktop (manual)

Add to your `claude_desktop_config.json`:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "cortex": {
      "command": "python",
      "args": ["-m", "cortex_mcp.server"]
    }
  }
}
```

> **Note:** If you have multiple Python versions, use the full path to the Python that has cortex-mcp installed (e.g. `C:\\Users\\YOU\\AppData\\Local\\Programs\\Python\\Python313\\python.exe`). The automatic setup command handles this for you.

### Verify

After setup, restart Claude Code/Desktop, then verify the connection:

```bash
python -m cortex_mcp ping
```

The serial port is auto-detected (ESP32-S3 USB VID `0x303A`). If auto-detection fails, set the port explicitly:

```bash
python -m cortex_mcp --port COM5 ping
```

Or via environment variable:

```bash
set CORTEX_PORT=COM5       # Windows
export CORTEX_PORT=/dev/ttyACM0  # Linux/Mac
```

## CLI Reference

All commands work with either `cortex-cli` (if on PATH) or `python -m cortex_mcp`:

```bash
# Setup
python -m cortex_mcp setup                          # Auto-configure Claude Code
python -m cortex_mcp setup --target claude-desktop   # Auto-configure Claude Desktop

# Connectivity
python -m cortex_mcp ping                    # Test round-trip to Cortex Core
python -m cortex_mcp status                  # Get Pi status (uptime, storage)
python -m cortex_mcp context                 # Get full context (sessions, notes, bugs)
python -m cortex_mcp info                    # Show serial ports and connection status

# Notes
python -m cortex_mcp note "My note text"
python -m cortex_mcp note "Fix auth bug" --type bug --project myapp --tags auth,urgent

# Activity logging
python -m cortex_mcp activity "VS Code" --details "Refactoring auth module" --project myapp

# Search logging
python -m cortex_mcp search "python async patterns" --source google

# Sessions
python -m cortex_mcp session start                           # Returns session_id
python -m cortex_mcp session end SESSION_ID "Summary of work" --projects cortex

# Database queries
python -m cortex_mcp query notes --limit 5
python -m cortex_mcp query sessions --filters '{"ai_platform":"claude"}'

# Raw protocol
python -m cortex_mcp raw "CMD:ping"

# Daemon management
python -m cortex_mcp daemon status               # Check if daemon is running
python -m cortex_mcp daemon start                # Start daemon in background
python -m cortex_mcp daemon start --foreground   # Start daemon in foreground
python -m cortex_mcp daemon stop                 # Stop the running daemon

# Direct serial (bypass daemon)
python -m cortex_mcp --direct ping               # Skip daemon, use COM port directly
```

## MCP Tools

When connected via MCP, these tools are available to the AI agent:

| Tool | Description |
|------|-------------|
| `ping` | Test round-trip connectivity |
| `get_status` | Pi uptime, storage, recording state |
| `send_note` | Store a timestamped note (with tags, project, type) |
| `log_activity` | Log what program/file is being worked on |
| `log_search` | Log a search query and source |
| `session_start` | Begin a session (returns session_id) |
| `session_end` | End a session with summary |
| `get_context` | Full context: projects, sessions, notes, bugs, files, reminders |
| `query` | Query any table in the Cortex database |
| `register_computer` | Register this machine with Cortex Core |
| `file_register` | Register metadata for a file already on the Pi |
| `file_list` | List registered files (by category or project) |
| `file_search` | Search files by name, description, or tags |
| `file_upload` | Upload a file to the Pi over WiFi |
| `file_download` | Download a file from the Pi over WiFi |
| `wifi_scan` | Scan for available WiFi networks near the Pi |
| `wifi_status` | Get current WiFi connection (IP, SSID, signal) |
| `wifi_config` | Connect the Pi to a WiFi network (headless provisioning) |
| `send_message` | Send a raw protocol message |
| `read_responses` | Read buffered async messages |
| `connection_info` | Show transport status (WiFi/daemon/serial) |

## Transport

Cortex supports three transports, selected automatically in priority order:

1. **WiFi HTTP** (preferred) — Direct HTTP to the Pi on port 8420 with bearer token auth. Fastest, supports file upload/download. WiFi credentials are discovered automatically via BLE when the ESP32 first connects.
2. **TCP Daemon** — Shared serial port access via `cortex-daemon` on localhost:19750. Multiple AI sessions share one ESP32.
3. **Direct Serial** — USB serial to ESP32 BLE bridge. Fallback when daemon is unavailable.

WiFi discovery: When the Pi connects to the ESP32 over BLE, it sends a `DISCOVER:` message containing its IP, port, and auth token. This is saved to `~/.cortex-wifi.json` automatically — no manual configuration needed.

## File Operations

File transfer requires WiFi transport (not available over BLE).

- **Upload**: `file_upload` sends a file from this computer to the Pi's `uploads/` directory and auto-registers it in the database.
- **Download**: `file_download` retrieves a file from any category (recordings, notes, logs, uploads).
- **Metadata**: `file_register` records metadata for files already on the Pi. `file_list` and `file_search` query the file database.

The Pi's HTTP server (port 8420) also supports direct REST access:
- `GET /files/<category>` — list files
- `GET /files/<category>/<name>` — download
- `POST /files/uploads` — upload (raw body + `X-Filename` header)

## Multi-Session / Daemon

Only one process can hold a serial port at a time. The **cortex-daemon** solves this by holding the ESP32 serial port and serving multiple clients over TCP.

```
Claude Code #1 ──stdio──> cortex-mcp ──TCP──┐
Claude Code #2 ──stdio──> cortex-mcp ──TCP──├──> cortex-daemon ──serial──> ESP32
Claude Desktop ──stdio──> cortex-mcp ──TCP──┤    (localhost:19750)
cortex-cli ─────────────────────TCP─────────┘
```

**The daemon starts automatically** — when `cortex-mcp` or `cortex-cli` runs, it checks for a running daemon and spawns one if needed. No manual setup required.

The daemon binds to `127.0.0.1` only (never exposed to the network) and uses a per-session auth token stored in `~/.cortex-daemon.secret` (mode 0600). Other processes on the same machine cannot send commands without the token.

Manual control:

```bash
cortex-cli daemon status     # Check daemon state
cortex-cli daemon start      # Start manually (background)
cortex-cli daemon stop       # Stop the daemon
```

To bypass the daemon and use the serial port directly:

```bash
cortex-cli --direct ping
CORTEX_DIRECT=1 cortex-mcp   # For MCP server
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_PORT` | auto-detect | Serial port (e.g. `COM5`, `/dev/ttyACM0`) |
| `CORTEX_BAUD` | `115200` | Baud rate |
| `CORTEX_TIMEOUT` | `5` | Response timeout in seconds |
| `CORTEX_DAEMON_PORT` | `19750` | TCP port for the daemon |
| `CORTEX_DIRECT` | unset | Set to `1` to bypass daemon and WiFi |
| `CORTEX_NO_WIFI` | unset | Set to `1` to skip WiFi, use BLE only |
| `CORTEX_PI_HOST` | auto-discover | Pi IP address (overrides BLE discovery) |
| `CORTEX_PI_PORT` | `8420` | Pi HTTP port |
| `CORTEX_WIFI_TOKEN` | auto-discover | Bearer token (overrides `~/.cortex-wifi.token`) |

## Hardware

- **Cortex Link**: ESP32-S3 USB dongle with BLE ([firmware](https://github.com/turfptax/esp32-keymaster))
- **Cortex Core**: Pi Zero 2 W with SQLite database, BLE client, optional mic/display

## Development

```bash
git clone https://github.com/turfptax/cortex.git
cd cortex
pip install -e .
```

## License

MIT
