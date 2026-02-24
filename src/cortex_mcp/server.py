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
    """Get the best available bridge: WiFi (preferred) -> daemon -> direct serial.

    WiFi is fastest (direct HTTP to Pi, no BLE relay). Falls back to
    BLE chain if Pi WiFi is unreachable.

    Environment variables:
        CORTEX_DIRECT=1    - Skip WiFi and daemon, use serial directly
        CORTEX_NO_WIFI=1   - Skip WiFi, use daemon/serial only
    """
    if os.environ.get("CORTEX_DIRECT"):
        return SerialBridge()

    # Try WiFi first (direct to Pi, bypasses ESP32 BLE chain)
    if not os.environ.get("CORTEX_NO_WIFI"):
        try:
            from cortex_mcp.wifi_bridge import WiFiBridge, is_pi_reachable, get_wifi_token
            if get_wifi_token() and is_pi_reachable(timeout=1.0):
                return WiFiBridge()
        except Exception:
            pass

    # Try daemon (shared serial port)
    try:
        from cortex_mcp.daemon_client import DaemonBridge, is_daemon_running, ensure_daemon
        if is_daemon_running() or ensure_daemon():
            return DaemonBridge()
    except Exception:
        pass

    # Daemon unavailable, fall back to direct serial
    return SerialBridge()


# Lazy singleton bridge instance (deferred to avoid 1s WiFi timeout on import)
_bridge = None


