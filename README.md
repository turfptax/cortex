# Cortex - Wearable AI Memory

Cortex is a wearable AI memory system that gives any AI agent persistent memory across sessions. It consists of a USB dongle (ESP32-S3 BLE bridge) and a wearable Pi Zero 2 W that stores notes, sessions, activities, and searches in a local SQLite database.

```
AI Agent <--MCP/CLI--> cortex-mcp <--USB Serial--> Cortex Link (ESP32) <--BLE--> Cortex Core (Pi Zero)
```

## Quick Start

```bash
pip install git+https://github.com/turfptax/cortex.git
cortex-cli ping
```

> **Windows note:** If `cortex-cli` is not found after install, pip may have installed it to a directory not on your PATH. Run `python -m sysconfig` and look for the `scripts` path, then either add it to PATH or use the full path (e.g. `C:\Users\YOU\...\Scripts\cortex-cli.exe`).

## Setup

### Automatic setup (recommended)

The `cortex-cli setup` command auto-detects the `cortex-mcp` executable path and writes the config for you:

```bash
# Configure Claude Code
cortex-cli setup

# Configure Claude Desktop
cortex-cli setup --target claude-desktop
```

### Claude Code (manual)

From a terminal (not inside Claude Code):

```bash
claude mcp add cortex -- cortex-mcp
```

Or if `cortex-mcp` is not on PATH, use the full path:

```bash
claude mcp add cortex -- C:\Users\YOU\...\Scripts\cortex-mcp.exe
```

If you're already inside Claude Code and can't run `claude mcp add`, edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "C:\\Users\\YOU\\...\\Scripts\\cortex-mcp.exe",
      "args": []
    }
  }
}
```

### Claude Desktop (manual)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex-mcp"
    }
  }
}
```

### Verify

After setup, restart Claude Code/Desktop, then verify the connection:

```bash
cortex-cli ping
```

The serial port is auto-detected (ESP32-S3 USB VID `0x303A`). If auto-detection fails, set the port explicitly:

```bash
cortex-cli --port COM5 ping
```

Or via environment variable:

```bash
set CORTEX_PORT=COM5       # Windows
export CORTEX_PORT=/dev/ttyACM0  # Linux/Mac
```

## CLI Reference

The `cortex-cli` tool lets any AI (or human) interact with Cortex via shell commands.

```bash
# Setup
cortex-cli setup                   # Auto-configure Claude Code
cortex-cli setup --target claude-desktop  # Auto-configure Claude Desktop

# Connectivity
cortex-cli ping                    # Test round-trip to Cortex Core
cortex-cli status                  # Get Pi status (uptime, storage)
cortex-cli context                 # Get full context (sessions, notes, bugs)
cortex-cli info                    # Show serial ports and connection status

# Notes
cortex-cli note "My note text"
cortex-cli note "Fix auth bug" --type bug --project myapp --tags auth,urgent

# Activity logging
cortex-cli activity "VS Code" --details "Refactoring auth module" --project myapp

# Search logging
cortex-cli search "python async patterns" --source google

# Sessions
cortex-cli session start                           # Returns session_id
cortex-cli session end SESSION_ID "Summary of work" --projects cortex

# Database queries
cortex-cli query notes --limit 5
cortex-cli query sessions --filters '{"ai_platform":"claude"}'

# Raw protocol
cortex-cli raw "CMD:ping"
```

## MCP Tools

When connected via MCP, these tools are available to the AI agent:

| Tool | Description |
|------|-------------|
| `ping` | Test round-trip BLE connectivity |
| `get_status` | Pi uptime, storage, recording state |
| `send_note` | Store a timestamped note (with tags, project, type) |
| `log_activity` | Log what program/file is being worked on |
| `log_search` | Log a search query and source |
| `session_start` | Begin a session (returns session_id) |
| `session_end` | End a session with summary |
| `get_context` | Full context: projects, sessions, notes, bugs, reminders |
| `query` | Query any table in the Cortex database |
| `register_computer` | Register this machine with Cortex Core |
| `send_message` | Send a raw protocol message |
| `read_responses` | Read buffered async messages |
| `connection_info` | Show serial port status |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_PORT` | auto-detect | Serial port (e.g. `COM5`, `/dev/ttyACM0`) |
| `CORTEX_BAUD` | `115200` | Baud rate |
| `CORTEX_TIMEOUT` | `5` | Response timeout in seconds |

Legacy `KEYMASTER_PORT`, `KEYMASTER_BAUD`, and `KEYMASTER_TIMEOUT` are also supported.

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
