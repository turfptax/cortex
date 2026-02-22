"""Cortex MCP Bridge Server.

Connects to Cortex Link (ESP32) via USB serial and provides MCP tools
for AI agents to communicate with Cortex Core (Pi Zero 2 W) over BLE.

Data flow (with daemon):
    AI Agent -> MCP Server -> TCP -> cortex-daemon -> USB Serial -> ESP32 -> BLE -> Pi

Data flow (direct, fallback):
    AI Agent -> MCP Server -> USB Serial -> Cortex Link -> BLE -> Cortex Core

Run with:
    cortex-mcp          (installed entry point)
    python -m cortex_mcp.server  (direct invocation)
"""

import json
import os
import socket
import platform

from mcp.server.fastmcp import FastMCP

from cortex_mcp.bridge import SerialBridge, find_esp32_port, list_ports
from cortex_mcp.protocol import send_command


def _get_bridge():
    """Get the best available bridge: daemon (preferred) or direct serial.

    Uses daemon by default for shared access. Set CORTEX_DIRECT=1 to
    bypass the daemon and use the serial port directly.
    """
    if os.environ.get("CORTEX_DIRECT"):
        return SerialBridge()

    try:
        from cortex_mcp.daemon_client import DaemonBridge, is_daemon_running, ensure_daemon
        if is_daemon_running() or ensure_daemon():
            return DaemonBridge()
    except Exception:
        pass

    # Daemon unavailable, fall back to direct serial
    return SerialBridge()


# Singleton bridge instance
_bridge = _get_bridge()

# MCP server
mcp = FastMCP(
    "Cortex Bridge",
    instructions=(
        "Bridge to Cortex Core (Pi Zero 2 W wearable) via Cortex Link (ESP32 BLE). "
        "Use these tools to log activities, notes, searches, and manage sessions. "
        "The Core stores all data in a local SQLite database. "
        "Start each conversation with get_context to load previous context."
    ),
)


