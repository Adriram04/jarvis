"""
Regenerate the Google Calendar OAuth refresh token for JARVIS.

Runs a local OAuth "loopback" flow using only the Python standard library
(no extra dependencies). Reads CLIENT_ID / CLIENT_SECRET from the project .env,
opens the browser for you to grant access, exchanges the code for tokens, and
writes the new refresh token into:
  1. the project .env   (JARVIS_GOOGLE_CALENDAR_REFRESH_TOKEN)
  2. ~/.openclaw/openclaw.json  (plugins.entries["jarvis-productivity"].config)

Usage:
  python scripts/get_google_calendar_token.py

Notes:
  - The OAuth client in Google Cloud Console must allow the redirect URI
    http://localhost:<port>/  (default port 8765). For a "Desktop app" client
    type, loopback is allowed automatically. For a "Web application" client,
    add http://localhost:8765/ as an Authorized redirect URI.
  - Run this whenever the calendar shows: invalid_grant / "Token has been
    expired or revoked".
"""

import json
import os
import sys
import time
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"

SCOPE = "https://www.googleapis.com/auth/calendar"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
PRODUCTIVITY_PLUGIN_ID = "jarvis-productivity"

DEFAULT_PORT = int(os.getenv("JARVIS_GOOGLE_OAUTH_PORT", "8765") or 8765)


def _load_env_file(path):
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        values[key] = val
    return values


def _update_env_refresh_token(path, token):
    """Replace (or append) JARVIS_GOOGLE_CALENDAR_REFRESH_TOKEN in .env, preserving the rest."""
    key = "JARVIS_GOOGLE_CALENDAR_REFRESH_TOKEN"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    found = False
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            out.append(f"{key}={token}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={token}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _update_openclaw_config(token, client_id, client_secret, calendar_id):
    """Best-effort: write the refresh token into the OpenClaw productivity plugin config."""
    config_path = Path(
        os.getenv("JARVIS_OPENCLAW_CONFIG")
        or os.getenv("OPENCLAW_CONFIG")
        or (Path.home() / ".openclaw" / "openclaw.json")
    ).expanduser()
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        entries = config.setdefault("plugins", {}).setdefault("entries", {})
        entry = entries.setdefault(PRODUCTIVITY_PLUGIN_ID, {})
        entry["enabled"] = True
        plugin_cfg = entry.setdefault("config", {})
        gcal = plugin_cfg.setdefault("googleCalendar", {})
        gcal["refreshToken"] = token
        if client_id:
            gcal["clientId"] = client_id
        if client_secret:
            gcal["clientSecret"] = client_secret
        if calendar_id:
            gcal.setdefault("calendarId", calendar_id)
        # Drop any stale short-lived access token so the plugin uses the refresh token
        gcal.pop("accessToken", None)
        # Backup then write
        backup = config_path.with_name(f"{config_path.name}.jarvis-backup-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(config_path)
    except Exception as exc:
        print(f"[WARN] No se pudo actualizar openclaw.json: {exc}")
        return None


class _CodeHandler(BaseHTTPRequestHandler):
    code_holder = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        _CodeHandler.code_holder["code"] = code
        _CodeHandler.code_holder["error"] = error
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            body = "<h2>JARVIS: autorizacion recibida. Ya puedes cerrar esta pestana.</h2>"
        else:
            body = f"<h2>JARVIS: error en la autorizacion: {error}</h2>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):
        pass  # silence the default HTTP logging


def run_oauth_flow(port=DEFAULT_PORT, open_browser=True):
    """Run the loopback OAuth flow. Returns dict with success / refresh_token / error."""
    env = _load_env_file(ENV_PATH)
    client_id = os.getenv("JARVIS_GOOGLE_CALENDAR_CLIENT_ID") or env.get("JARVIS_GOOGLE_CALENDAR_CLIENT_ID", "")
    client_secret = os.getenv("JARVIS_GOOGLE_CALENDAR_CLIENT_SECRET") or env.get("JARVIS_GOOGLE_CALENDAR_CLIENT_SECRET", "")
    calendar_id = os.getenv("JARVIS_GOOGLE_CALENDAR_ID") or env.get("JARVIS_GOOGLE_CALENDAR_ID", "primary")

    if not client_id or not client_secret:
        return {"success": False, "error": "Faltan JARVIS_GOOGLE_CALENDAR_CLIENT_ID / CLIENT_SECRET en .env"}

    redirect_uri = f"http://localhost:{port}/"
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # force a refresh_token even if previously granted
    }
    auth_url = f"{AUTH_URI}?{urllib.parse.urlencode(auth_params)}"

    _CodeHandler.code_holder = {}
    try:
        server = HTTPServer(("127.0.0.1", port), _CodeHandler)
    except OSError as exc:
        return {"success": False, "error": f"No se pudo abrir el puerto {port}: {exc}"}

    server.timeout = 1
    print(f"\n[OAuth] Abriendo el navegador para autorizar Google Calendar...")
    print(f"[OAuth] Si no se abre, visita manualmente:\n{auth_url}\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    # Wait for the redirect (up to 5 minutes)
    deadline = time.time() + 300
    while "code" not in _CodeHandler.code_holder and "error" not in _CodeHandler.code_holder:
        server.handle_request()
        if time.time() > deadline:
            server.server_close()
            return {"success": False, "error": "Tiempo de espera agotado (no se recibio la autorizacion)."}
    server.server_close()

    if _CodeHandler.code_holder.get("error"):
        return {"success": False, "error": f"Autorizacion denegada: {_CodeHandler.code_holder['error']}"}

    code = _CodeHandler.code_holder.get("code")
    if not code:
        return {"success": False, "error": "No se recibio el codigo de autorizacion."}

    # Exchange code for tokens
    token_body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            TOKEN_URI,
            data=token_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"Error al intercambiar el codigo: {detail}"}
    except Exception as exc:
        return {"success": False, "error": f"Error al intercambiar el codigo: {exc}"}

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return {
            "success": False,
            "error": "Google no devolvio refresh_token. Revoca el acceso en https://myaccount.google.com/permissions y reintenta.",
        }

    # Persist to .env and openclaw.json
    _update_env_refresh_token(ENV_PATH, refresh_token)
    cfg_path = _update_openclaw_config(refresh_token, client_id, client_secret, calendar_id)

    return {
        "success": True,
        "refresh_token": refresh_token,
        "env_path": str(ENV_PATH),
        "openclaw_config_path": cfg_path,
    }


def main():
    print("=" * 60)
    print(" JARVIS - Regenerar token de Google Calendar")
    print("=" * 60)
    result = run_oauth_flow()
    print()
    if result.get("success"):
        print("[OK] Nuevo refresh token guardado correctamente.")
        print(f"     .env:         {result.get('env_path')}")
        if result.get("openclaw_config_path"):
            print(f"     openclaw.json: {result.get('openclaw_config_path')}")
        print("\nReinicia JARVIS (o el gateway de OpenClaw) para aplicarlo.")
        sys.exit(0)
    else:
        print(f"[ERROR] {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
