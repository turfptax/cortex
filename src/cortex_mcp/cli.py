"""Cortex CLI - interact with Cortex Core via Cortex Link (ESP32).

Usage:
    cortex-cli ping
    cortex-cli context
    cortex-cli note "My note text" --project cortex --tags idea,important
    cortex-cli query notes --limit 5
"""

import json
import socket
import platform

import click

from cortex_mcp.bridge import SerialBridge, find_esp32_port, list_ports
from cortex_mcp.protocol import send_command


pass_bridge = click.make_pass_decorator(SerialBridge, ensure=True)


@click.group()
@click.option("--port", envvar="CORTEX_PORT", default=None, help="Serial port (auto-detects ESP32).")
@click.option("--baud", envvar="CORTEX_BAUD", default=115200, type=int, help="Baud rate.")
@click.option("--timeout", envvar="CORTEX_TIMEOUT", default=5.0, type=float, help="Response timeout in seconds.")
@click.pass_context
def cli(ctx, port, baud, timeout):
    """Cortex CLI - interact with Cortex Core via Cortex Link (ESP32)."""
    ctx.ensure_object(dict)
    ctx.obj = SerialBridge(port=port, baud=baud, timeout=timeout)


@cli.command()
@click.pass_obj
def ping(bridge):
    """Test round-trip connectivity to Cortex Core."""
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
@click.pass_obj
def status(bridge):
    """Get Cortex Core status (uptime, storage, recording state)."""
    click.echo(send_command(bridge, "status", timeout=5))


@cli.command()
@click.pass_obj
def context(bridge):
    """Get full context for starting an AI session."""
    click.echo(send_command(bridge, "get_context", timeout=20))


@cli.command()
@click.argument("content")
@click.option("--tags", "-t", default="", help="Comma-separated tags.")
@click.option("--project", "-p", default="", help="Project tag.")
@click.option("--type", "note_type", default="note",
              type=click.Choice(["note", "decision", "bug", "reminder", "idea", "todo", "context"]),
              help="Note type.")
@click.pass_obj
def note(bridge, content, tags, project, note_type):
    """Store a note on Cortex Core."""
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
@click.pass_obj
def activity(bridge, program, details, file_path, project):
    """Log an activity (what program/file you're working on)."""
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
@click.pass_obj
def search(bridge, query_text, source, url, project):
    """Log a search query."""
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
@click.pass_obj
def session_start(bridge, ai_platform):
    """Start a new Cortex session."""
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
@click.pass_obj
def session_end(bridge, session_id, summary, projects):
    """End a Cortex session with a summary."""
    payload = {"session_id": session_id, "summary": summary}
    if projects:
        payload["projects"] = projects
    click.echo(send_command(bridge, "session_end", payload))


@cli.command()
@click.argument("table")
@click.option("--filters", "-f", default="", help='JSON filters, e.g. \'{"project":"cortex"}\'.')
@click.option("--limit", "-n", default=10, type=int, help="Max results.")
@click.option("--order-by", default="created_at DESC", help="SQL ORDER BY clause.")
@click.pass_obj
def query(bridge, table, filters, limit, order_by):
    """Query the Cortex database."""
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
@click.pass_obj
def raw(bridge, message):
    """Send a raw message to Cortex Link."""
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


def main():
    """Entry point for the cortex-cli console script."""
    cli()


if __name__ == "__main__":
    main()
