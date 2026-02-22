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

## Claude Code Setup

```bash
claude mcp add cortex -- cortex-mcp
```

With an explicit serial port:

```bash
claude mcp add cortex -e CORTEX_PORT=COM5 -- cortex-mcp
```

## Claude Desktop Setup

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

Or with an explicit port:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex-mcp",
      "env": {
        "CORTEX_PORT": "COM5"
      }
    }
  }
}
```

## CLI Reference

The `cortex-cli` tool lets any AI (or human) interact with Cortex via shell commands.

```bash
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
