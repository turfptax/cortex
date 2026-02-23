"""Cortex CLI - interact with Cortex Core via Cortex Link (ESP32).

Usage:
    cortex-cli ping
    cortex-cli context
    cortex-cli note "My note text" --project cortex --tags idea,important
    cortex-cli query notes --limit 5
    cortex-cli daemon status
"""

import json
import os
import socket
import platform
from pathlib import Path

import click

from cortex_mcp.bridge import SerialBridge, find_esp32_port, list_ports
from cortex_mcp.protocol import send_command


def _get_bridge(ctx):
    """Get the bridge from context, using daemon or direct serial."""
    obj = ctx.find_object(dict) or {}

    # If --direct flag or CORTEX_DIRECT env var, use serial directly
    if obj.get("direct") or os.environ.get("CORTEX_DIRECT"):
        return SerialBridge(
            port=obj.get("port"),
            baud=obj.get("baud"),
            timeout=obj.get("timeout"),
        )

    # Try daemon first
    try:
        from cortex_mcp.daemon_client import DaemonBridge, is_daemon_running, ensure_daemon
        if is_daemon_running() or ensure_daemon(
            serial_port=obj.get("port"),
            baud=obj.get("baud"),
            timeout=obj.get("timeout"),
        ):
            return DaemonBridge()
    except Exception:
        pass

    # Fall back to direct serial
    return SerialBridge(
        port=obj.get("port"),
        baud=obj.get("baud"),
        timeout=obj.get("timeout"),
    )


@click.group()
@click.option("--port", envvar="CORTEX_PORT", default=None, help="Serial port (auto-detects ESP32).")
@click.option("--baud", envvar="CORTEX_BAUD", default=115200, type=int, help="Baud rate.")
@click.option("--timeout", envvar="CORTEX_TIMEOUT", default=5.0, type=float, help="Response timeout in seconds.")
@click.option("--direct", is_flag=True, default=False, help="Bypass daemon, use serial port directly.")
@click.pass_context
def cli(ctx, port, baud, timeout, direct):
    """Cortex CLI - interact with Cortex Core via Cortex Link (ESP32)."""
    ctx.ensure_object(dict)
    ctx.obj = {"port": port, "baud": baud, "timeout": timeout, "direct": direct}


@cli.command()
@click.pass_context
def ping(ctx):
    """Test round-trip connectivity to Cortex Core."""
    bridge = _get_bridge(ctx)
    try:
        lines = bridge.send_and_wait("CMD:ping", timeout=5)
        if lines:
            click.echo(" | ".join(lines))
        else:
            click.echo("No response (timeout).", err=True)
            raise SystemExit(1)
    except ConnectionError as e:
        click.echo("Connection error: {}".format(e), err=True)
        raise SystemExit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """Get Cortex Core status (uptime, storage, recording state)."""
    bridge = _get_bridge(ctx)
    click.echo(send_command(bridge, "status", timeout=5))


@cli.command()
@click.pass_context
def context(ctx):
    """Get full context for starting an AI session."""
    bridge = _get_bridge(ctx)
    click.echo(send_command(bridge, "get_context", timeout=20))


@cli.command()
@click.argument("content")
@click.option("--tags", "-t", default="", help="Comma-separated tags.")
@click.option("--project", "-p", default="", help="Project tag.")
@click.option("--type", "note_type", default="note",
              type=click.Choice(["note", "decision", "bug", "reminder", "idea", "todo", "context"]),
              help="Note type.")
@click.pass_context
def note(ctx, content, tags, project, note_type):
    """Store a note on Cortex Core."""
    bridge = _get_bridge(ctx)
    payload = {"content": content}
    if tags:
        payload["tags"] = tags
    if project:
        payload["project"] = project
    if note_type != "note":
        payload["type"] = note_type
    click.echo(send_command(bridge, "note", payload))


@cli.command()
@click.argument("program")
@click.option("--details", "-d", default="", help="Activity description.")
@click.option("--file", "file_path", default="", help="File path being worked on.")
@click.option("--project", "-p", default="", help="Project tag.")
@click.pass_context
def activity(ctx, program, details, file_path, project):
    """Log an activity (what program/file you're working on)."""
    bridge = _get_bridge(ctx)
    payload = {"program": program}
    if details:
        payload["details"] = details
    if file_path:
        payload["file_path"] = file_path
    if project:
        payload["project"] = project
    click.echo(send_command(bridge, "activity", payload))