@mcp.tool()
def ping() -> str:
    """Ping the Pi Zero to test round-trip connectivity.

    Sends CMD:ping through the ESP32 BLE bridge and waits for CMD:pong.
    Use this to verify the full chain: Computer -> ESP32 -> BLE -> Pi.
    """
    try:
        lines = _bridge.send_and_wait("CMD:ping", timeout=5)
        if lines:
            return "Response: " + " | ".join(lines)
        return "No response (timeout). Check Cortex Link and Core are connected."
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def get_status() -> str:
    """Get the Pi Zero's current status.

    Returns uptime, connection info, storage stats, and recording state.
    """
    try:
        return send_command(_bridge, "status", timeout=5)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def send_note(content: str, tags: str = "", project: str = "", note_type: str = "note") -> str:
    """Send a text note to the Pi Zero for storage.

    Notes are timestamped and stored on the Pi's SD card for future analysis.

    Args:
        content: The note text to store.
        tags: Optional comma-separated tags for categorization
              (e.g. "idea,project,urgent").
        project: Optional project tag (e.g. "cortex", "bewell").
        note_type: Note type: note, decision, bug, reminder, idea, todo, context.
    """
    try:
        payload = {"content": content}
        if tags:
            payload["tags"] = tags
        if project:
            payload["project"] = project
        if note_type and note_type != "note":
            payload["type"] = note_type
        return send_command(_bridge, "note", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def log_activity(program: str, details: str = "", file_path: str = "", project: str = "") -> str:
    """Log what the user is currently working on.

    Records the program, optional file path, and details to the Pi for
    building an activity timeline.

    Args:
        program: Program name (e.g. "VS Code", "Chrome", "Terminal").
        details: Optional description of the activity.
        file_path: Optional file path being worked on.
        project: Optional project tag.
    """
    try:
        payload = {"program": program}
        if details:
            payload["details"] = details
        if file_path:
            payload["file_path"] = file_path
        if project:
            payload["project"] = project
        return send_command(_bridge, "activity", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def log_search(query: str, url: str = "", source: str = "web", project: str = "") -> str:
    """Log a web search or research query.

    Records searches for building a research history on the Pi.

    Args:
        query: The search query text.
        url: Optional URL of the search or result page.
        source: Search engine or source (e.g. "google", "github", "stackoverflow").
        project: Optional project tag.
    """
    try:
        payload = {"query": query, "source": source}
        if url:
            payload["url"] = url
        if project:
            payload["project"] = project
        return send_command(_bridge, "search", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def session_start(ai_platform: str = "claude") -> str:
    """Start a new Cortex session.

    Call this at the beginning of a conversation to register the session
    with Cortex Core. Returns a session_id for use in subsequent calls.

    Args:
        ai_platform: The AI platform name (e.g. "claude", "chatgpt").
    """
    try:
        payload = {
            "ai_platform": ai_platform,
            "hostname": socket.gethostname(),
            "os_info": "{} {}".format(platform.system(), platform.release()),
        }
        return send_command(_bridge, "session_start", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def session_end(session_id: str, summary: str, projects: str = "") -> str:
    """End a Cortex session.

    Call this before a conversation ends to record what was accomplished.

    Args:
        session_id: The session ID from session_start.
        summary: Brief summary of what was accomplished in this session.
        projects: Comma-separated project tags that were touched.
    """
    try:
        payload = {
            "session_id": session_id,
            "summary": summary,
        }
        if projects:
            payload["projects"] = projects
        return send_command(_bridge, "session_end", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def get_context() -> str:
    """Get full context for starting an informed AI session.

    Returns active projects, recent sessions, pending reminders,
    recent decisions, open bugs, and computer info. Call this at the
    start of every conversation to understand what the user is working on.
    """
    try:
        return send_command(_bridge, "get_context", timeout=20)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def query(table: str, filters: str = "", limit: int = 10, order_by: str = "created_at DESC") -> str:
    """Query the Cortex database on the Pi.

    Generic query interface for retrieving stored data.

    Args:
        table: Table to query (notes, activities, searches, sessions, projects, computers, people).
        filters: JSON string of filters, e.g. '{"project":"cortex","type":"bug"}'.
        limit: Max results to return (default 10).
        order_by: SQL ORDER BY clause (default "created_at DESC").
    """
    try:
        payload = {"table": table, "limit": limit, "order_by": order_by}
        if filters:
            try:
                payload["filters"] = json.loads(filters)
            except (json.JSONDecodeError, ValueError):
                return "Error: 'filters' must be valid JSON (e.g. '{\"project\":\"cortex\"}')"
        return send_command(_bridge, "query", payload, timeout=10)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def register_computer() -> str:
    """Register this computer with Cortex Core.

    Auto-detects hostname, OS, platform, and Python version.
    Useful for tracking which machines the user works on.
    """
    try:
        payload = {
            "hostname": socket.gethostname(),
            "os_info": "{} {} {}".format(
                platform.system(), platform.release(), platform.version()
            ),
            "platform": platform.machine(),
        }
        return send_command(_bridge, "computer_reg", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def send_message(message: str) -> str:
    """Send an arbitrary message to the Pi Zero through the bridge.

    Use for custom commands or data not covered by other tools.
    Messages are newline-delimited UTF-8, max 512 bytes.

    Args:
        message: The message to send.
    """
    try:
        lines = _bridge.send_and_wait(message, timeout=5)
        if lines:
            return "\n".join(lines)
        return "Sent (no response)."
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def read_responses() -> str:
    """Read any pending messages from the Pi Zero.

    Returns buffered messages that arrived without a preceding request.
    Useful for checking unsolicited data or async responses.
    """
    try:
        _bridge._ensure_connected()
        lines = _bridge.read_pending()
        if lines:
            return "\n".join(lines)
        return "No pending messages."
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def connection_info() -> str:
    """Show current serial connection status and available ports.

    Lists detected serial ports and the active connection details.
    """
    try:
        port_list = list_ports()

        info = "Available ports:\n"
        if port_list:
            info += "\n".join("  " + p for p in port_list)
        else:
            info += "  (none detected)"

        info += "\n\n"

        if _bridge.is_connected:
            info += "Connected: {}\n".format(_bridge.port_name)
            info += "Baud: {}\n".format(_bridge.baud_rate)
            info += "Buffered messages: {}".format(_bridge.buffered_count)
        else:
            info += "Status: Not connected"
            auto = find_esp32_port()
            if auto:
                info += "\nAuto-detected ESP32: {}".format(auto)

        return info
    except Exception as e:
        return "Error: {}".format(e)


def main():
    """Entry point for the cortex-mcp console script."""
    mcp.run()


if __name__ == "__main__":
    main()