def _get_bridge_lazy():
    """Get or initialize the bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = _get_bridge()
    return _bridge

# MCP server
mcp = FastMCP(
    "Cortex Bridge",
    instructions=(
        "Cortex is a wearable AI memory system. A Pi Zero 2 W (Cortex Core) "
        "worn by the user stores notes, sessions, activities, searches, and "
        "files in a local SQLite database. An ESP32-S3 USB dongle (Cortex Link) "
        "provides BLE connectivity as a fallback.\n\n"

        "TRANSPORT (automatic, no action needed): "
        "WiFi HTTP (preferred, direct to Pi on port 8420) -> "
        "TCP daemon (shared serial, localhost:19750) -> "
        "direct USB serial to ESP32 -> BLE to Pi. "
        "The active transport is chosen automatically at startup. "
        "WiFi is 10-100x faster than BLE and supports file transfer. "
        "Use connection_info to check which transport is active.\n\n"

        "RECOMMENDED WORKFLOW:\n"
        "1. Call get_context first -- returns active projects, recent sessions, "
        "pending reminders, open bugs, recent files, and DB stats.\n"
        "2. Call session_start to register this conversation.\n"
        "3. Use tools as needed during the session.\n"
        "4. Call session_end with a summary before the conversation ends.\n\n"

        "CAPABILITIES:\n"
        "- Notes: send_note (tags, project, type: note/decision/bug/reminder/idea/todo/context)\n"
        "- Sessions: session_start/session_end (tracks conversations across computers)\n"
        "- Activities: log_activity (program, file, project tracking)\n"
        "- Searches: log_search (research history)\n"
        "- Database: query any table (notes, activities, searches, sessions, "
        "projects, computers, people, files)\n"
        "- File metadata: file_register, file_list, file_search\n"
        "- File transfer (WiFi only): file_upload (local -> Pi), "
        "file_download (Pi -> local)\n"
        "- Diagnostics: ping, get_status, connection_info\n\n"

        "FILE OPERATIONS: Files on the Pi are organized by category: "
        "recordings, notes, logs, uploads. Use file_upload to send a file "
        "from this computer to the Pi over WiFi (auto-registers in DB). "
        "Use file_download to retrieve files. file_register records metadata "
        "for files already on the Pi. File transfer requires WiFi transport."
    ),
)


@mcp.tool()
def ping() -> str:
    """Ping the Pi Zero to test round-trip connectivity.

    Sends CMD:ping through the ESP32 BLE bridge and waits for CMD:pong.
    Use this to verify the full chain: Computer -> ESP32 -> BLE -> Pi.
    """
    try:
        lines = _get_bridge_lazy().send_and_wait("CMD:ping", timeout=5)
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
        return send_command(_get_bridge_lazy(), "status", timeout=5)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def send_note(content: str, tags: str = "", project: str = "", note_type: str = "note") -> str:
    """Send a text note to the Pi Zero for storage.

    Notes are timestamped and stored on the Pi's SD card for future analysis.
    Notes of any length are supported -- the transport handles chunking automatically.

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
        return send_command(_get_bridge_lazy(), "note", payload)
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
        return send_command(_get_bridge_lazy(), "activity", payload)
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
        return send_command(_get_bridge_lazy(), "search", payload)
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
        return send_command(_get_bridge_lazy(), "session_start", payload)
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
        return send_command(_get_bridge_lazy(), "session_end", payload)
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
        return send_command(_get_bridge_lazy(), "get_context", timeout=20)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def query(table: str, filters: str = "", limit: int = 10, order_by: str = "created_at DESC") -> str:
    """Query the Cortex database on the Pi.

    Generic query interface for retrieving stored data.

    Args:
        table: Table to query (notes, activities, searches, sessions, projects, computers, people, files).
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
        return send_command(_get_bridge_lazy(), "query", payload, timeout=10)
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
        return send_command(_get_bridge_lazy(), "computer_reg", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def file_register(filename: str, category: str = "uploads", description: str = "",
                  tags: str = "", project: str = "", mime_type: str = "",
                  size_bytes: int = 0) -> str:
    """Register a file in the Cortex database for sharing and discovery.

    Records file metadata so AI agents can find and serve files by context.
    The file must already exist on the Pi (in the appropriate category directory).

    To transfer a file FROM this computer to the Pi, use file_upload instead.
    file_upload auto-registers the file in the DB after upload.

    Args:
        filename: Name of the file on the Pi.
        category: File category: recordings, notes, logs, uploads.
        description: Human-readable description of the file contents.
        tags: Comma-separated tags for categorization.
        project: Project tag this file belongs to.
        mime_type: MIME type (auto-detected if empty).
        size_bytes: File size in bytes.
    """
    try:
        payload = {"filename": filename, "category": category}
        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = tags
        if project:
            payload["project"] = project
        if mime_type:
            payload["mime_type"] = mime_type
        if size_bytes:
            payload["size_bytes"] = size_bytes
        return send_command(_get_bridge_lazy(), "file_register", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def file_list(category: str = "", project: str = "", limit: int = 50) -> str:
    """List files registered in the Cortex database.

    Returns file metadata including name, description, tags, and download info.

    Args:
        category: Filter by category (recordings, notes, logs, uploads). Empty for all.
        project: Filter by project tag. Empty for all.
        limit: Max results (default 50).
    """
    try:
        payload = {"limit": limit}
        if category:
            payload["category"] = category
        if project:
            payload["project"] = project
        return send_command(_get_bridge_lazy(), "file_list", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def file_search(query: str, limit: int = 20) -> str:
    """Search for files by name, description, or tags.

    Searches across filename, description, and tags fields.

    Args:
        query: Search text to match against file metadata.
        limit: Max results (default 20).
    """
    try:
        payload = {"query": query, "limit": limit}
        return send_command(_get_bridge_lazy(), "file_search", payload)
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def file_upload(local_path: str, remote_name: str = "", description: str = "",
                tags: str = "", project: str = "") -> str:
    """Upload a file from this computer to the Pi Zero over WiFi.

    Transfers the file contents via HTTP and auto-registers it in the Cortex
    database with metadata. Only works when WiFi transport is active (not BLE).

    Use connection_info to verify WiFi is connected before uploading.

    Args:
        local_path: Absolute path to the file on this computer.
        remote_name: Filename on the Pi (defaults to local filename).
        description: Human-readable description of the file.
        tags: Comma-separated tags for categorization.
        project: Project tag this file belongs to.
    """
    try:
        bridge = _get_bridge_lazy()
        if not hasattr(bridge, "upload_file"):
            return ("Error: file_upload requires WiFi transport. "
                    "Current transport does not support file transfer. "
                    "Use connection_info to check WiFi status.")
        if not os.path.isfile(local_path):
            return "Error: file not found: {}".format(local_path)
        result = bridge.upload_file(
            local_path,
            remote_name=remote_name or None,
            description=description,
            tags=tags,
            project=project,
        )
        return "Uploaded: {} ({} bytes, file_id={})".format(
            result.get("filename"), result.get("size"), result.get("file_id"))
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def file_download(category: str, filename: str, local_path: str = "") -> str:
    """Download a file from the Pi Zero to this computer over WiFi.

    Retrieves file contents via HTTP. Only works when WiFi transport is active.

    Args:
        category: File category on the Pi: recordings, notes, logs, uploads.
        filename: Name of the file to download.
        local_path: Local destination path (defaults to current directory + filename).
    """
    try:
        bridge = _get_bridge_lazy()
        if not hasattr(bridge, "download_file"):
            return ("Error: file_download requires WiFi transport. "
                    "Current transport does not support file transfer. "
                    "Use connection_info to check WiFi status.")
        dest = local_path or os.path.join(".", filename)
        bridge.download_file(category, filename, dest)
        size = os.path.getsize(dest)
        return "Downloaded: {} -> {} ({} bytes)".format(filename, dest, size)
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
        lines = _get_bridge_lazy().send_and_wait(message, timeout=5)
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
        bridge = _get_bridge_lazy()
        bridge._ensure_connected()
        lines = bridge.read_pending()
        if lines:
            return "\n".join(lines)
        return "No pending messages."
    except Exception as e:
        return "Error: {}".format(e)


@mcp.tool()
def connection_info() -> str:
    """Show current connection status and available ports.

    Lists detected serial ports, WiFi status, and the active connection details.
    Transport hierarchy: WiFi HTTP (fastest) -> TCP daemon -> direct serial (BLE).
    File upload/download only work over WiFi transport.
    """
    try:
        bridge = _get_bridge_lazy()
        info = ""

        # WiFi status
        try:
            from cortex_mcp.wifi_bridge import is_pi_reachable, get_pi_host, get_pi_port, get_wifi_token
            host = get_pi_host()
            port = get_pi_port()
            has_token = bool(get_wifi_token())
            if has_token and is_pi_reachable(timeout=1.0):
                info += "WiFi: connected (http://{}:{})\n".format(host, port)
            elif has_token:
                info += "WiFi: unreachable ({}:{})\n".format(host, port)
            else:
                info += "WiFi: no token configured\n"
        except Exception:
            info += "WiFi: not available\n"

        info += "Active transport: {}\n\n".format(bridge.port_name)

        # Serial ports
        port_list = list_ports()
        info += "Available ports:\n"
        if port_list:
            info += "\n".join("  " + p for p in port_list)
        else:
            info += "  (none detected)"

        info += "\n\n"

        if bridge.is_connected:
            info += "Connected: {}\n".format(bridge.port_name)
            if bridge.baud_rate:
                info += "Baud: {}\n".format(bridge.baud_rate)
            info += "Buffered messages: {}".format(bridge.buffered_count)
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
