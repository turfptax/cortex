"""Cortex Daemon — shared serial port server.

Holds the ESP32 serial port exclusively and serves multiple clients
over TCP. This solves COM port contention when multiple AI sessions
(Claude Code, Claude Desktop, cortex-cli) need concurrent access.

Architecture:
    cortex-mcp #1 ──TCP──┐
    cortex-mcp #2 ──TCP──├──> cortex-daemon ──serial──> ESP32 ──BLE──> Pi
    cortex-cli ───────TCP─┘    (localhost:19750)

TCP Protocol (JSON-over-TCP, newline-delimited):
    Request:  {"cmd": "send_and_wait", "message": "CMD:ping", "timeout": 5}
    Response: {"ok": true, "lines": ["RSP:pong"]}
"""

import json
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from cortex_mcp.bridge import SerialBridge, find_esp32_port, list_ports

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19750

LOCK_FILE = Path.home() / ".cortex-daemon.lock"


def get_daemon_port():
    """Get daemon TCP port from env or default."""
    return int(os.environ.get("CORTEX_DAEMON_PORT", DEFAULT_PORT))


def get_daemon_host():
    """Get daemon host from env or default."""
    return os.environ.get("CORTEX_DAEMON_HOST", DEFAULT_HOST)


class DaemonHandler(socketserver.StreamRequestHandler):
    """Handle a single TCP client request.

    Each connection sends one JSON request line and receives one JSON
    response line. The serial bridge is accessed under a lock so
    concurrent clients are serialized.
    """

    def handle(self):
        try:
            raw = self.rfile.readline()
            if not raw:
                return
            raw = raw.decode("utf-8").strip()
            if not raw:
                return

            try:
                request = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                self._respond({"ok": False, "error": "Invalid JSON"})
                return

            cmd = request.get("cmd", "")
            response = self.server.daemon.handle_command(cmd, request)
            self._respond(response)

        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception as e:
            try:
                self._respond({"ok": False, "error": str(e)})
            except Exception:
                pass

    def _respond(self, data):
        line = json.dumps(data) + "\n"
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()


class CortexDaemonServer(socketserver.ThreadingTCPServer):
    """TCP server that holds a reference to the daemon."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, daemon):
        self.daemon = daemon
        super().__init__(server_address, handler_class)


class CortexDaemon:
    """Cortex daemon that owns the serial bridge and serves TCP clients."""

    def __init__(self, serial_port=None, baud=None, timeout=None,
                 host=None, daemon_port=None):
        self.host = host or get_daemon_host()
        self.daemon_port = daemon_port or get_daemon_port()
        self.bridge = SerialBridge(port=serial_port, baud=baud, timeout=timeout)
        self._lock = threading.Lock()
        self._server = None
        self._clients_served = 0
        self._start_time = None

    def handle_command(self, cmd, request):
        """Process a client command under the serial lock."""
        if cmd == "shutdown":
            threading.Thread(target=self._shutdown, daemon=True).start()
            return {"ok": True, "message": "Shutting down"}

        if cmd == "info":
            return {
                "ok": True,
                "port": self.bridge.port_name,
                "baud": self.bridge.baud_rate,
                "connected": self.bridge.is_connected,
                "buffered": self.bridge.buffered_count,
                "clients_served": self._clients_served,
                "uptime": time.time() - self._start_time if self._start_time else 0,
                "pid": os.getpid(),
            }

        if cmd == "send_and_wait":
            message = request.get("message", "")
            timeout = request.get("timeout", self.bridge.default_timeout)
            settle = request.get("settle", 0.4)
            if not message:
                return {"ok": False, "error": "Missing 'message'"}
            with self._lock:
                self._clients_served += 1
                try:
                    lines = self.bridge.send_and_wait(
                        message, timeout=timeout, settle=settle
                    )
                    return {"ok": True, "lines": lines}
                except Exception as e:
                    return {"ok": False, "error": str(e)}

        if cmd == "send_raw":
            message = request.get("message", "")
            if not message:
                return {"ok": False, "error": "Missing 'message'"}
            with self._lock:
                self._clients_served += 1
                try:
                    self.bridge.send(message)
                    return {"ok": True}
                except Exception as e:
                    return {"ok": False, "error": str(e)}

        if cmd == "read_pending":
            with self._lock:
                try:
                    self.bridge._ensure_connected()
                    lines = self.bridge.read_pending()
                    return {"ok": True, "lines": lines}
                except Exception as e:
                    return {"ok": False, "error": str(e)}

        if cmd == "ping":
            return {"ok": True, "message": "daemon alive", "pid": os.getpid()}

        return {"ok": False, "error": "Unknown command: {}".format(cmd)}

    def run(self):
        """Start the daemon: connect to serial, serve TCP forever."""
        self._start_time = time.time()

        # Connect to ESP32
        try:
            self.bridge.connect()
            port_name = self.bridge.port_name
        except ConnectionError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)

        # Write lock file
        _write_lock_file(os.getpid(), self.daemon_port)

        # Set up signal handlers for clean shutdown
        signal.signal(signal.SIGINT, lambda *_: self._shutdown())
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())

        print("Cortex daemon started (PID {})".format(os.getpid()))
        print("  Serial: {} @ {}".format(port_name, self.bridge.baud_rate))
        print("  TCP:    {}:{}".format(self.host, self.daemon_port))

        # Start TCP server
        self._server = CortexDaemonServer(
            (self.host, self.daemon_port), DaemonHandler, self
        )

        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()

    def _shutdown(self):
        """Gracefully shut down the daemon."""
        if self._server:
            self._server.shutdown()

    def _cleanup(self):
        """Clean up resources on exit."""
        print("\nDaemon shutting down...")
        try:
            self.bridge.disconnect()
        except Exception:
            pass
        _remove_lock_file()
        print("Done.")


def _write_lock_file(pid, port):
    """Write daemon PID and port to lock file."""
    try:
        LOCK_FILE.write_text(
            json.dumps({"pid": pid, "port": port}) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _remove_lock_file():
    """Remove the daemon lock file."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def read_lock_file():
    """Read daemon info from lock file. Returns dict or None."""
    try:
        if LOCK_FILE.exists():
            data = json.loads(LOCK_FILE.read_text(encoding="utf-8").strip())
            return data
    except Exception:
        pass
    return None


def is_pid_alive(pid):
    """Check if a process with given PID is running."""
    if pid is None:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


def main():
    """Entry point for the cortex-daemon console script."""
    import argparse

    parser = argparse.ArgumentParser(description="Cortex daemon — shared serial port server")
    parser.add_argument("--port", default=None, help="Serial port (auto-detects ESP32)")
    parser.add_argument("--baud", default=None, type=int, help="Baud rate")
    parser.add_argument("--timeout", default=None, type=float, help="Serial timeout")
    parser.add_argument("--host", default=None, help="TCP host (default: 127.0.0.1)")
    parser.add_argument("--daemon-port", default=None, type=int, help="TCP port (default: 19750)")
    args = parser.parse_args()

    daemon = CortexDaemon(
        serial_port=args.port,
        baud=args.baud,
        timeout=args.timeout,
        host=args.host,
        daemon_port=args.daemon_port,
    )
    daemon.run()


if __name__ == "__main__":
    main()