@cli.command()
@click.argument("query_text")
@click.option("--source", "-s", default="web", help="Search source (google, github, etc.).")
@click.option("--url", "-u", default="", help="URL of the result.")
@click.option("--project", "-p", default="", help="Project tag.")
@click.pass_context
def search(ctx, query_text, source, url, project):
    """Log a search query."""
    bridge = _get_bridge(ctx)
    payload = {"query": query_text, "source": source}
    if url:
        payload["url"] = url
    if project:
        payload["project"] = project
    click.echo(send_command(bridge, "search", payload))


@cli.group()
def session():
    """Manage Cortex sessions (start/end)."""
    pass


@session.command("start")
@click.option("--platform", "ai_platform", default="claude", help="AI platform name.")
@click.pass_context
def session_start(ctx, ai_platform):
    """Start a new Cortex session."""
    bridge = _get_bridge(ctx)
    payload = {
        "ai_platform": ai_platform,
        "hostname": socket.gethostname(),
        "os_info": "{} {}".format(platform.system(), platform.release()),
    }
    click.echo(send_command(bridge, "session_start", payload))


@session.command("end")
@click.argument("session_id")
@click.argument("summary")
@click.option("--projects", default="", help="Comma-separated project tags.")
@click.pass_context
def session_end(ctx, session_id, summary, projects):
    """End a Cortex session with a summary."""
    bridge = _get_bridge(ctx)
    payload = {"session_id": session_id, "summary": summary}
    if projects:
        payload["projects"] = projects
    click.echo(send_command(bridge, "session_end", payload))


@cli.command()
@click.argument("table")
@click.option("--filters", "-f", default="", help='JSON filters, e.g. \'{"project":"cortex"}\'.')
@click.option("--limit", "-n", default=10, type=int, help="Max results.")
@click.option("--order-by", default="created_at DESC", help="SQL ORDER BY clause.")
@click.pass_context
def query(ctx, table, filters, limit, order_by):
    """Query the Cortex database."""
    bridge = _get_bridge(ctx)
    payload = {"table": table, "limit": limit, "order_by": order_by}
    if filters:
        try:
            payload["filters"] = json.loads(filters)
        except (json.JSONDecodeError, ValueError):
            click.echo("Error: --filters must be valid JSON.", err=True)
            raise SystemExit(1)
    click.echo(send_command(bridge, "query", payload, timeout=10))


@cli.command()
@click.argument("message")
@click.pass_context
def raw(ctx, message):
    """Send a raw message to Cortex Link."""
    bridge = _get_bridge(ctx)
    lines = bridge.send_and_wait(message, timeout=5)
    if lines:
        click.echo("\n".join(lines))
    else:
        click.echo("Sent (no response).")


@cli.command()
def info():
    """Show serial connection info and available ports."""
    ports = list_ports()
    click.echo("Available ports:")
    if ports:
        for p in ports:
            click.echo("  " + p)
    else:
        click.echo("  (none detected)")

    auto = find_esp32_port()
    if auto:
        click.echo("\nAuto-detected ESP32: {}".format(auto))
    else:
        click.echo("\nNo ESP32 auto-detected.")

    # Check daemon status
    try:
        from cortex_mcp.daemon_client import is_daemon_running, DaemonBridge
        if is_daemon_running():
            db = DaemonBridge()
            info_data = db._get_info()
            click.echo("\nDaemon: running (PID {})".format(info_data.get("pid", "?")))
            click.echo("  Serial: {} @ {}".format(
                info_data.get("port", "?"),
                info_data.get("baud", "?"),
            ))
            click.echo("  Clients served: {}".format(info_data.get("clients_served", 0)))
        else:
            click.echo("\nDaemon: not running")
    except Exception:
        click.echo("\nDaemon: not running")


# -- Daemon subcommands --

@cli.group()
def daemon():
    """Manage the Cortex daemon (shared serial port server)."""
    pass


@daemon.command("start")
@click.option("--background/--foreground", default=True,
              help="Run in background (default) or foreground.")
