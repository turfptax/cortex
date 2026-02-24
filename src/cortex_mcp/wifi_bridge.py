"""WiFi HTTP bridge to Cortex Core (Pi Zero 2 W).

WiFiBridge is a drop-in replacement for SerialBridge that routes
commands directly to the Pi over HTTP, bypassing the ESP32 BLE chain.

Data flow:
    AI Agent -> MCP Server -> WiFiBridge -> HTTP -> Pi (direct)

Fallback (when Pi WiFi unreachable):
    AI Agent -> MCP Server -> DaemonBridge -> USB Serial -> ESP32 -> BLE -> Pi

Uses only urllib.request (stdlib) -- no new dependencies.
"""

import json
import os
import urllib.request
import urllib.error

DEFAULT_PI_HOST = "10.0.0.132"
DEFAULT_PI_PORT = 8420
DISCOVERY_FILE = os.path.join(os.path.expanduser("~"), ".cortex-wifi.json")


def _load_discovery():
    """Load discovered Pi config from ~/.cortex-wifi.json (set by BLE auto-discovery)."""
    try:
        with open(DISCOVERY_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_pi_host():
    """Get Pi IP from env var, BLE discovery, or default."""
    env = os.environ.get("CORTEX_PI_HOST", "")
    if env:
        return env
    discovered = _load_discovery()
    return discovered.get("ip", DEFAULT_PI_HOST)


def get_pi_port():
    """Get Pi HTTP port from env var, BLE discovery, or default."""
    env = os.environ.get("CORTEX_PI_PORT", "")
    if env:
        return int(env)
    discovered = _load_discovery()
    return discovered.get("port", DEFAULT_PI_PORT)


def get_wifi_token():
    """Read WiFi bearer token from env var, BLE discovery, or token file."""
    token = os.environ.get("CORTEX_WIFI_TOKEN", "")
    if token:
        return token
    # Try discovery file first (set by BLE auto-discovery)
    discovered = _load_discovery()
    token = discovered.get("token", "")
    if token:
        return token
    # Fallback to standalone token file
    token_file = os.path.join(os.path.expanduser("~"), ".cortex-wifi.token")
    try:
        with open(token_file, "r") as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def is_pi_reachable(host=None, port=None, timeout=1.0):
    """Quick health check -- is the Pi HTTP server responding?

    Used by _get_bridge() to decide whether to use WiFi or BLE.
    The /health endpoint requires no auth and returns minimal JSON.
    """
    host = host or get_pi_host()
    port = port or get_pi_port()
    url = "http://{}:{}/health".format(host, port)
    try:
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data.get("ok", False)
    except Exception:
        return False


class WiFiBridge:
    """Drop-in replacement for SerialBridge/DaemonBridge using HTTP to Pi.

    Provides the same send_and_wait() interface so the MCP server and CLI
    can use it transparently.
    """

    def __init__(self, host=None, port=None, token=None):
        self._host = host or get_pi_host()
        self._port = port or get_pi_port()
        self._token = token or get_wifi_token()
        self._base = "http://{}:{}".format(self._host, self._port)

    def _request(self, method, path, body=None, timeout=10, stream=False):
        """Make an authenticated HTTP request."""
        url = self._base + path
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        if self._token:
            req.add_header("Authorization", "Bearer {}".format(self._token))
        if data:
            req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            return resp
        return json.loads(resp.read())

    def send_and_wait(self, message, timeout=None, settle=None):
        """Send a CMD: message via HTTP and return response lines.

        The HTTP endpoint calls CortexProtocol.handle_message() directly
        and returns the response synchronously -- no chunking needed.
        """
        timeout = timeout or 10

        # Parse CMD: message into command + payload
        if message.startswith("CMD:"):
            rest = message[4:]
            colon = rest.find(":")
            if colon == -1:
                command = rest.strip()
                payload = None
            else:
                command = rest[:colon].strip()
                payload_str = rest[colon + 1:]
                try:
                    payload = json.loads(payload_str)
                except (json.JSONDecodeError, ValueError):
                    payload = payload_str
        else:
            command = message
            payload = None

        body = {"command": command}
        if payload is not None:
            body["payload"] = payload

        result = self._request("POST", "/api/cmd", body, timeout=timeout)
        response = result.get("response", "")
        if response:
            return [response]
        return []

    def send(self, message):
        """Fire-and-forget send."""
        self.send_and_wait(message, timeout=5)

    def read_pending(self):
        """No pending messages over HTTP (request/response model)."""
        return []

    def connect(self, port=None, baud=None):
        """No-op for WiFi bridge."""
        pass

    def disconnect(self):
        """No-op for WiFi bridge."""
        pass

    def _ensure_connected(self):
        """No-op for WiFi bridge."""
        pass

    @property
    def is_connected(self):
        return True  # Assume connected; send_and_wait will fail if not

    @property
    def port_name(self):
        return "wifi://{}:{}".format(self._host, self._port)

    @property
    def baud_rate(self):
        return 0  # N/A

    @property
    def buffered_count(self):
        return 0

    @property
    def default_timeout(self):
        return 10.0

    # -- File operations (WiFi-only features) --

    def list_files(self, category):
        """List files in a category (recordings, notes, logs, uploads)."""
        return self._request("GET", "/files/{}".format(category))

    def download_file(self, category, filename, local_path):
        """Download a file from the Pi to a local path."""
        url = "{}/files/{}/{}".format(self._base, category, filename)
        req = urllib.request.Request(url)
        if self._token:
            req.add_header("Authorization", "Bearer {}".format(self._token))
        resp = urllib.request.urlopen(req, timeout=120)
        with open(local_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)

    def upload_file(self, local_path, remote_name=None, description="",
                    tags="", project=""):
        """Upload a file to the Pi's uploads directory."""
        filename = remote_name or os.path.basename(local_path)
        with open(local_path, "rb") as f:
            data = f.read()
        url = "{}/files/uploads".format(self._base)
        req = urllib.request.Request(url, data=data, method="POST")
        if self._token:
            req.add_header("Authorization", "Bearer {}".format(self._token))
        req.add_header("X-Filename", filename)
        req.add_header("Content-Length", str(len(data)))
        if description:
            req.add_header("X-Description", description)
        if tags:
            req.add_header("X-Tags", tags)
        if project:
            req.add_header("X-Project", project)
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read())

    def download_db(self, local_path):
        """Download the cortex.db database snapshot."""
        url = "{}/files/db".format(self._base)
        req = urllib.request.Request(url)
        if self._token:
            req.add_header("Authorization", "Bearer {}".format(self._token))
        resp = urllib.request.urlopen(req, timeout=120)
        with open(local_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