@click.pass_context
def daemon_start(ctx, background):
    """Start the Cortex daemon."""
    from cortex_mcp.daemon_client import is_daemon_running

    if is_daemon_running():
        click.echo("Daemon is already running.")
        return

    obj = ctx.find_object(dict) or {}

    if background:
        from cortex_mcp.daemon_client import ensure_daemon
        click.echo("Starting daemon in background...")
        if ensure_daemon(
            serial_port=obj.get("port"),
            baud=obj.get("baud"),
            timeout=obj.get("timeout"),
        ):
            click.echo("Daemon started successfully.")
        else:
            click.echo("Failed to start daemon.", err=True)
            raise SystemExit(1)
    else:
        # Run in foreground (blocks)
        from cortex_mcp.daemon import CortexDaemon
        d = CortexDaemon(
            serial_port=obj.get("port"),
            baud=obj.get("baud"),
            timeout=obj.get("timeout"),
        )
        d.run()


@daemon.command("stop")
def daemon_stop():
    """Stop the running Cortex daemon."""
    from cortex_mcp.daemon_client import is_daemon_running, DaemonBridge

    if not is_daemon_running():
        click.echo("Daemon is not running.")
        return

    db = DaemonBridge()
    resp = db._request({"cmd": "shutdown"}, timeout=3)
    if resp.get("ok"):
        click.echo("Daemon shutdown requested.")
    else:
        click.echo("Error: {}".format(resp.get("error", "Unknown")), err=True)


@daemon.command("status")
def daemon_status():
    """Check if the Cortex daemon is running."""
    from cortex_mcp.daemon_client import is_daemon_running, DaemonBridge
    from cortex_mcp.daemon import read_lock_file

    if is_daemon_running():
        db = DaemonBridge()
        info_data = db._get_info()
        click.echo("Daemon: running")
        click.echo("  PID:      {}".format(info_data.get("pid", "?")))
        click.echo("  Serial:   {} @ {}".format(
            info_data.get("port", "?"),
            info_data.get("baud", "?"),
        ))
        click.echo("  Connected: {}".format(info_data.get("connected", False)))
        click.echo("  Buffered:  {}".format(info_data.get("buffered", 0)))
        click.echo("  Served:    {} requests".format(info_data.get("clients_served", 0)))
        uptime = info_data.get("uptime", 0)
        if uptime:
            mins = int(uptime // 60)
            secs = int(uptime % 60)
            click.echo("  Uptime:    {}m {}s".format(mins, secs))
    else:
        click.echo("Daemon: not running")
        lock = read_lock_file()
        if lock:
            click.echo("  (stale lock file found, PID {})".format(lock.get("pid")))


# -- Setup command --

@cli.command()
@click.option("--target", type=click.Choice(["claude-code", "claude-desktop"]),
              default="claude-code", help="Which Claude app to configure.")
def setup(target):
    """Auto-configure Claude Code or Claude Desktop to use Cortex MCP.

    Uses the current Python interpreter with -m cortex_mcp.server, which
    avoids Windows PATH issues (pip Scripts dir often isn't on PATH).
    """
    import sys

    # Use the Python that has cortex-mcp installed (the one running this script)
    python_exe = str(Path(sys.executable).resolve())
    click.echo("Using Python: {}".format(python_exe))

    # Build the MCP server entry — portable across all platforms
    mcp_entry = {
        "command": python_exe,
        "args": ["-m", "cortex_mcp.server"],
    }

    if target == "claude-code":
        config_path = Path.home() / ".claude.json"

        # Read existing config or start fresh
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                click.echo("Warning: existing {} is invalid JSON, creating new.".format(config_path))

        # Add/update mcpServers.cortex
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        config["mcpServers"]["cortex"] = mcp_entry

        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        click.echo("Wrote Claude Code config to: {}".format(config_path))
        click.echo("\nRestart Claude Code to pick up the new MCP server.")

    elif target == "claude-desktop":
        if platform.system() == "Windows":
            config_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
        elif platform.system() == "Darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                click.echo("Warning: existing {} is invalid JSON, creating new.".format(config_path))

        if "mcpServers" not in config:
            config["mcpServers"] = {}
        config["mcpServers"]["cortex"] = mcp_entry

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        click.echo("Wrote Claude Desktop config to: {}".format(config_path))
        click.echo("\nRestart Claude Desktop to pick up the new MCP server.")

    click.echo("\nVerify with: python -m cortex_mcp ping")


def main():
    """Entry point for the cortex-cli console script."""
    cli()


if __name__ == "__main__":
    main()
