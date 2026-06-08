import sys
import asyncio
import platform

# Force UTF-8 on stdout/stderr so print() never crashes on non-cp1252 chars
# (emojis, accents, arrows) when launched under the Windows console / Electron.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    if hasattr(platform, "_wmi_query"):
        def _jarvis_skip_wmi_query(*args, **kwargs):
            raise OSError("WMI query skipped by Jarvis to avoid Windows import hang.")

        platform._wmi_query = _jarvis_skip_wmi_query

import socketio
import uvicorn
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import threading
import sys
import os
import json
import time
import unicodedata
import re
import ctypes
import subprocess
from datetime import datetime
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# Ensure imports work both when launched from the project root and when Electron
# starts this file with backend/ as the current working directory.
for import_path in (PROJECT_ROOT, BACKEND_DIR):
    import_path_str = str(import_path)
    if import_path_str not in sys.path:
        sys.path.insert(0, import_path_str)

import backend.jarvis as jarvis
from automation_manager import AutomationManager
import automation_templates
from condition_evaluator import ConditionEvaluator
from authenticator import FaceAuthenticator
from kasa_agent import KasaAgent
from integrations.openclaw_bridge import OpenClawBridge
from integrations.openwa_bridge import OpenWABridge
from openclaw_allowlist_sync import sync_openclaw_whatsapp_allowlist
from openclaw_autopilot_manager import OpenClawAutopilotManager
from openclaw_contacts_importer import import_contacts_csv, import_contacts_vcf
from openclaw_event_normalizer import normalize_openclaw_inbound
from openclaw_events_manager import OpenClawEventsManager
from openclaw_messages_manager import OpenClawMessagesManager
from openclaw_targets_manager import OpenClawTargetsManager
from openclaw_voice_intent_router import route_openclaw_voice_intent
from pending_actions_manager import PendingActionsManager
from permissions_manager import PermissionsManager
from simulation_manager import simulation_manager
from simulators.kasa_simulator import kasa_simulator
from simulators.printer_simulator import printer_simulator
from workflow_manager import WorkflowManager
from music_manager import music_manager

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Music events are emitted through the shared MusicManager so both HTTP endpoints
# and the live voice tools (jarvis.py) reach the frontend via the same path.
music_manager.set_emitter(lambda event, data: asyncio.create_task(sio.emit(event, data)))
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app_socketio = socketio.ASGIApp(sio, app)

import signal

# --- SHUTDOWN HANDLER ---
CAMERA_QUERY_PHRASES = [
    "que ves",
    "que estas viendo",
    "que estoy enseñando",
    "que estoy ensenando",
    "que tengo en la mano",
    "que objeto",
    "describe la imagen",
    "describe lo que ves",
    "describe la camara",
    "identifica",
    "camara",
    "camera",
    "webcam",
    "what do you see",
    "what am i holding",
    "describe what you see",
]

CAMERA_FOLLOWUP_PHRASES = {"y ahora", "ahora", "ahora?", "y ahora?", "ahora mismo", "mira ahora"}

CAPABILITY_QUERY_PHRASES = [
    "que puedes hacer",
    "cuales son tus funcionalidades",
    "que funciones tienes",
    "en que me puedes ayudar",
    "dime tus capacidades",
    "que sabes hacer",
    "tus capacidades",
    "tus funcionalidades",
]

TEXT_CONFIRMATION_PHRASES = {
    "si",
    "sí",
    "ok",
    "vale",
    "dale",
    "adelante",
    "confirmo",
    "lo confirmo",
    "confirmalo",
    "confírmalo",
    "envialo",
    "envíalo",
    "mandalo",
    "mándalo",
}

TEXT_CANCELLATION_PHRASES = {
    "no",
    "cancela",
    "cancelalo",
    "cancélalo",
    "cancelar",
    "no lo envies",
    "no lo envíes",
    "no lo mandes",
    "olvidalo",
    "olvídalo",
}

def _normalize_text_for_match(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-zA-Z0-9+]+", " ", without_accents.lower())
    return re.sub(r"\s+", " ", cleaned).strip()

def _is_text_confirmation(text):
    normalized = _normalize_text_for_match(text)
    confirmations = {_normalize_text_for_match(item) for item in TEXT_CONFIRMATION_PHRASES}
    if normalized in confirmations:
        return True
    return normalized in {
        "si confirmo",
        "si lo confirmo",
        "si confirmalo",
        "si adelante",
        "si dale",
    }

def _is_text_cancellation(text):
    return _normalize_text_for_match(text) in {_normalize_text_for_match(item) for item in TEXT_CANCELLATION_PHRASES}

def _is_camera_question(text, loop=None):
    normalized = _normalize_text_for_match(text)
    if any(phrase in normalized for phrase in CAMERA_QUERY_PHRASES):
        return True

    if normalized in CAMERA_FOLLOWUP_PHRASES and loop:
        last_camera_question_at = getattr(loop, "_last_camera_question_at", None)
        if last_camera_question_at and (time.time() - last_camera_question_at) < 120:
            return True

    return False

def _is_capability_question(text):
    normalized = _normalize_text_for_match(text)
    return any(phrase in normalized for phrase in CAPABILITY_QUERY_PHRASES)

def _jarvis_capability_response():
    return (
        "Puedo ayudarte con varias areas: hablar contigo por voz, analizar lo que ve la camara, "
        "generar modelos CAD, iterarlos, preparar impresiones 3D, controlar impresoras y usar "
        "simulaciones para la defensa. Tambien puedo controlar dispositivos inteligentes Kasa, "
        "gestionar proyectos y conservar memoria de trabajo. Si estan configuradas tus cuentas o "
        "canales, tambien puedo ayudarte con mensajeria, respuestas automaticas autorizadas por "
        "grupo o contacto, correo, calendario, publicaciones en redes sociales, workflows personales "
        "y automatizaciones controladas. Para acciones sensibles, como enviar mensajes, publicar "
        "contenido, crear invitaciones o cancelar eventos, te pedire confirmacion antes."
    )

SIMULATION_ACTIVATE_PHRASES = [
    "activa el modo simulacion",
    "activar modo simulacion",
    "activa la simulacion",
    "activar simulacion",
    "modo demo",
    "activa modo demo",
    "activar modo demo",
]

SIMULATION_DEACTIVATE_PHRASES = [
    "desactiva el modo simulacion",
    "desactivar modo simulacion",
    "desactiva la simulacion",
    "desactivar simulacion",
    "desactiva modo demo",
    "desactivar modo demo",
]

def _simulation_command_intent(text):
    normalized = _normalize_text_for_match(text)
    if any(phrase in normalized for phrase in SIMULATION_DEACTIVATE_PHRASES):
        return "deactivate"
    if any(phrase in normalized for phrase in SIMULATION_ACTIVATE_PHRASES):
        return "activate"
    return None

async def _simulation_kasa_devices():
    if not simulation_manager.is_kasa_enabled():
        return []
    return await kasa_simulator.discover_devices()

async def _simulation_printers():
    if not simulation_manager.is_printer_enabled():
        return []
    return await printer_simulator.discover_printers()

async def emit_simulation_snapshot(message=None):
    state = simulation_manager.get_state()
    await sio.emit('simulation_status', state)
    await sio.emit('simulation_kasa_devices', await _simulation_kasa_devices())
    await sio.emit('simulation_printers', await _simulation_printers())
    if message:
        await sio.emit('simulation_event', {'message': message, 'timestamp': datetime.now().isoformat(timespec='seconds')})

async def set_simulation_mode(enabled):
    if enabled:
        simulation_manager.activate_all()
        kasa_simulator.reset()
        printer_simulator.reset()
        message = "Modo simulacion activado. A partir de ahora usare dispositivos Kasa e impresoras 3D simuladas."
    else:
        simulation_manager.deactivate_all()
        message = "Modo simulacion desactivado. Volvere a usar dispositivos reales si estan disponibles."

    await emit_simulation_snapshot(message)
    return message

def signal_handler(sig, frame):
    print(f"\n[SERVER] Caught signal {sig}. Exiting gracefully...")
    # Clean up audio loop
    if audio_loop:
        try:
            print("[SERVER] Stopping Audio Loop...")
            audio_loop.stop() 
        except:
            pass
    # Force kill
    print("[SERVER] Force exiting...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Global state
audio_loop = None
loop_task = None
authenticator = None
kasa_agent = KasaAgent()
openclaw_bridge = OpenClawBridge()
openwa_bridge = OpenWABridge()
openclaw_permissions = PermissionsManager()
pending_actions_manager = PendingActionsManager()
openclaw_autopilot_manager = OpenClawAutopilotManager()
openclaw_targets_manager = OpenClawTargetsManager()
openclaw_events_manager = OpenClawEventsManager()
openclaw_messages_manager = OpenClawMessagesManager()
automation_manager = AutomationManager()
workflow_manager = None
condition_evaluator = None
automation_scheduler_task = None
calendar_upcoming_notified = set()
printer_finished_events = set()
SETTINGS_FILE = BACKEND_DIR / "settings.json"
REFERENCE_IMAGE_FILE = BACKEND_DIR / "reference.jpg"

OPENCLAW_TOOL_PERMISSION_DEFAULTS = {
    "openclaw_check_status": False,
    "openclaw_directory_self": False,
    "openclaw_directory_peers": False,
    "openclaw_directory_groups": False,
    "openclaw_list_targets": False,
    "openclaw_resolve_target": False,
    "openclaw_execute_action": False,
    "openclaw_send_message": False,
    "openclaw_send_dry_run": False,
    "openclaw_read_conversation": False,
    "openclaw_list_events": False,
    "openclaw_mark_target_allowed": False,
    "openclaw_list_calendar_events": False,
    "openclaw_calendar_action": False,
    "openclaw_prepare_social_post": False,
    "openclaw_schedule_social_post": False,
    "openclaw_publish_social_post": False,
    "openclaw_run_workflow": False,
    "get_pending_actions": False,
    "confirm_pending_action": False,
    "cancel_pending_action": False,
    "create_openclaw_autopilot_rule": False,
    "list_openclaw_autopilot_rules": False,
    "enable_openclaw_autopilot_rule": False,
    "disable_openclaw_autopilot_rule": False,
    "delete_openclaw_autopilot_rule": False,
}

DEFAULT_SETTINGS = {
    "face_auth_enabled": False, # Default OFF as requested
    "tool_permissions": {
        "generate_cad": True,
        "run_web_agent": True,
        "inspect_camera": False,
        "create_directory": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "delete_path": True,
        "delete_project": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True,
        "discover_printers": True,
        "print_stl": True,
        "get_print_status": True,
        "pause_print": True,
        "resume_print": True,
        "cancel_print": True,
        "activate_simulation_mode": False,
        "deactivate_simulation_mode": False,
        "get_simulation_status": False,
        **OPENCLAW_TOOL_PERMISSION_DEFAULTS,
    },
    "printers": [], # List of {host, port, name, type}
    "kasa_devices": [], # List of {ip, alias, model}
    "camera_flipped": False # Invert cursor horizontal direction
}

SETTINGS = DEFAULT_SETTINGS.copy()

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                # Merge with defaults to ensure new keys exist
                # Deep merge for tool_permissions would be better but shallow merge of top keys + tool_permissions check is okay for now
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                         SETTINGS["tool_permissions"].update(v)
                    else:
                        SETTINGS[k] = v
            print(f"Loaded settings: {SETTINGS}")
        except Exception as e:
            print(f"Error loading settings: {e}")

def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(SETTINGS, f, indent=4)
        print("Settings saved.")
    except Exception as e:
        print(f"Error saving settings: {e}")

def _printer_type_value(printer_type):
    return printer_type.value if hasattr(printer_type, "value") else str(printer_type)

def _build_printer_settings_config(name, host, printer, camera_url=None, api_key=None):
    config = {
        "name": name,
        "host": host,
        "port": printer.port,
        "type": _printer_type_value(printer.printer_type),
    }

    if camera_url is not None:
        config["camera_url"] = camera_url
    elif getattr(printer, "camera_url", None) is not None:
        config["camera_url"] = printer.camera_url

    if api_key is not None:
        config["api_key"] = api_key

    return config

def _upsert_printer_setting(printer_config):
    printers = SETTINGS.setdefault("printers", [])
    for index, existing in enumerate(printers):
        if existing.get("host") == printer_config["host"]:
            printers[index] = {**existing, **printer_config}
            return "updated"

    printers.append(printer_config)
    return "added"

# Load on startup
load_settings()

authenticator = None
kasa_agent = KasaAgent(known_devices=SETTINGS.get("kasa_devices"))
# tool_permissions is now SETTINGS["tool_permissions"]

async def require_fresh_face_auth(reload_reference=False):
    """Reset auth state and start face authentication when the feature is enabled."""
    if not SETTINGS.get("face_auth_enabled", False) or not authenticator:
        return

    authenticator.reset_authentication(reload_reference=reload_reference)
    await sio.emit('auth_status', {'authenticated': False})
    asyncio.create_task(authenticator.start_authentication_loop())

async def _openwa_session_startup():
    """On server start: ensure the OpenWA session is active and webhook is registered."""
    await asyncio.sleep(2)  # brief pause so OpenWA has time to respond
    try:
        result = await openwa_bridge.ensure_session_active()
        action = result.get("action", "")
        print(f"[OPENWA] Session startup ({action}): {result.get('message', '')}")
    except Exception as exc:
        print(f"[OPENWA] Session startup error: {exc}")
        return

    # Register webhook so inbound messages reach JARVIS
    try:
        webhook_url = os.getenv(
            "JARVIS_OPENWA_WEBHOOK_URL",
            "http://127.0.0.1:8000/api/openwa/inbound",
        ).strip()
        wh_result = await openwa_bridge.ensure_webhook_configured(webhook_url)
        print(f"[OPENWA] Webhook ({wh_result.get('action', '')}): {wh_result.get('message', '')}")
    except Exception as exc:
        print(f"[OPENWA] Webhook setup error: {exc}")


async def _openwa_watchdog_loop():
    """Background task: monitor OpenWA session and restart it if disconnected."""
    interval = max(10, int(os.getenv("JARVIS_OPENWA_WATCHDOG_INTERVAL_SECONDS", "30") or 30))
    await asyncio.sleep(interval)  # initial delay before first check
    while True:
        try:
            result = await openwa_bridge.ensure_session_active()
            action = result.get("action", "")
            if action in ("started", "created_and_started"):
                print(f"[OPENWA] Watchdog recovered session: {result.get('message', '')}")
                await sio.emit("whatsapp_inbound_message", {
                    "message": None,
                    "unread_count": openclaw_messages_manager.get_unread_count(channel="whatsapp"),
                    "session_recovered": True,
                })
                # Re-register webhook after session restart
                webhook_url = os.getenv(
                    "JARVIS_OPENWA_WEBHOOK_URL",
                    "http://127.0.0.1:8000/api/openwa/inbound",
                ).strip()
                wh_result = await openwa_bridge.ensure_webhook_configured(webhook_url)
                if wh_result.get("action") == "created":
                    print(f"[OPENWA] Watchdog re-registered webhook: {wh_result.get('message', '')}")
        except Exception as exc:
            print(f"[OPENWA] Watchdog error: {exc}")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def startup_event():
    global automation_scheduler_task
    import sys
    print(f"[SERVER DEBUG] Startup Event Triggered")
    print(f"[SERVER DEBUG] Python Version: {sys.version}")
    try:
        loop = asyncio.get_running_loop()
        print(f"[SERVER DEBUG] Running Loop: {type(loop)}")
        policy = asyncio.get_event_loop_policy()
        print(f"[SERVER DEBUG] Current Policy: {type(policy)}")
    except Exception as e:
        print(f"[SERVER DEBUG] Error checking loop: {e}")

    print("[SERVER] Startup: Initializing Kasa Agent...")
    await kasa_agent.initialize()
    if automation_scheduler_task is None or automation_scheduler_task.done():
        automation_scheduler_task = asyncio.create_task(_automation_scheduler_loop())
        print("[SERVER] Automation scheduler started.")

    if openwa_bridge.is_enabled():
        asyncio.create_task(_openwa_session_startup())
        if _env_bool("JARVIS_OPENWA_WATCHDOG_ENABLED", True):
            asyncio.create_task(_openwa_watchdog_loop())
            print(f"[OPENWA] Session watchdog started (interval: {os.getenv('JARVIS_OPENWA_WATCHDOG_INTERVAL_SECONDS', '30')}s).")

    await dispatch_automation_event("system.startup", {"started_at": datetime.now().isoformat(timespec="seconds")})

class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _get_memory_status():
    try:
        if sys.platform == "win32":
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
                used = max(0, total - available)
                percent = round((used / total) * 100, 1) if total else None
                return {
                    "percent": percent,
                    "used_bytes": used,
                    "available_bytes": available,
                    "total_bytes": total,
                }

        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(pages * page_size)
        available = None
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as meminfo:
                for line in meminfo:
                    if line.startswith("MemAvailable:"):
                        available = int(line.split()[1]) * 1024
                        break
        except OSError:
            available = None

        used = max(0, total - available) if available is not None else None
        percent = round((used / total) * 100, 1) if used is not None and total else None
        return {
            "percent": percent,
            "used_bytes": used,
            "available_bytes": available,
            "total_bytes": total,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _get_cpu_percent():
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["wmic", "cpu", "get", "LoadPercentage", "/value"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            values = []
            for line in result.stdout.splitlines():
                if line.startswith("LoadPercentage="):
                    raw_value = line.split("=", 1)[1].strip()
                    if raw_value:
                        values.append(float(raw_value))
            if values:
                return round(sum(values) / len(values), 1)

        load_avg = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        return round(min(100, max(0, (load_avg / cpu_count) * 100)), 1)
    except Exception:
        return None


def _get_processor_label():
    return (
        platform.processor()
        or os.environ.get("PROCESSOR_IDENTIFIER")
        or platform.machine()
        or "No disponible"
    )


def _projects_root():
    root = PROJECT_ROOT / "projects"
    root.mkdir(exist_ok=True)
    return root.resolve()


def _safe_project_path(project_name: str):
    root = _projects_root()
    safe_name = "".join([c for c in str(project_name or "") if c.isalnum() or c in (" ", "-", "_")]).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Project name is required.")

    project_path = (root / safe_name).resolve()
    try:
        project_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project path.") from exc

    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return project_path


def _project_summary(project_path: Path):
    files_count = 0
    folders_count = 0
    latest_mtime = project_path.stat().st_mtime

    for root, dirs, files in os.walk(project_path):
        folders_count += len(dirs)
        files_count += len(files)
        for name in dirs + files:
            try:
                latest_mtime = max(latest_mtime, (Path(root) / name).stat().st_mtime)
            except OSError:
                pass

    return {
        "name": project_path.name,
        "path": str(project_path),
        "files_count": files_count,
        "folders_count": folders_count,
        "updated_at": datetime.fromtimestamp(latest_mtime).isoformat(),
    }


def _project_tree(project_path: Path, max_entries: int | None = None):
    root = project_path.resolve()
    count = 0

    def build(path: Path):
        nonlocal count
        if max_entries is not None and count >= max_entries:
            return None
        count += 1

        try:
            stat = path.stat()
        except OSError:
            return None

        item = {
            "name": path.name,
            "path": str(path.relative_to(root)) if path != root else ".",
            "type": "folder" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else None,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda entry: (entry.is_file(), entry.name.lower())):
                node = build(child)
                if node:
                    children.append(node)
            item["children"] = children

        return item

    return build(root)


@app.get("/status")
async def status():
    return {
        "status": "running",
        "service": "J.A.R.V.I.S Backend",
        "system": {
            "cpu": {
                "percent": _get_cpu_percent(),
                "processor": _get_processor_label(),
                "cores": os.cpu_count(),
            },
            "memory": _get_memory_status(),
        },
    }


@app.get("/api/projects")
async def api_projects():
    root = _projects_root()
    projects = [
        _project_summary(path)
        for path in sorted(root.iterdir(), key=lambda entry: entry.name.lower())
        if path.is_dir()
    ]
    current = audio_loop.project_manager.current_project if audio_loop and audio_loop.project_manager else None
    return {"success": True, "projects": projects, "current_project": current}


@app.get("/api/projects/{project_name}/tree")
async def api_project_tree(project_name: str):
    project_path = _safe_project_path(project_name)
    return {"success": True, "project": _project_summary(project_path), "tree": _project_tree(project_path)}


@app.post("/api/projects/{project_name}/activate")
async def api_project_activate(project_name: str):
    project_path = _safe_project_path(project_name)
    if not audio_loop or not getattr(audio_loop, "project_manager", None):
        raise HTTPException(status_code=503, detail="Project manager unavailable.")

    success, message = audio_loop.project_manager.switch_project(project_path.name)
    if not success:
        raise HTTPException(status_code=404, detail=message)

    current_project = audio_loop.project_manager.current_project
    await sio.emit('project_update', {'project': current_project})
    return {
        "success": True,
        "message": message,
        "current_project": current_project,
        "project": _project_summary(project_path),
    }

def _get_memory():
    """Return the live SemanticMemory instance, or raise 503 if unavailable."""
    memory = getattr(audio_loop, "memory", None) if audio_loop else None
    if not memory:
        raise HTTPException(status_code=503, detail="Semantic memory unavailable.")
    return memory


@app.get("/api/memory/stats")
async def api_memory_stats():
    return {"success": True, "stats": _get_memory().stats()}


@app.post("/api/memory/search")
async def api_memory_search(data: dict = Body(default={})):
    query = str(data.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Missing 'query'.")
    k = int(data.get("k") or 5)
    hits = await _get_memory().search(query, k=k)
    return {"success": True, "query": query, "results": hits}


@app.post("/api/memory/remember")
async def api_memory_remember(data: dict = Body(default={})):
    text = str(data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'.")
    memory = _get_memory()
    current = audio_loop.project_manager.current_project if audio_loop and audio_loop.project_manager else None
    result = await memory.add_text(text, source=str(data.get("source") or "nota"), project=current)
    return {"success": result.get("success", False), "result": result, "stats": memory.stats()}


@app.post("/api/memory/ingest")
async def api_memory_ingest(file: UploadFile = File(...)):
    import tempfile
    memory = _get_memory()
    content = await file.read()
    suffix = os.path.splitext(file.filename or "")[1] or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        current = audio_loop.project_manager.current_project if audio_loop and audio_loop.project_manager else None
        result = await memory.add_file(tmp_path, project=current)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    # Report the original filename rather than the temp path.
    result["file"] = file.filename
    if memory.records and result.get("success"):
        # Re-tag the freshly added chunks with the real filename for nicer recall.
        for rec in memory.records:
            if rec.get("metadata", {}).get("path") == tmp_path:
                rec["source"] = file.filename
        memory._save()
    return {"success": result.get("success", False), "result": result, "stats": memory.stats()}


@app.delete("/api/memory")
async def api_memory_clear():
    return {"success": True, "result": await _get_memory().clear()}


@app.post("/api/simulation/activate")
async def api_simulation_activate():
    message = await set_simulation_mode(True)
    return {"message": message, "state": simulation_manager.get_state()}

@app.post("/api/simulation/deactivate")
async def api_simulation_deactivate():
    message = await set_simulation_mode(False)
    return {"message": message, "state": simulation_manager.get_state()}

@app.post("/api/simulation/reset")
async def api_simulation_reset():
    kasa_simulator.reset()
    printer_simulator.reset()
    await emit_simulation_snapshot("Demo reiniciada")
    return {"message": "Demo reiniciada", "state": simulation_manager.get_state()}

@app.get("/api/simulation/status")
async def api_simulation_status():
    return {
        "state": simulation_manager.get_state(),
        "kasa_devices": await _simulation_kasa_devices(),
        "printers": await _simulation_printers(),
    }

@app.get("/api/simulation/kasa/devices")
async def api_simulation_kasa_devices():
    return await _simulation_kasa_devices()

def _require_kasa_simulation():
    if not simulation_manager.is_kasa_enabled():
        raise HTTPException(status_code=409, detail="Kasa simulation is not active.")

@app.post("/api/simulation/kasa/{target}/on")
async def api_simulation_kasa_on(target: str):
    _require_kasa_simulation()
    await kasa_simulator.turn_on(target)
    await emit_simulation_snapshot(f"{target} encendido")
    return kasa_simulator.get_state(target)

@app.post("/api/simulation/kasa/{target}/off")
async def api_simulation_kasa_off(target: str):
    _require_kasa_simulation()
    await kasa_simulator.turn_off(target)
    await emit_simulation_snapshot(f"{target} apagado")
    return kasa_simulator.get_state(target)

@app.post("/api/simulation/kasa/{target}/brightness")
async def api_simulation_kasa_brightness(target: str, data: dict = Body(default={})):
    _require_kasa_simulation()
    value = data.get("brightness", data.get("value"))
    if value is None:
        raise HTTPException(status_code=400, detail="brightness is required.")
    await kasa_simulator.set_brightness(target, value)
    await emit_simulation_snapshot(f"{target} brillo {value}%")
    return kasa_simulator.get_state(target)

@app.post("/api/simulation/kasa/{target}/color")
async def api_simulation_kasa_color(target: str, data: dict = Body(default={})):
    _require_kasa_simulation()
    value = data.get("color", data.get("value", data))
    await kasa_simulator.set_color(target, value)
    await emit_simulation_snapshot(f"{target} color actualizado")
    return kasa_simulator.get_state(target)

@app.get("/api/simulation/printers")
async def api_simulation_printers():
    return await _simulation_printers()

def _require_printer_simulation():
    if not simulation_manager.is_printer_enabled():
        raise HTTPException(status_code=409, detail="Printer simulation is not active.")

@app.get("/api/simulation/printers/{target}/status")
async def api_simulation_printer_status(target: str):
    _require_printer_simulation()
    status_data = await printer_simulator.get_print_status(target)
    if not status_data:
        raise HTTPException(status_code=404, detail="Demo printer not found.")
    return status_data

@app.post("/api/simulation/printers/{target}/start")
async def api_simulation_printer_start(target: str, data: dict = Body(default={})):
    _require_printer_simulation()
    status_data = await printer_simulator.start_demo_print(target, data.get("filename", "jarvis_demo_part.gcode"))
    if not status_data:
        raise HTTPException(status_code=404, detail="Demo printer not found.")
    await emit_simulation_snapshot(f"Impresion demo iniciada en {status_data['printer']}")
    return status_data

@app.post("/api/simulation/printers/{target}/pause")
async def api_simulation_printer_pause(target: str):
    _require_printer_simulation()
    status_data = await printer_simulator.pause_print(target)
    if not status_data:
        raise HTTPException(status_code=404, detail="Demo printer not found.")
    await emit_simulation_snapshot(f"Impresion pausada en {status_data['printer']}")
    return status_data

@app.post("/api/simulation/printers/{target}/resume")
async def api_simulation_printer_resume(target: str):
    _require_printer_simulation()
    status_data = await printer_simulator.resume_print(target)
    if not status_data:
        raise HTTPException(status_code=404, detail="Demo printer not found.")
    await emit_simulation_snapshot(f"Impresion reanudada en {status_data['printer']}")
    return status_data

@app.post("/api/simulation/printers/{target}/cancel")
async def api_simulation_printer_cancel(target: str):
    _require_printer_simulation()
    status_data = await printer_simulator.cancel_print(target)
    if not status_data:
        raise HTTPException(status_code=404, detail="Demo printer not found.")
    await emit_simulation_snapshot(f"Impresion cancelada en {status_data['printer']}")
    return status_data

def _openclaw_local_result(action_type, summary, success=True, raw=None, warnings=None):
    return {
        "success": bool(success),
        "service": "openclaw",
        "action_type": action_type,
        "summary": summary,
        "raw": raw,
        "external_id": None,
        "warnings": warnings or [],
    }

def _api_success(data=None, **extra):
    response = {"success": True, "data": data, "error": None}
    response.update(extra)
    return response

def _api_error(error, data=None, status_code=None, **extra):
    response = {"success": False, "data": data, "error": str(error or "Error desconocido.")}
    response.update(extra)
    if status_code:
        return JSONResponse(status_code=status_code, content=response)
    return response

def _api_from_openclaw_result(result, **extra):
    result = result or {}
    success = bool(result.get("success"))
    error = None if success else (result.get("error") or result.get("summary") or "OpenClaw no pudo completar la accion.")
    response = {"success": success, "data": result, "error": error}
    response.update(extra)
    return response

def _extract_openclaw_json(result):
    raw = (result or {}).get("raw") or {}
    if isinstance(raw, dict) and isinstance(raw.get("json"), dict):
        return raw.get("json")
    if isinstance(raw, dict) and isinstance(raw.get("json"), list):
        return {"items": raw.get("json")}
    return {}

def _extract_resolved_target(result, fallback=None):
    data = _extract_openclaw_json(result)
    for key in ("canonical_target", "canonicalTarget", "target", "id", "jid", "value", "address"):
        value = data.get(key)
        if value:
            return str(value)
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    for key in ("canonical", "id", "jid", "value"):
        value = target.get(key)
        if value:
            return str(value)
    return str(fallback or "")

def _target_payload_for_openclaw(payload):
    payload = dict(payload or {})
    target_id = payload.get("target_id")
    if target_id:
        stored = openclaw_targets_manager.get_target(target_id)
        if stored:
            payload.setdefault("channel", stored.get("channel"))
            payload.setdefault("kind", stored.get("kind"))
            payload.setdefault("display_target", stored.get("display_name"))
            payload.setdefault("target", stored.get("raw_target") or stored.get("display_name"))
            if stored.get("canonical_target"):
                payload.setdefault("canonical_target", stored.get("canonical_target"))
    return payload

def _save_inbound_message(incoming_message, raw_payload):
    incoming_message = incoming_message or {}
    canonical_target = incoming_message.get("target") or incoming_message.get("sender")
    return openclaw_messages_manager.add_message(
        channel=incoming_message.get("channel", "whatsapp"),
        kind=incoming_message.get("kind", "auto"),
        target=canonical_target,
        display_target=incoming_message.get("display_target"),
        sender=incoming_message.get("sender"),
        sender_name=incoming_message.get("sender_name"),
        message=incoming_message.get("message"),
        message_id=incoming_message.get("message_id"),
        conversation_id=incoming_message.get("conversation_id"),
        timestamp=incoming_message.get("timestamp"),
        read=False,
        raw=raw_payload,
    )

def _build_send_payload_from_request(data):
    payload = _target_payload_for_openclaw(data)
    target = payload.get("canonical_target") or payload.get("target")
    if not target:
        return None
    return {
        "channel": payload.get("channel", "whatsapp"),
        "kind": payload.get("kind", "user"),
        "target": target,
        "canonical_target": target,
        "display_target": payload.get("display_target") or payload.get("target") or target,
        "target_id": payload.get("target_id"),
        "message": payload.get("message") or payload.get("text"),
    }

def _allowed_whatsapp_target_for_payload(payload):
    payload = payload or {}
    if str(payload.get("channel", "whatsapp")).strip().lower() != "whatsapp":
        return True, None

    target = None
    if payload.get("target_id"):
        target = openclaw_targets_manager.get_target(payload.get("target_id"))
    canonical_target = payload.get("canonical_target") or payload.get("target")
    if not target and canonical_target:
        target = openclaw_targets_manager.find_by_canonical_target("whatsapp", canonical_target)
    if not target and payload.get("display_target"):
        target = openclaw_targets_manager.find_best_match("whatsapp", payload.get("display_target"))

    return bool(target and target.get("allowed")), target

def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}

def _whatsapp_provider():
    """Returns the configured WhatsApp provider ('openwa' or 'openclaw')."""
    return os.getenv("JARVIS_WHATSAPP_PROVIDER", "openclaw").strip().lower() or "openclaw"

def _is_whatsapp_channel_str(channel):
    return str(channel or "").strip().lower() == "whatsapp"

def _sync_openclaw_whatsapp_allowlist_best_effort(force=False):
    if os.getenv("PYTEST_CURRENT_TEST") and not force:
        return {"success": True, "skipped": True, "reason": "pytest"}
    if not force and not _env_bool("JARVIS_OPENCLAW_AUTO_SYNC_ALLOWLIST", True):
        return {"success": True, "skipped": True, "reason": "disabled"}
    try:
        return sync_openclaw_whatsapp_allowlist(openclaw_targets_manager)
    except Exception as exc:
        print(f"[OPENCLAW] WhatsApp allowlist sync failed: {exc}")
        return {"success": False, "error": str(exc)}

def _openclaw_human_summary(action_type, payload):
    payload = payload or {}
    if action_type in {"send_message", "send_whatsapp_message", "send_channel_message"}:
        return f"Enviar mensaje a {payload.get('display_target') or payload.get('target')} por {payload.get('channel')}: {payload.get('message')}"
    if action_type in {"send_email", "reply_email"}:
        return f"Enviar correo: {payload.get('subject') or payload.get('to') or 'sin asunto'}"
    if str(action_type).endswith("_calendar_event"):
        return f"Ejecutar accion de calendario: {action_type}"
    if action_type in {"schedule_social_post", "publish_social_post"}:
        return f"Ejecutar accion de redes sociales: {action_type}"
    if action_type == "run_workflow":
        return f"Ejecutar workflow: {payload.get('workflow_name')}"
    if action_type == "create_autopilot_rule":
        return f"Crear regla automatica para {payload.get('channel')} -> {payload.get('display_target') or payload.get('target')} en modo {payload.get('mode')}"
    if action_type == "openclaw_mark_target_allowed":
        return f"Marcar target OpenClaw como permitido: {payload.get('target_id')}"
    if str(action_type).endswith("_autopilot_rule"):
        return f"Modificar regla automatica: {action_type}"
    return f"Ejecutar accion externa: {action_type}"

def _public_openclaw_payload(payload):
    return {key: value for key, value in dict(payload or {}).items() if not str(key).startswith("_")}

async def _execute_openclaw_action(action_type, payload):
    payload = dict(payload or {})
    payload.setdefault("confirmed", True)
    automation_result = await _execute_automation_action(action_type, payload)
    if automation_result is not None:
        return automation_result
    if action_type == "check_status":
        result = await openclaw_bridge.check_status()
        openclaw_events_manager.add_event(
            "status",
            channel=payload.get("channel", "whatsapp"),
            message=result.get("summary"),
            success=result.get("success"),
            error=result.get("error") or (None if result.get("success") else result.get("summary")),
            raw=result,
        )
        return result
    _whatsapp_send_actions = {"send_message", "send_whatsapp_message", "send_channel_message", "autopilot_reply", "send_image", "send_whatsapp_image", "openclaw_send_image"}
    if action_type in _whatsapp_send_actions:
        allowed, target_record = _allowed_whatsapp_target_for_payload(payload)
        if not allowed:
            display = (
                (target_record or {}).get("display_name")
                or payload.get("display_target")
                or payload.get("target")
                or "ese destino"
            )
            return _openclaw_local_result(
                action_type,
                f"{display} no esta en la allowlist de WhatsApp de Jarvis.",
                success=False,
                warnings=["not_allowed"],
                raw={"target": target_record, "payload": _public_openclaw_payload(payload)},
            )
        _sync_openclaw_whatsapp_allowlist_best_effort()

        # Route WhatsApp sends to OpenWA when configured as provider
        channel = payload.get("channel", "whatsapp")
        if _is_whatsapp_channel_str(channel) and _whatsapp_provider() == "openwa":
            result = await openwa_bridge.execute_action(action_type, _public_openclaw_payload(payload))
            rule_id = payload.get("_autopilot_rule_id")
            if rule_id and result.get("success"):
                openclaw_autopilot_manager.register_reply(rule_id)
            real_target = payload.get("canonical_target") or payload.get("target")
            openclaw_events_manager.add_event(
                "outbound" if result.get("success") else "error",
                channel=channel,
                kind=payload.get("kind", "auto"),
                target=real_target,
                display_target=payload.get("display_target") or payload.get("target"),
                message=payload.get("message") or payload.get("text"),
                success=result.get("success"),
                error=result.get("error") or (None if result.get("success") else result.get("summary")),
                raw=result,
            )
            return result

    result = await openclaw_bridge.execute_action(action_type, _public_openclaw_payload(payload))
    rule_id = payload.get("_autopilot_rule_id")
    if rule_id and result.get("success"):
        openclaw_autopilot_manager.register_reply(rule_id)
    _log_actions = {"send_message", "send_whatsapp_message", "send_channel_message", "autopilot_reply", "send_image", "send_whatsapp_image", "openclaw_send_image"}
    if action_type in _log_actions:
        real_target = payload.get("canonical_target") or payload.get("target")
        msg_preview = payload.get("message") or payload.get("text") or payload.get("caption") or ("[imagen]" if "image" in action_type else "")
        openclaw_events_manager.add_event(
            "outbound" if result.get("success") else "error",
            channel=payload.get("channel", "whatsapp"),
            kind=payload.get("kind", "auto"),
            target=real_target,
            display_target=payload.get("display_target") or payload.get("target"),
            message=msg_preview,
            success=result.get("success"),
            error=result.get("error") or (None if result.get("success") else result.get("summary")),
            raw=result,
        )
    return result

async def _execute_or_queue_openclaw_action(action_type, payload, human_summary=None):
    action_type = str(action_type or "").strip()
    if not action_type:
        return _openclaw_local_result(
            "unknown",
            "Falta action_type para ejecutar la accion externa.",
            success=False,
            warnings=["invalid_request"],
        )

    if isinstance(payload, dict) and payload.get("dry_run") is True:
        return await _execute_openclaw_action(action_type, payload)

    classification = openclaw_permissions.classify(action_type)
    if classification == "forbidden":
        return _openclaw_local_result(
            action_type,
            f"Accion bloqueada por seguridad: {openclaw_permissions.explain(action_type)}",
            success=False,
            warnings=["forbidden"],
        )

    # Per-automation safety policy can force confirmation even on safe actions.
    # It can NEVER downgrade a confirmation_required/forbidden action (security
    # stays authoritative); "never" simply means "no extra friction".
    if classification == "safe" and _automation_safety_policy(payload) == "always":
        classification = "confirmation_required"

    if classification == "confirmation_required":
        pending = pending_actions_manager.create_pending_action(
            action_type,
            payload or {},
            human_summary or _openclaw_human_summary(action_type, payload or {}),
        )
        workflow_context = (payload or {}).get("_workflow_context") if isinstance(payload, dict) else {}
        if not isinstance(workflow_context, dict) or workflow_context.get("event_type") != "pending_action.created":
            await dispatch_automation_event(
                "pending_action.created",
                {
                    "pending_action": pending,
                    "action_type": action_type,
                    "payload": _public_openclaw_payload(payload or {}),
                    "human_summary": pending.get("human_summary"),
                },
            )
        return _openclaw_local_result(
            action_type,
            f"Accion pendiente de confirmacion. ID: {pending['id']}",
            success=False,
            raw=pending,
            warnings=["confirmation_required"],
        )

    return await _execute_openclaw_action(action_type, payload)


def _get_workflow_manager():
    global workflow_manager
    if workflow_manager is None:
        workflow_manager = WorkflowManager(_execute_or_queue_openclaw_action)
    return workflow_manager


def _get_project_manager():
    return getattr(audio_loop, "project_manager", None) if audio_loop else None


def _extract_calendar_events(result):
    """Best-effort extraction of a calendar event list from an OpenClaw result."""
    if not isinstance(result, dict):
        return []
    for key in ("events", "items", "results"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    raw = result.get("raw") if isinstance(result.get("raw"), (dict, list)) else result.get("data")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("events", "items", "results"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    return []


async def _automation_provider_is_provider_connected(name):
    name = str(name or "").strip().lower()
    try:
        if name in {"openwa", "whatsapp"} and _whatsapp_provider() == "openwa":
            status = await openwa_bridge.check_status()
        else:
            status = await openclaw_bridge.check_status()
        return bool(status.get("success"))
    except Exception:
        return False


def _automation_provider_is_sender_allowed(sender):
    sender = str(sender or "").strip()
    if not sender:
        return False
    try:
        match = openclaw_targets_manager.find_best_match("whatsapp", sender)
        return bool(match and match.get("allowed"))
    except Exception:
        return False


async def _automation_provider_has_calendar_events(condition=None):
    try:
        result = await openclaw_bridge.execute_action("list_calendar_events", {"max_results": 5})
        return len(_extract_calendar_events(result)) > 0
    except Exception:
        return False


def _automation_provider_is_project_active(name=None):
    pm = _get_project_manager()
    if not pm:
        return False
    current = getattr(pm, "current_project", None)
    if name:
        return str(current) == str(name)
    return bool(current and str(current) != "temp")


def _get_condition_evaluator():
    global condition_evaluator
    if condition_evaluator is None:
        condition_evaluator = ConditionEvaluator(
            providers={
                "is_provider_connected": _automation_provider_is_provider_connected,
                "is_sender_allowed": _automation_provider_is_sender_allowed,
                "has_calendar_events": _automation_provider_has_calendar_events,
                "is_project_active": _automation_provider_is_project_active,
                "is_simulation_enabled": simulation_manager.is_simulation_enabled,
            }
        )
    return condition_evaluator


def _automation_safety_policy(payload):
    """Reads safety.requires_confirmation from the workflow context, if present."""
    if not isinstance(payload, dict):
        return "auto"
    context = payload.get("_workflow_context")
    automation = context.get("automation") if isinstance(context, dict) else None
    safety = automation.get("safety") if isinstance(automation, dict) else None
    if isinstance(safety, dict):
        return str(safety.get("requires_confirmation") or "auto").strip().lower()
    return "auto"


async def _execute_automation_action(action_type, payload):
    """Handlers for the automation-level action vocabulary. Returns None when the
    action is not an automation action (so the caller falls through to the regular
    OpenClaw/OpenWA executor)."""
    public_payload = _public_openclaw_payload(payload or {})

    if action_type == "notify":
        title = str(public_payload.get("title") or "Notificacion de JARVIS").strip()
        message = str(
            public_payload.get("message")
            or public_payload.get("text")
            or public_payload.get("title")
            or "Notificacion de automatizacion."
        ).strip()
        priority = str(public_payload.get("priority") or "normal").strip()
        try:
            await sio.emit("automation_notification", {"title": title, "message": message, "priority": priority})
        except Exception as exc:
            print(f"[AUTOMATION] notify emit failed: {exc}")
        return _openclaw_local_result("notify", f"{title}: {message}", raw={"priority": priority})

    if action_type == "play_music":
        query = str(public_payload.get("query") or public_payload.get("playlist") or "").strip()
        mode = str(public_payload.get("mode") or ("random" if not query else "search")).strip()
        result = await music_manager.play(query, mode)
        success = bool(result.get("success"))
        title = result.get("title") or query or "musica"
        summary = f"Reproduciendo: {title}." if success else (result.get("error") or "No pude reproducir musica.")
        return _openclaw_local_result("play_music", summary, success=success, raw=result)

    if action_type == "control_music":
        command = str(public_payload.get("command") or "").strip()
        volume = public_payload.get("volume")
        result = music_manager.command(command, volume=volume)
        success = bool(result.get("success"))
        summary = f"Comando de musica: {command}." if success else (result.get("error") or "Comando de musica no valido.")
        return _openclaw_local_result("control_music", summary, success=success, raw=result)

    if action_type == "open_project":
        name = str(public_payload.get("project") or public_payload.get("name") or "").strip()
        pm = _get_project_manager()
        if not pm:
            return _openclaw_local_result("open_project", "No hay gestor de proyectos disponible.", success=False, warnings=["unavailable"])
        if not name:
            current = getattr(pm, "current_project", None)
            return _openclaw_local_result("open_project", f"Proyecto activo actual: {current or 'temp'}.", raw={"current_project": current})
        ok, message = pm.switch_project(name)
        return _openclaw_local_result("open_project", message, success=bool(ok), raw={"current_project": getattr(pm, "current_project", None)})

    if action_type == "activate_simulation":
        state = simulation_manager.activate_all()
        return _openclaw_local_result("activate_simulation", "Simulacion activada (modo demo sin hardware).", raw=state)

    if action_type == "check_integrations":
        results = {}
        try:
            results["openclaw"] = await openclaw_bridge.check_status()
        except Exception as exc:
            results["openclaw"] = {"success": False, "error": str(exc)}
        try:
            results["openwa"] = await openwa_bridge.check_status()
        except Exception as exc:
            results["openwa"] = {"success": False, "error": str(exc)}
        ok = bool(results.get("openclaw", {}).get("success") or results.get("openwa", {}).get("success"))
        connected = [name for name, value in results.items() if isinstance(value, dict) and value.get("success")]
        summary = f"Integraciones conectadas: {', '.join(connected) if connected else 'ninguna'}."
        return _openclaw_local_result("check_integrations", summary, success=ok, raw=results)

    if action_type == "list_calendar_today":
        try:
            result = await openclaw_bridge.execute_action("list_calendar_events", {"max_results": int(public_payload.get("max_results") or 10)})
        except Exception as exc:
            return _openclaw_local_result("list_calendar_today", f"No pude consultar el calendario: {exc}", success=False, warnings=["calendar_error"])
        events = _extract_calendar_events(result)
        return _openclaw_local_result("list_calendar_today", f"Eventos en el calendario: {len(events)}.", raw={"events": events})

    if action_type == "list_whatsapp_unread":
        unread = openclaw_messages_manager.get_unread_count(channel="whatsapp")
        messages = openclaw_messages_manager.list_new_messages(channel="whatsapp", limit=int(public_payload.get("limit") or 20))
        return _openclaw_local_result("list_whatsapp_unread", f"Mensajes de WhatsApp sin leer: {unread}.", raw={"unread": unread, "messages": messages})

    if action_type == "summarize_day":
        unread = openclaw_messages_manager.get_unread_count(channel="whatsapp")
        pending = len(pending_actions_manager.get_pending_actions())
        try:
            calendar_result = await openclaw_bridge.execute_action("list_calendar_events", {"max_results": 10})
            events = _extract_calendar_events(calendar_result)
        except Exception:
            events = []
        summary = (
            f"Resumen del dia: {len(events)} evento(s) en el calendario, "
            f"{unread} mensaje(s) de WhatsApp sin leer y {pending} accion(es) pendiente(s)."
        )
        try:
            await sio.emit("automation_notification", {"title": "Resumen del dia", "message": summary, "priority": "normal"})
        except Exception:
            pass
        return _openclaw_local_result("summarize_day", summary, raw={"events": events, "unread": unread, "pending": pending})

    if action_type == "create_pending_action":
        target_action = str(public_payload.get("target_action_type") or public_payload.get("action_type") or "").strip()
        if not target_action:
            return _openclaw_local_result("create_pending_action", "Falta target_action_type para crear la accion pendiente.", success=False, warnings=["invalid_request"])
        target_payload = public_payload.get("target_payload") if isinstance(public_payload.get("target_payload"), dict) else {}
        human_summary = str(public_payload.get("human_summary") or _openclaw_human_summary(target_action, target_payload)).strip()
        pending = pending_actions_manager.create_pending_action(target_action, target_payload, human_summary)
        await dispatch_automation_event(
            "pending_action.created",
            {"pending_action": pending, "action_type": target_action, "payload": target_payload, "human_summary": human_summary},
        )
        return _openclaw_local_result("create_pending_action", f"Accion pendiente creada: {human_summary}", raw=pending, warnings=["confirmation_required"])

    if action_type == "prepare_whatsapp_reply":
        target = public_payload.get("target") or public_payload.get("display_target")
        message = str(public_payload.get("message") or public_payload.get("reply") or "").strip()
        send_payload = {
            "channel": public_payload.get("channel", "whatsapp"),
            "target": target,
            "display_target": public_payload.get("display_target") or target,
            "message": message,
        }
        human_summary = str(public_payload.get("human_summary") or _openclaw_human_summary("send_message", send_payload)).strip()
        pending = pending_actions_manager.create_pending_action("send_message", send_payload, human_summary)
        await dispatch_automation_event(
            "pending_action.created",
            {"pending_action": pending, "action_type": "send_message", "payload": send_payload, "human_summary": human_summary},
        )
        return _openclaw_local_result("prepare_whatsapp_reply", f"Respuesta de WhatsApp preparada y pendiente de confirmacion. ID: {pending['id']}", raw=pending, warnings=["confirmation_required"])

    return None


def _automation_event_message(event_type, automation, result, source):
    name = (automation or {}).get("name") or (result or {}).get("automation", {}).get("name") or "Automatizacion"
    status_text = (result or {}).get("status") or (result or {}).get("result", {}).get("status") or "sin_estado"
    return f"{event_type}: {name} ({source}): {status_text}"


def _record_automation_event(event_type, automation, result=None, source="scheduler", error=None):
    try:
        return openclaw_events_manager.add_event(
            event_type,
            channel="automation",
            kind=source,
            display_target=(automation or {}).get("name"),
            message=str(error) if error else _automation_event_message(event_type, automation, result, source),
            success=not bool(error) and event_type not in {"automation.failed", "automation.waiting_for_confirmation"},
            error=str(error) if error else None,
            raw={"event_type": event_type, "automation": automation or {}, "result": result or {}, "source": source},
        )
    except Exception as exc:
        print(f"[AUTOMATION] Failed to record event: {exc}")
        return None


async def _record_and_dispatch_automation_event(event_type, automation, result=None, source="scheduler", error=None):
    event = _record_automation_event(event_type, automation, result=result, source=source, error=error)
    if str(source or "").startswith("event:automation."):
        return event
    await dispatch_automation_event(
        event_type,
        {
            "automation": automation or {},
            "result": result or {},
            "source": source,
            "event": event,
            "error": str(error) if error else None,
        },
    )
    return event


async def _run_automation_by_id(automation_id, source="manual", event_type=None, event_payload=None):
    automation, claim_state = automation_manager.claim_automation_for_run(automation_id)
    if claim_state == "not_found":
        return _api_error("No encuentro esa automatizacion.", status_code=404)
    if claim_state == "already_running":
        result = {
            "success": False,
            "status": "skipped_already_running",
            "automation": automation,
            "summary": "La automatizacion ya esta en ejecucion.",
        }
        await _record_and_dispatch_automation_event(
            "automation.skipped_already_running",
            automation,
            result=result,
            source=source,
        )
        return _api_success(result)

    try:
        evaluation = await _get_condition_evaluator().evaluate(
            automation.get("conditions") or [],
            event_payload or {},
        )
        if not evaluation.get("passed"):
            skip_result = {
                "success": True,
                "status": "skipped_conditions",
                "automation": automation,
                "summary": evaluation.get("summary"),
                "conditions": evaluation.get("results"),
            }
            # Advance next_run_at so scheduled automations don't loop every tick.
            updated = automation_manager.mark_run(
                automation_id,
                result={"success": True, "status": "skipped_conditions", "summary": evaluation.get("summary")},
            )
            skip_result["automation"] = updated or automation
            await _record_and_dispatch_automation_event(
                "automation.skipped_conditions",
                updated or automation,
                result=skip_result,
                source=source,
            )
            return _api_success(skip_result)

        await _record_and_dispatch_automation_event(
            "automation.started",
            automation,
            result={"success": True, "status": "started"},
            source=source,
        )
        workflow_result = await _get_workflow_manager().execute_workflow(
            automation.get("workflow") or {},
            automation={
                **automation,
                "source": source,
                "event_type": event_type,
                "event_payload": event_payload,
            },
        )
        updated = automation_manager.mark_run(automation_id, result=workflow_result)
        status = workflow_result.get("status")
        lifecycle_event = "automation.completed"
        if status == "waiting_for_confirmation":
            lifecycle_event = "automation.waiting_for_confirmation"
        elif not workflow_result.get("success"):
            lifecycle_event = "automation.failed"
        api_result = {
            "success": bool(workflow_result.get("success")),
            "status": status,
            "automation": updated,
            "result": workflow_result,
        }
        await _record_and_dispatch_automation_event(
            lifecycle_event,
            updated or automation,
            result=api_result,
            source=source,
        )
        return _api_success(api_result)
    except Exception as exc:
        error_result = {"success": False, "status": "exception", "summary": str(exc), "error": str(exc)}
        updated = automation_manager.mark_run(automation_id, result=error_result)
        await _record_and_dispatch_automation_event(
            "automation.failed",
            updated or automation,
            result=error_result,
            source=source,
            error=exc,
        )
        return _api_error(str(exc), data={"automation": automation})
    finally:
        automation_manager.release_automation_run(automation_id)


async def dispatch_automation_event(event_type, payload=None):
    event_type = str(event_type or "").strip()
    if not event_type:
        return {"event_type": "", "matched": 0, "results": [], "error": "event_type is required"}

    payload = payload or {}
    matches = automation_manager.automations_for_event(event_type, payload)
    results = []
    for automation in matches:
        response = await _run_automation_by_id(
            automation.get("id"),
            source=f"event:{event_type}",
            event_type=event_type,
            event_payload=payload,
        )
        results.append(
            {
                "automation_id": automation.get("id"),
                "name": automation.get("name"),
                "response": response,
            }
        )
    return {"event_type": event_type, "matched": len(matches), "results": results}


def _parse_calendar_start(event):
    from datetime import timezone

    start = event.get("start") or event.get("start_time") or event.get("when")
    if isinstance(start, dict):
        start = start.get("dateTime") or start.get("date")
    if not start:
        return None
    text = str(start).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _check_calendar_upcoming():
    """Polls the calendar and fires calendar.event_upcoming for events starting
    soon. Only runs when at least one automation listens for that event."""
    from datetime import timezone

    if not automation_manager.automations_for_event("calendar.event_upcoming", {}):
        return
    try:
        window_minutes = int(os.getenv("JARVIS_CALENDAR_UPCOMING_WINDOW_MIN", "30") or 30)
    except Exception:
        window_minutes = 30
    try:
        result = await openclaw_bridge.execute_action("list_calendar_events", {"max_results": 10})
    except Exception:
        return
    now = datetime.now(timezone.utc)
    for event in _extract_calendar_events(result):
        if not isinstance(event, dict):
            continue
        start = _parse_calendar_start(event)
        if not start:
            continue
        minutes_until = (start - now).total_seconds() / 60.0
        if not 0 <= minutes_until <= window_minutes:
            continue
        event_id = str(event.get("id") or event.get("event_id") or event.get("summary") or start.isoformat())
        if event_id in calendar_upcoming_notified:
            continue
        calendar_upcoming_notified.add(event_id)
        await dispatch_automation_event(
            "calendar.event_upcoming",
            {"event": event, "minutes_until": round(minutes_until), "start": start.isoformat()},
        )


async def _automation_scheduler_loop():
    await asyncio.sleep(5)
    while True:
        try:
            await dispatch_automation_event("scheduler.tick", {"checked_at": datetime.now().isoformat(timespec="seconds")})
            for automation in automation_manager.due_automations():
                print(f"[AUTOMATION] Running due automation: {automation.get('name')}")
                await _run_automation_by_id(automation.get("id"), source="scheduler")
            await _check_calendar_upcoming()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[AUTOMATION] Scheduler error: {exc}")
        await asyncio.sleep(30)


async def _execute_confirmed_pending_action(action):
    if not action:
        return _openclaw_local_result(
            "confirm_pending_action",
            "No encuentro esa accion pendiente.",
            success=False,
            warnings=["not_found"],
        )

    action_type = action.get("action_type")
    payload = action.get("payload") or {}

    if action_type == "create_autopilot_rule":
        rule = openclaw_autopilot_manager.create_rule(
            payload.get("channel"),
            payload.get("target"),
            payload.get("mode"),
            payload.get("trigger"),
            payload.get("behavior"),
            kind=payload.get("kind", "auto"),
            display_target=payload.get("display_target"),
            target_id=payload.get("target_id"),
        )
        return _openclaw_local_result(action_type, "Regla de respuesta automatica creada.", raw=rule)

    if action_type == "openclaw_mark_target_allowed":
        target = openclaw_targets_manager.mark_allowed(payload.get("target_id"), payload.get("allowed", True))
        if not target:
            return _openclaw_local_result(action_type, "No encuentro ese target.", success=False, warnings=["not_found"])
        return _openclaw_local_result(action_type, "Target marcado como permitido manualmente.", raw=target)

    if action_type == "enable_autopilot_rule":
        rule = openclaw_autopilot_manager.enable_rule(payload.get("rule_id"))
        return _autopilot_mutation_result(action_type, rule, "activada")

    if action_type == "disable_autopilot_rule":
        rule = openclaw_autopilot_manager.disable_rule(payload.get("rule_id"))
        return _autopilot_mutation_result(action_type, rule, "desactivada")

    if action_type == "delete_autopilot_rule":
        rule = openclaw_autopilot_manager.delete_rule(payload.get("rule_id"))
        return _autopilot_mutation_result(action_type, rule, "eliminada")

    return await _execute_openclaw_action(action_type, payload)

async def _claim_and_execute_pending_action(action_id):
    action, claim_state = pending_actions_manager.claim_action_for_execution(action_id)
    if not action:
        return _openclaw_local_result(
            "confirm_pending_action",
            "No encuentro esa accion pendiente.",
            success=False,
            warnings=["not_found"],
        )

    if claim_state == "executed":
        return action.get("result") or _openclaw_local_result(
            "confirm_pending_action",
            "La accion pendiente ya estaba ejecutada.",
            raw=action,
            warnings=["already_executed"],
        )

    if claim_state == "executing":
        return _openclaw_local_result(
            "confirm_pending_action",
            "La accion pendiente ya se esta ejecutando.",
            raw=action,
            warnings=["already_executing"],
        )

    if claim_state == "cancelled":
        return _openclaw_local_result(
            "confirm_pending_action",
            "La accion pendiente ya estaba cancelada.",
            success=False,
            raw=action,
            warnings=["already_cancelled"],
        )

    try:
        result = await _execute_confirmed_pending_action(action)
    except Exception as exc:
        result = _openclaw_local_result(
            action.get("action_type") or "confirm_pending_action",
            f"No he podido ejecutar la accion pendiente: {str(exc)[:200]}",
            success=False,
            raw=action,
            warnings=["handler_error"],
        )
    pending_actions_manager.mark_executed(action_id, result)
    return result

def _message_from_pending_result(result, success_fallback="Accion procesada correctamente."):
    result = result or {}
    if result.get("success"):
        return result.get("summary") or success_fallback
    return result.get("error") or result.get("summary") or "No he podido ejecutar la accion."

async def _notify_pending_action_resolution(result, source="panel", room=None):
    message = _message_from_pending_result(result)
    await sio.emit('openclaw_pending_action', None, room=room)

    session = getattr(audio_loop, "session", None) if audio_loop else None
    if session:
        try:
            await session.send(
                input=(
                    "El usuario ha confirmado o resuelto una accion pendiente "
                    f"desde {source}. La accion ya esta procesada. "
                    f"Resultado: {message}. "
                    "Actualiza solo tu contexto interno. No respondas ni repitas este resultado."
                ),
                end_of_turn=False,
            )
        except Exception as exc:
            print(f"[SERVER] Could not notify live Jarvis session about pending action resolution: {exc}")

    await sio.emit('transcription', {'sender': 'JARVIS', 'text': message, 'append': False}, room=room)
    if audio_loop and getattr(audio_loop, "project_manager", None):
        audio_loop.project_manager.log_chat("JARVIS", message)

def _autopilot_mutation_result(action_type, rule, label):
    if not rule:
        return _openclaw_local_result(action_type, "No encuentro esa regla.", success=False, warnings=["not_found"])
    return _openclaw_local_result(action_type, f"Regla {label}.", raw=rule)

def _create_openclaw_autopilot_rule_from_payload(data):
    if not _env_bool("JARVIS_OPENCLAW_AUTOPILOT_ENABLED", True):
        return _openclaw_local_result(
            "create_autopilot_rule",
            "Las respuestas automaticas externas no estan habilitadas.",
            success=False,
            warnings=["autopilot_disabled"],
        )

    mode = data.get("mode", "ask_before_send")
    payload = {
        "channel": data.get("channel"),
        "kind": data.get("kind", "auto"),
        "target": data.get("target"),
        "display_target": data.get("display_target"),
        "target_id": data.get("target_id"),
        "mode": mode,
        "trigger": data.get("trigger") or {},
        "behavior": data.get("behavior") or {},
    }

    if mode == "auto_send_limited":
        pending = pending_actions_manager.create_pending_action(
            "create_autopilot_rule",
            payload,
            _openclaw_human_summary("create_autopilot_rule", payload),
        )
        return _openclaw_local_result(
            "create_autopilot_rule",
            f"Regla pendiente de confirmacion antes de activar autoenvio. ID: {pending['id']}",
            success=False,
            raw=pending,
            warnings=["confirmation_required"],
        )

    rule = openclaw_autopilot_manager.create_rule(
        payload["channel"],
        payload["target"],
        payload["mode"],
        payload["trigger"],
        payload["behavior"],
        kind=payload.get("kind", "auto"),
        display_target=payload.get("display_target"),
        target_id=payload.get("target_id"),
    )
    return _openclaw_local_result("create_autopilot_rule", "Regla de respuesta automatica creada.", raw=rule)

def _build_autopilot_reply(rule, incoming_message):
    behavior = rule.get("behavior", {}) if isinstance(rule, dict) else {}
    instruction = str(behavior.get("instruction") or "").strip()
    message = str((incoming_message or {}).get("message") or "").lower()

    if "manana a las 12" in _normalize_text_for_match(instruction):
        return "La reunion sera manana a las 12."
    if "ocupado" in _normalize_text_for_match(instruction):
        return "Ahora mismo estoy ocupado. Te respondo en cuanto pueda."
    if "reunion" in _normalize_text_for_match(message):
        return "Gracias por preguntar. La reunion sigue segun lo previsto; si hay cambios, aviso."
    return "Gracias por el mensaje. Lo reviso y respondo en cuanto pueda."

def _create_pending_autopilot_reply(rule, incoming_message, reply_text, draft_only=False):
    action_type = "draft_content" if draft_only else "send_message"
    payload = {
        "channel": incoming_message.get("channel"),
        "kind": incoming_message.get("kind") or rule.get("kind", "auto"),
        "target": incoming_message.get("target"),
        "canonical_target": incoming_message.get("target"),
        "display_target": incoming_message.get("display_target") or rule.get("display_target") or incoming_message.get("target"),
        "target_id": rule.get("target_id"),
        "message": reply_text,
        "conversation_id": incoming_message.get("conversation_id"),
        "_autopilot_rule_id": rule.get("id"),
    }
    pending = pending_actions_manager.create_pending_action(
        action_type,
        payload,
        f"Respuesta propuesta para {payload.get('display_target')}: {reply_text}",
    )
    return pending

@app.get("/api/openclaw/status")
async def api_openclaw_status():
    return _api_from_openclaw_result(await openclaw_bridge.check_status())

@app.get("/api/openclaw/directory/self")
async def api_openclaw_directory_self(channel: str = "whatsapp", account: str = None):
    result = await openclaw_bridge.directory_self(channel=channel, account=account)
    return _api_from_openclaw_result(result)

@app.get("/api/openclaw/directory/peers")
async def api_openclaw_directory_peers(channel: str = "whatsapp", query: str = None, limit: int = 50, account: str = None):
    result = await openclaw_bridge.directory_peers(channel=channel, query=query, limit=limit, account=account)
    return _api_from_openclaw_result(result)

@app.get("/api/openclaw/directory/groups")
async def api_openclaw_directory_groups(channel: str = "whatsapp", query: str = None, limit: int = 50, account: str = None):
    result = await openclaw_bridge.directory_groups(channel=channel, query=query, limit=limit, account=account)
    return _api_from_openclaw_result(result)

@app.get("/api/openclaw/targets")
async def api_openclaw_targets():
    return _api_success(openclaw_targets_manager.list_targets())

@app.get("/api/openclaw/targets/allowed")
async def api_openclaw_targets_allowed(channel: str = "whatsapp", kind: str = None):
    return _api_success(openclaw_targets_manager.list_allowed_targets(channel=channel, kind=kind))

@app.post("/api/openclaw/whatsapp/sync-allowlist")
async def api_openclaw_whatsapp_sync_allowlist(data: dict = Body(default={})):
    result = sync_openclaw_whatsapp_allowlist(
        openclaw_targets_manager,
        dry_run=bool(data.get("dry_run", False)),
    )
    if not result.get("success"):
        return _api_error(
            result.get("error") or result.get("reason") or "No se pudo sincronizar la allowlist de WhatsApp con OpenClaw.",
            warnings=[result.get("reason") or "sync_failed"],
            data=result,
        )
    return _api_success(result)

@app.post("/api/openclaw/targets")
async def api_openclaw_targets_create(data: dict = Body(default={})):
    target = openclaw_targets_manager.add_target(
        data.get("channel", "whatsapp"),
        data.get("kind", "auto"),
        data.get("display_name") or data.get("display_target") or data.get("raw_target") or data.get("canonical_target"),
        data.get("raw_target") or data.get("target") or data.get("phone") or data.get("canonical_target"),
        canonical_target=data.get("canonical_target") or data.get("phone"),
        resolved=bool(data.get("resolved", False)),
        allowed=bool(data.get("allowed", False)),
        raw_openclaw=data.get("raw_openclaw"),
        aliases=data.get("aliases") or [],
        favorite=bool(data.get("favorite", False)),
        relationship=data.get("relationship", ""),
        source=data.get("source", "dashboard"),
    )
    sync_result = _sync_openclaw_whatsapp_allowlist_best_effort()
    return _api_success({"target": target, "sync": sync_result})

@app.get("/api/openclaw/targets/resolve-alias")
async def api_openclaw_target_resolve_alias(alias: str, channel: str = "whatsapp", kind: str = None):
    target = openclaw_targets_manager.find_best_match(channel, alias, kind=kind)
    if not target:
        return _api_error("No encuentro ese alias en la agenda local.", warnings=["not_found"])
    return _api_success(target)

@app.get("/api/openclaw/targets/{target_id}")
async def api_openclaw_target_get(target_id: str):
    target = openclaw_targets_manager.get_target(target_id)
    if not target:
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    return _api_success(target)

@app.post("/api/openclaw/targets/{target_id}/resolve")
async def api_openclaw_target_resolve(target_id: str, data: dict = Body(default={})):
    target = openclaw_targets_manager.get_target(target_id)
    if not target:
        return _api_error("No encuentro ese target.", warnings=["not_found"])

    channel = data.get("channel") or target.get("channel") or "whatsapp"
    kind = data.get("kind") or target.get("kind") or "auto"
    raw_target = data.get("target") or target.get("raw_target") or target.get("display_name") or target.get("canonical_target")
    result = await openclaw_bridge.resolve_target(channel, raw_target, kind=kind, account=data.get("account"))
    if not result.get("success"):
        openclaw_events_manager.add_event(
            "error",
            channel=channel,
            kind=kind,
            target=target.get("canonical_target") or raw_target,
            display_target=target.get("display_name"),
            message="resolve_target",
            success=False,
            error=result.get("error") or result.get("summary"),
            raw=result,
        )
        return _api_from_openclaw_result(result)

    canonical_target = _extract_resolved_target(result, fallback=raw_target)
    updated = openclaw_targets_manager.update_target(
        target_id,
        canonical_target=canonical_target,
        resolved=True,
        raw_openclaw=_extract_openclaw_json(result) or result,
    )
    return _api_success({"target": updated, "openclaw": result})

@app.post("/api/openclaw/targets/{target_id}/mark-allowed")
async def api_openclaw_target_mark_allowed(target_id: str, data: dict = Body(default={})):
    if not openclaw_targets_manager.get_target(target_id):
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    allowed = data.get("allowed", True)
    target = openclaw_targets_manager.mark_allowed(target_id, bool(allowed))
    sync_result = _sync_openclaw_whatsapp_allowlist_best_effort()
    return _api_success({"target": target, "sync": sync_result})

@app.post("/api/openclaw/targets/{target_id}/aliases")
async def api_openclaw_target_add_alias(target_id: str, data: dict = Body(default={})):
    target = openclaw_targets_manager.add_alias(target_id, data.get("alias"))
    if not target:
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    return _api_success(target)

@app.delete("/api/openclaw/targets/{target_id}/aliases")
async def api_openclaw_target_remove_alias(target_id: str, data: dict = Body(default={})):
    target = openclaw_targets_manager.remove_alias(target_id, data.get("alias"))
    if not target:
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    return _api_success(target)

@app.delete("/api/openclaw/targets/{target_id}")
async def api_openclaw_target_delete(target_id: str):
    removed = openclaw_targets_manager.delete_target(target_id)
    if not removed:
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    sync_result = _sync_openclaw_whatsapp_allowlist_best_effort()
    return _api_success({"target": removed, "sync": sync_result})

@app.post("/api/openclaw/contacts/import-csv")
async def api_openclaw_contacts_import_csv(file: UploadFile = File(...)):
    content = await file.read()
    summary = import_contacts_csv(content, openclaw_targets_manager)
    sync_result = _sync_openclaw_whatsapp_allowlist_best_effort()
    return _api_success({**summary, "sync": sync_result})

@app.post("/api/openclaw/contacts/import-vcf")
async def api_openclaw_contacts_import_vcf(file: UploadFile = File(...)):
    content = await file.read()
    summary = import_contacts_vcf(content, openclaw_targets_manager)
    sync_result = _sync_openclaw_whatsapp_allowlist_best_effort()
    return _api_success({**summary, "sync": sync_result})

@app.post("/api/openclaw/read")
async def api_openclaw_read(data: dict = Body(default={})):
    payload = _target_payload_for_openclaw(data)
    target = payload.get("canonical_target") or payload.get("target")
    if not target:
        return _api_error("Falta target para leer la conversacion.", warnings=["missing_target"])
    if str(payload.get("channel", "whatsapp")).lower() == "whatsapp":
        messages = openclaw_messages_manager.list_messages(
            channel="whatsapp",
            target=target,
            limit=int(payload.get("limit", 10) or 10),
        )
        return _api_success(
            messages,
            warning="WhatsApp no soporta lectura de historial mediante OpenClaw. Mostrando mensajes inbound guardados localmente.",
        )
    result = await openclaw_bridge.read_conversation(
        payload.get("channel", "whatsapp"),
        target,
        limit=int(payload.get("limit", 10) or 10),
        before=payload.get("before"),
        after=payload.get("after"),
        around=payload.get("around"),
        message_id=payload.get("message_id"),
        thread_id=payload.get("thread_id"),
    )
    return _api_from_openclaw_result(result)

@app.get("/api/openclaw/messages/new")
async def api_openclaw_messages_new_get(channel: str = "whatsapp", target: str = None, limit: int = 50, mark_read: bool = False):
    messages = openclaw_messages_manager.list_new_messages(channel=channel, target=target, limit=limit, mark_read=mark_read)
    return _api_success(messages)

@app.get("/api/openclaw/messages")
async def api_openclaw_messages(channel: str = None, target: str = None, unread_only: bool = False, limit: int = 50):
    messages = openclaw_messages_manager.list_messages(channel=channel, target=target, unread_only=unread_only, limit=limit)
    unread_count = openclaw_messages_manager.get_unread_count(channel=channel, target=target)
    return _api_success({"messages": messages, "unread_count": unread_count})

@app.get("/api/openclaw/messages/recent")
async def api_openclaw_messages_recent(channel: str = "whatsapp", target: str = None, minutes: int = 5, limit: int = 50, mark_read: bool = False):
    messages = openclaw_messages_manager.list_recent_messages(
        channel=channel,
        target=target,
        minutes=minutes,
        limit=limit,
        mark_read=mark_read,
    )
    return _api_success(messages)

@app.post("/api/openclaw/messages/new")
async def api_openclaw_messages_new_post(data: dict = Body(default={})):
    payload = _target_payload_for_openclaw(data)
    target = payload.get("canonical_target") or payload.get("target")
    messages = openclaw_messages_manager.list_new_messages(
        channel=payload.get("channel", "whatsapp"),
        target=target,
        limit=int(payload.get("limit", 50) or 50),
        mark_read=bool(payload.get("mark_read", False)),
    )
    return _api_success(messages)

@app.post("/api/openclaw/messages/mark-read")
async def api_openclaw_messages_mark_read(data: dict = Body(default={})):
    changed = openclaw_messages_manager.mark_read(
        message_ids=data.get("message_ids"),
        channel=data.get("channel"),
        target=data.get("target"),
    )
    return _api_success({"marked_read": len(changed), "messages": changed})

@app.post("/api/openclaw/targets/{target_id}/messages/new")
async def api_openclaw_target_messages_new(target_id: str, data: dict = Body(default={})):
    target = openclaw_targets_manager.get_target(target_id)
    if not target:
        return _api_error("No encuentro ese target.", warnings=["not_found"])
    messages = openclaw_messages_manager.list_new_messages(
        channel=target.get("channel", "whatsapp"),
        target=target.get("canonical_target") or target.get("raw_target"),
        limit=int(data.get("limit", 50) or 50),
        mark_read=bool(data.get("mark_read", True)),
    )
    return _api_success(messages)

@app.post("/api/openclaw/send-dry-run")
async def api_openclaw_send_dry_run(data: dict = Body(default={})):
    payload = _target_payload_for_openclaw(data)
    payload["dry_run"] = True
    allowed, target_record = _allowed_whatsapp_target_for_payload(payload)
    if not allowed:
        return _api_error(
            f"{(target_record or {}).get('display_name') or payload.get('display_target') or payload.get('target') or 'Ese destino'} no esta en la allowlist de WhatsApp de Jarvis.",
            warnings=["not_allowed"],
        )
    result = await openclaw_bridge.execute_action("send_message", payload)
    openclaw_events_manager.add_event(
        "dry_run",
        channel=payload.get("channel", "whatsapp"),
        kind=payload.get("kind", "auto"),
        target=payload.get("canonical_target") or payload.get("target"),
        display_target=payload.get("display_target") or payload.get("target"),
        message=payload.get("message") or payload.get("text"),
        success=result.get("success"),
        error=result.get("error") or (None if result.get("success") else result.get("summary")),
        raw=result,
    )
    return _api_from_openclaw_result(result)

@app.post("/api/openclaw/send-pending")
async def api_openclaw_send_pending(data: dict = Body(default={})):
    payload = _build_send_payload_from_request(data)
    if not payload or not payload.get("message"):
        return _api_error("Falta target o mensaje para crear el envio pendiente.", warnings=["invalid_request"])
    allowed, target_record = _allowed_whatsapp_target_for_payload(payload)
    if not allowed:
        return _api_error(
            f"{(target_record or {}).get('display_name') or payload.get('display_target') or payload.get('target') or 'Ese destino'} no esta en la allowlist de WhatsApp de Jarvis.",
            warnings=["not_allowed"],
        )
    pending = pending_actions_manager.create_pending_action(
        "send_message",
        payload,
        _openclaw_human_summary("send_message", payload),
    )
    await dispatch_automation_event(
        "pending_action.created",
        {"pending_action": pending, "source": "api_openclaw_send_pending", "payload": payload},
    )
    return _api_success({"pending_action_id": pending["id"], "pending_action": pending})

@app.get("/api/openclaw/events")
async def api_openclaw_events(limit: int = 100, type: str = None, channel: str = None):
    return _api_success(openclaw_events_manager.list_events(limit=limit, type=type, channel=channel))

# Google Calendar token-expiry detection + auto re-auth ----------------------
_google_reauth_in_progress = False


def _result_has_google_token_expiry(result):
    if not result:
        return False
    try:
        blob = json.dumps(result, ensure_ascii=False, default=str).lower()
    except Exception:
        blob = str(result).lower()
    return "invalid_grant" in blob or "token has been expired or revoked" in blob


async def _run_google_reauth():
    """Run the local OAuth helper to regenerate the Google Calendar refresh token."""
    global _google_reauth_in_progress
    if _google_reauth_in_progress:
        return {"success": False, "error": "Una reconexión de Google ya está en curso."}
    _google_reauth_in_progress = True
    try:
        script = str(PROJECT_ROOT / "scripts" / "get_google_calendar_token.py")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=320)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"success": False, "error": "Tiempo de espera agotado durante la reconexión."}
        out = (stdout or b"").decode("utf-8", errors="replace")
        success = proc.returncode == 0
        await sio.emit("calendar_reauth_result", {"success": success})
        return {"success": success, "output": out[-1500:]}
    finally:
        _google_reauth_in_progress = False


async def _maybe_handle_google_expiry(result):
    """If a calendar result shows an expired Google token, surface a friendly
    error, notify the UI, and optionally auto-launch the re-auth flow."""
    if not _result_has_google_token_expiry(result):
        return result

    await sio.emit("calendar_reauth_required", {"reason": "google_token_expired"})

    if _env_bool("JARVIS_GOOGLE_AUTO_REAUTH", False) and not _google_reauth_in_progress:
        asyncio.create_task(_run_google_reauth())

    if isinstance(result, dict):
        result = dict(result)
        result["code"] = "GOOGLE_TOKEN_EXPIRED"
        result["summary"] = "El token de Google Calendar ha caducado. Pulsa 'Reconectar Google Calendar'."
        result["error"] = result["summary"]
    return result


@app.post("/api/openclaw/action")
async def api_openclaw_action(data: dict = Body(default={})):
    action_type = data.get("action_type") or data.get("type")
    payload = data.get("payload") or {}
    result = await _execute_or_queue_openclaw_action(action_type, payload)
    result = await _maybe_handle_google_expiry(result)
    return _api_from_openclaw_result(result)


@app.post("/api/calendar/reauth")
async def api_calendar_reauth():
    """Launch the Google Calendar OAuth re-auth flow (opens a browser to grant access)."""
    result = await _run_google_reauth()
    if result.get("success"):
        return _api_success({
            "message": "Google Calendar reconectado. Recarga el calendario; si sigue fallando, reinicia JARVIS.",
        })
    return _api_error(result.get("error") or "No se pudo reconectar Google Calendar.", data=result)


@app.get("/api/music/status")
async def api_music_status():
    return _api_success(music_manager.status())


@app.get("/api/music/preferences")
async def api_music_preferences_get():
    return _api_success({
        "preferences": music_manager.get_preferences(),
        "history": music_manager.get_history(limit=30),
    })


@app.post("/api/music/preferences")
async def api_music_preferences_update(data: dict = Body(default={})):
    updated = music_manager.update_preferences(data or {})
    return _api_success({"preferences": updated})


@app.post("/api/music/search")
async def api_music_search(data: dict = Body(default={})):
    result = await music_manager.search(data.get("query", ""), data.get("mode", "search"))
    return _api_from_openclaw_result(result) if result.get("success") is False else _api_success(result)


@app.post("/api/music/play")
async def api_music_play(data: dict = Body(default={})):
    result = await music_manager.play(data.get("query", ""), data.get("mode", "search"))
    return _api_success(result) if result.get("success") else _api_error(result.get("error") or "No se pudo reproducir.", data=result)


@app.post("/api/music/random")
async def api_music_random(data: dict = Body(default={})):
    result = await music_manager.random()
    return _api_success(result) if result.get("success") else _api_error(result.get("error") or "No se pudo reproducir.", data=result)


@app.post("/api/music/command")
async def api_music_command(data: dict = Body(default={})):
    command = data.get("command")
    if not str(command or "").strip():
        return _api_error("command es obligatorio.", status_code=400)
    result = music_manager.command(command, volume=data.get("volume"))
    return _api_success(result) if result.get("success") else _api_error(result.get("error") or "Comando no valido.", data=result)


@app.get("/api/automations")
async def api_automations_list():
    return _api_success({"automations": automation_manager.list_automations()})


@app.get("/api/automations/history")
async def api_automations_history(limit: int = 100):
    """Execution history: automation lifecycle events recorded in the event log."""
    events = openclaw_events_manager.list_events(limit=limit, channel="automation")
    return _api_success({"history": events})


@app.get("/api/automations/templates")
async def api_automations_templates():
    return _api_success({"templates": automation_templates.list_templates()})


@app.post("/api/automations/templates/{template_id}/apply")
async def api_automations_apply_template(template_id: str, data: dict = Body(default={})):
    overrides = data if isinstance(data, dict) else {}
    payload = automation_templates.template_as_automation_payload(template_id, overrides)
    if not payload:
        return _api_error("No encuentro esa plantilla.", status_code=404)
    try:
        automation = automation_manager.create_automation(payload)
    except ValueError as exc:
        return _api_error(str(exc), status_code=400)
    return _api_success({"automation": automation, "template_id": template_id})


@app.post("/api/automations")
async def api_automations_create(data: dict = Body(default={})):
    try:
        automation = automation_manager.create_automation(data)
    except ValueError as exc:
        return _api_error(str(exc), status_code=400)
    return _api_success({"automation": automation})


@app.post("/api/automations/events/dispatch")
async def api_automations_event_dispatch(data: dict = Body(default={})):
    event_type = data.get("event_type") or data.get("type")
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if not str(event_type or "").strip():
        return _api_error("event_type es obligatorio.", status_code=400)
    result = await dispatch_automation_event(event_type, payload)
    return _api_success(result)


@app.post("/api/automations/events")
async def api_automations_event_dispatch_alias(data: dict = Body(default={})):
    """Alias of /api/automations/events/dispatch matching the spec."""
    return await api_automations_event_dispatch(data)


@app.get("/api/automations/{automation_id}")
async def api_automations_get(automation_id: str):
    automation = automation_manager.get_automation(automation_id)
    if not automation:
        return _api_error("No encuentro esa automatizacion.", status_code=404)
    return _api_success({"automation": automation})


@app.put("/api/automations/{automation_id}")
async def api_automations_update(automation_id: str, data: dict = Body(default={})):
    try:
        automation = automation_manager.update_automation(automation_id, data)
    except ValueError as exc:
        return _api_error(str(exc), status_code=400)
    if not automation:
        return _api_error("No encuentro esa automatizacion.", status_code=404)
    return _api_success({"automation": automation})


@app.delete("/api/automations/{automation_id}")
async def api_automations_delete(automation_id: str):
    automation = automation_manager.delete_automation(automation_id)
    if not automation:
        return _api_error("No encuentro esa automatizacion.", status_code=404)
    return _api_success({"automation": automation})


@app.post("/api/automations/{automation_id}/run")
async def api_automations_run(automation_id: str):
    return await _run_automation_by_id(automation_id, source="manual")


@app.post("/api/openclaw/inbound")
async def api_openclaw_inbound(request: Request, data: dict = Body(default={})):
    inbound_secret = os.getenv("JARVIS_OPENCLAW_INBOUND_SECRET", "").strip()
    if inbound_secret and request.headers.get("X-Jarvis-OpenClaw-Secret") != inbound_secret:
        return _api_error("Invalid OpenClaw inbound secret.", status_code=401)

    incoming_message = normalize_openclaw_inbound(data)
    target_record = openclaw_targets_manager.upsert_from_inbound(incoming_message)
    stored_message = _save_inbound_message(incoming_message, data)
    inbound_event = openclaw_events_manager.add_event(
        "inbound",
        channel=incoming_message.get("channel"),
        kind=incoming_message.get("kind"),
        target=incoming_message.get("target"),
        display_target=incoming_message.get("display_target"),
        message=incoming_message.get("message"),
        success=True,
        raw=data,
    )

    # Notify frontend and JARVIS about new inbound WhatsApp message
    unread_count = openclaw_messages_manager.get_unread_count(channel="whatsapp")
    await sio.emit("whatsapp_inbound_message", {
        "message": stored_message,
        "unread_count": unread_count,
    })
    await _notify_jarvis_inbound_whatsapp(incoming_message, target_record)

    automation_dispatch = await dispatch_automation_event(
        "openclaw.inbound_message",
        {
            "incoming": incoming_message,
            "message": stored_message,
            "stored_message": stored_message,
            "target": target_record,
            "event": inbound_event,
            "raw": data,
        },
    )

    if str((incoming_message or {}).get("channel") or "").lower() == "whatsapp":
        await dispatch_automation_event(
            "whatsapp.message_received",
            {
                "incoming": incoming_message,
                "message": stored_message,
                "stored_message": stored_message,
                "target": target_record,
                "raw": data,
            },
        )

    if not _env_bool("JARVIS_OPENCLAW_AUTOPILOT_ENABLED", True):
        return _api_success(
            {
                "incoming": incoming_message,
                "message": stored_message,
                "stored_message": stored_message,
                "target": target_record,
                "event": inbound_event,
                "automation_dispatch": automation_dispatch,
                "matched": False,
                "results": [],
            },
            matched=False,
            message="Las respuestas automaticas externas no estan habilitadas.",
        )

    matches = openclaw_autopilot_manager.find_matching_rules(incoming_message)
    if not matches:
        return _api_success(
            {
                "incoming": incoming_message,
                "message": stored_message,
                "stored_message": stored_message,
                "target": target_record,
                "event": inbound_event,
                "automation_dispatch": automation_dispatch,
                "matched": False,
                "results": [],
            },
            matched=False,
            message="No hay reglas activas para este evento.",
        )

    results = []
    for rule in matches:
        reply_text = _build_autopilot_reply(rule, incoming_message)
        mode = rule.get("mode")
        openclaw_events_manager.add_event(
            "rule_match",
            channel=incoming_message.get("channel"),
            kind=incoming_message.get("kind"),
            target=incoming_message.get("target"),
            display_target=incoming_message.get("display_target"),
            message=incoming_message.get("message"),
            success=True,
            raw={"rule_id": rule.get("id"), "mode": mode},
        )

        if openclaw_autopilot_manager.is_message_blocked(rule, incoming_message):
            results.append({"rule_id": rule.get("id"), "mode": mode, "status": "blocked_by_behavior"})
            continue

        if mode == "draft_only":
            pending = _create_pending_autopilot_reply(rule, incoming_message, reply_text, draft_only=True)
            await dispatch_automation_event("pending_action.created", {"pending_action": pending, "source": "openclaw_autopilot", "rule": rule})
            results.append({"rule_id": rule.get("id"), "mode": mode, "status": "draft_pending", "pending_action": pending})
            continue

        if mode == "ask_before_send":
            pending = _create_pending_autopilot_reply(rule, incoming_message, reply_text)
            await dispatch_automation_event("pending_action.created", {"pending_action": pending, "source": "openclaw_autopilot", "rule": rule})
            results.append({"rule_id": rule.get("id"), "mode": mode, "status": "confirmation_required", "pending_action": pending})
            continue

        if mode == "auto_send_limited":
            first_reply_needs_confirmation = (
                rule.get("behavior", {}).get("require_confirmation_for_first_reply", True)
                and int(rule.get("reply_count_total", 0) or 0) == 0
            )
            if first_reply_needs_confirmation:
                pending = _create_pending_autopilot_reply(rule, incoming_message, reply_text)
                await dispatch_automation_event("pending_action.created", {"pending_action": pending, "source": "openclaw_autopilot", "rule": rule})
                results.append({"rule_id": rule.get("id"), "mode": mode, "status": "first_reply_confirmation_required", "pending_action": pending})
                continue

            if not openclaw_autopilot_manager.should_auto_reply(rule, incoming_message):
                results.append({"rule_id": rule.get("id"), "mode": mode, "status": "blocked_by_rule_limits"})
                continue

            result = await openclaw_bridge.execute_autopilot_reply(
                rule,
                {**incoming_message, "reply": reply_text, "outgoing_message": reply_text},
            )
            if result.get("success"):
                openclaw_autopilot_manager.register_reply(rule.get("id"))
            results.append({"rule_id": rule.get("id"), "mode": mode, "status": "executed", "result": result})

    first_pending = next((item.get("pending_action") for item in results if item.get("pending_action")), None)
    first_result = results[0] if results else {}
    return _api_success(
        {
            "incoming": incoming_message,
            "message": stored_message,
            "stored_message": stored_message,
            "target": target_record,
            "event": inbound_event,
            "automation_dispatch": automation_dispatch,
            "rules": matches,
            "matched": True,
            "pending_action_id": first_pending.get("id") if first_pending else None,
            "results": results,
        },
        matched=True,
        rule_id=first_result.get("rule_id"),
        pending_action_id=first_pending.get("id") if first_pending else None,
        mode=first_result.get("mode"),
    )

@app.get("/api/pending-actions")
async def api_pending_actions():
    return {"actions": pending_actions_manager.get_pending_actions()}

@app.post("/api/pending-actions/{action_id}/confirm")
async def api_pending_action_confirm(action_id: str):
    result = await _claim_and_execute_pending_action(action_id)
    await _notify_pending_action_resolution(result, source="dashboard_button")
    return result

@app.post("/api/pending-actions/{action_id}/cancel")
async def api_pending_action_cancel(action_id: str):
    action = pending_actions_manager.cancel_action(action_id)
    if not action:
        return _openclaw_local_result("cancel_pending_action", "No encuentro esa accion pendiente.", success=False, warnings=["not_found"])
    result = _openclaw_local_result("cancel_pending_action", "Accion pendiente cancelada.", raw=action)
    await _notify_pending_action_resolution(result, source="dashboard_button")
    return result

@app.get("/api/openclaw/autopilot/rules")
async def api_openclaw_autopilot_rules():
    return {"rules": openclaw_autopilot_manager.list_rules()}

@app.post("/api/openclaw/autopilot/rules")
async def api_openclaw_autopilot_rules_create(data: dict = Body(default={})):
    result = _create_openclaw_autopilot_rule_from_payload(data)
    pending = result.get("raw") if isinstance(result, dict) else None
    if isinstance(pending, dict) and pending.get("id"):
        await dispatch_automation_event(
            "pending_action.created",
            {"pending_action": pending, "source": "api_openclaw_autopilot_rules_create"},
        )
    return result

@app.post("/api/openclaw/autopilot/rules/{rule_id}/enable")
async def api_openclaw_autopilot_rule_enable(rule_id: str):
    return await _execute_or_queue_openclaw_action(
        "enable_autopilot_rule",
        {"rule_id": rule_id},
        f"Activar regla automatica {rule_id}",
    )

@app.post("/api/openclaw/autopilot/rules/{rule_id}/disable")
async def api_openclaw_autopilot_rule_disable(rule_id: str):
    return await _execute_or_queue_openclaw_action(
        "disable_autopilot_rule",
        {"rule_id": rule_id},
        f"Desactivar regla automatica {rule_id}",
    )

@app.delete("/api/openclaw/autopilot/rules/{rule_id}")
async def api_openclaw_autopilot_rule_delete(rule_id: str):
    return await _execute_or_queue_openclaw_action(
        "delete_autopilot_rule",
        {"rule_id": rule_id},
        f"Eliminar regla automatica {rule_id}",
    )

def _openwa_id_to_canonical(openwa_id: str) -> str:
    """Convert '34600111222@c.us' or '34600111222@g.us' → '+34600111222' / keep @g.us."""
    if not openwa_id:
        return ""
    if openwa_id.endswith("@g.us"):
        return openwa_id  # groups stay as-is
    phone = openwa_id.split("@")[0].strip()
    if phone and not phone.startswith("+"):
        return f"+{phone}"
    return phone


def _normalize_openwa_inbound(data: dict, targets_manager=None) -> dict | None:
    """
    Convert an OpenWA webhook payload to JARVIS's standard inbound message format.
    Returns None for messages sent by us (fromMe=True) or unrecognised events.
    """
    event = str(data.get("event") or "").lower()
    if event and event not in ("message.received", "*", ""):
        return None

    msg = data.get("data") or data  # some variants nest under "data", some are flat
    if not isinstance(msg, dict):
        return None

    from_me = bool(msg.get("fromMe", False))
    if from_me:
        return None  # skip our own sent messages

    from_id = str(msg.get("from") or "").strip()
    chat_id = str(msg.get("chatId") or from_id).strip()
    is_group = bool(msg.get("isGroup", False)) or chat_id.endswith("@g.us")
    body = str(msg.get("body") or "").strip()
    msg_type = str(msg.get("type") or "chat").lower()
    message_id = str(msg.get("id") or data.get("deliveryId") or data.get("idempotencyKey") or "").strip()

    # Normalize timestamp
    ts_raw = msg.get("timestamp")
    try:
        from datetime import datetime as _dt, timezone as _tz
        if isinstance(ts_raw, (int, float)):
            ts = float(ts_raw)
            if ts > 10_000_000_000:
                ts /= 1000
            timestamp_iso = _dt.fromtimestamp(ts, tz=_tz.utc).isoformat(timespec="seconds")
        else:
            ts_str = str(data.get("timestamp") or ts_raw or "").strip()
            if ts_str:
                timestamp_iso = ts_str
            else:
                timestamp_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")
    except Exception:
        from datetime import datetime as _dt, timezone as _tz
        timestamp_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")

    # Resolve contact name from local agenda
    canonical = _openwa_id_to_canonical(from_id)
    display_name = ""
    if targets_manager:
        record = targets_manager.find_by_canonical_target("whatsapp", canonical)
        if not record and from_id != canonical:
            record = targets_manager.find_by_canonical_target("whatsapp", from_id)
        if record:
            display_name = record.get("display_name") or ""
    if not display_name:
        display_name = str(
            msg.get("pushName") or msg.get("senderName") or msg.get("notifyName") or canonical or from_id
        ).strip()

    return {
        "channel": "whatsapp",
        "kind": "group" if is_group else "user",
        "target": canonical or from_id,
        "canonical_target": canonical or from_id,
        "display_target": display_name or canonical or from_id,
        "sender": from_id,
        "sender_name": display_name,
        "message": body,
        "message_id": message_id,
        "timestamp": timestamp_iso,
        "type": msg_type,
        "is_group": is_group,
        "chat_id": chat_id,
    }


@app.post("/api/openwa/inbound")
async def api_openwa_inbound(request: Request, data: dict = Body(default={})):
    """
    Receives webhook events from OpenWA (message.received, session.connected, etc.).
    Configured automatically on JARVIS startup via ensure_webhook_configured().
    """
    event = str(data.get("event") or "").lower()

    # Handle session status events
    if event in ("session.connected", "session.disconnected"):
        await sio.emit("whatsapp_inbound_message", {
            "message": None,
            "unread_count": openclaw_messages_manager.get_unread_count(channel="whatsapp"),
            "session_event": event,
        })
        if event == "session.connected":
            await dispatch_automation_event("openwa.connected", {"event": event, "provider": "openwa", "raw": data})
        return _api_success({"handled": True, "event": event})

    if event and event != "message.received":
        return _api_success({"handled": False, "event": event, "reason": "event_ignored"})

    incoming_message = _normalize_openwa_inbound(data, targets_manager=openclaw_targets_manager)
    if incoming_message is None:
        return _api_success({"handled": False, "reason": "from_me_or_invalid"})

    # Resolve the real phone number + contact name. WhatsApp now uses LIDs
    # (e.g. 222092792471622@lid) instead of phone numbers for privacy; OpenWA's
    # contact endpoint maps the LID to the real number ("id": 34xxxx@c.us) and name.
    await _resolve_openwa_real_identity(incoming_message)

    target_record = openclaw_targets_manager.upsert_from_inbound(incoming_message)

    # Auto-allow contacts that message us so JARVIS can reply to them
    if target_record and not target_record.get("allowed"):
        target_record = openclaw_targets_manager.mark_allowed(target_record["id"], True)

    stored_message = _save_inbound_message(incoming_message, data)
    openclaw_events_manager.add_event(
        "inbound",
        channel=incoming_message.get("channel"),
        kind=incoming_message.get("kind"),
        target=incoming_message.get("target"),
        display_target=incoming_message.get("display_target"),
        message=incoming_message.get("message"),
        success=True,
        raw=data,
    )

    unread_count = openclaw_messages_manager.get_unread_count(channel="whatsapp")
    await sio.emit("whatsapp_inbound_message", {
        "message": stored_message,
        "unread_count": unread_count,
    })
    await _notify_jarvis_inbound_whatsapp(incoming_message, target_record)

    await dispatch_automation_event(
        "openclaw.inbound_message",
        {
            "incoming": incoming_message,
            "message": stored_message,
            "stored_message": stored_message,
            "target": target_record,
            "raw": data,
        },
    )

    if str((incoming_message or {}).get("channel") or "").lower() == "whatsapp":
        await dispatch_automation_event(
            "whatsapp.message_received",
            {
                "incoming": incoming_message,
                "message": stored_message,
                "stored_message": stored_message,
                "target": target_record,
                "raw": data,
            },
        )

    return _api_success({
        "handled": True,
        "event": event or "message.received",
        "message_id": stored_message.get("id"),
        "sender": incoming_message.get("display_target"),
    })


# Cache LID/contact-id -> {canonical, name} so we don't hit OpenWA on every message.
_openwa_identity_cache = {}


async def _resolve_openwa_real_identity(incoming_message):
    """Resolve a WhatsApp sender's REAL phone number and contact name via OpenWA.

    WhatsApp now sends a LID (e.g. 222092792471622@lid) instead of the phone
    number. OpenWA's contact endpoint maps it: it returns the real number in the
    "id" field (34635366743@c.us) and the saved name in "name"/"pushName".
    Mutates incoming_message in place with the real canonical_target and name.
    """
    if incoming_message.get("is_group"):
        return  # groups keep their @g.us id

    sender_raw = str(incoming_message.get("sender") or "").strip()
    if not sender_raw or "@" not in sender_raw:
        return

    # Cache hit
    cached = _openwa_identity_cache.get(sender_raw)
    if cached:
        if cached.get("canonical"):
            incoming_message["target"] = cached["canonical"]
            incoming_message["canonical_target"] = cached["canonical"]
        if cached.get("name"):
            incoming_message["display_target"] = cached["name"]
            incoming_message["sender_name"] = cached["name"]
        return

    try:
        sid = await openwa_bridge._get_session_uuid()
        raw = await openwa_bridge._http_get(f"/sessions/{sid}/contacts/{sender_raw}")
        if not isinstance(raw, dict) or not raw.get("success"):
            return
        contact = raw.get("json") or {}
        real_id = str(contact.get("id") or "").strip()
        name = (str(contact.get("name") or "").strip() or str(contact.get("pushName") or "").strip())

        canonical = None
        if real_id.endswith("@c.us"):
            canonical = "+" + real_id.split("@")[0]
            incoming_message["target"] = canonical
            incoming_message["canonical_target"] = canonical
        if name:
            incoming_message["display_target"] = name
            incoming_message["sender_name"] = name

        _openwa_identity_cache[sender_raw] = {"canonical": canonical, "name": name}
        if len(_openwa_identity_cache) > 2000:
            _openwa_identity_cache.clear()
    except Exception:
        pass


# Inbound-notification throttling state.
# WhatsApp/OpenWA replays a burst of recent messages when the session connects.
# Without throttling, each one would fire session.send() into the live Gemini
# session concurrently and crash it (error 1007 "invalid argument").
_announced_whatsapp_ids = set()
_last_whatsapp_voice_announce_at = 0.0


def _message_age_seconds(incoming_message):
    """Return how many seconds ago the message was sent, or None if unknown."""
    from datetime import datetime as _dt, timezone as _tz
    raw = incoming_message.get("timestamp")
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 10_000_000_000:
                ts /= 1000
            sent = _dt.fromtimestamp(ts, tz=_tz.utc)
        else:
            sent = _dt.fromisoformat(str(raw).replace("Z", "+00:00"))
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=_tz.utc)
        return (_dt.now(_tz.utc) - sent).total_seconds()
    except Exception:
        return None


async def _notify_jarvis_inbound_whatsapp(incoming_message, target_record=None):
    """Emit a notification and optionally wake JARVIS to announce a new inbound WhatsApp.

    Heavily guarded against the message burst OpenWA replays on session connect:
    deduplicates by message_id, ignores old messages, and rate-limits the live
    voice announcement so it never floods the Gemini Live session.
    """
    global _last_whatsapp_voice_announce_at

    if not _env_bool("JARVIS_WHATSAPP_NOTIFY_INBOUND", True):
        return

    channel = str(incoming_message.get("channel") or "whatsapp").lower()
    if channel != "whatsapp":
        return

    # Deduplicate: never announce the same message_id twice (handles reconnect replays)
    message_id = str(incoming_message.get("message_id") or "").strip()
    if message_id:
        if message_id in _announced_whatsapp_ids:
            return
        _announced_whatsapp_ids.add(message_id)
        # Bound the set so it doesn't grow forever
        if len(_announced_whatsapp_ids) > 2000:
            _announced_whatsapp_ids.clear()
            _announced_whatsapp_ids.add(message_id)

    # Ignore old messages (the burst replayed when the WhatsApp session connects).
    # Only genuinely recent messages should trigger a notification.
    max_age = float(os.getenv("JARVIS_WHATSAPP_INBOUND_MAX_AGE_SECONDS", "120") or 120)
    age = _message_age_seconds(incoming_message)
    if age is not None and age > max_age:
        return

    display = (
        (target_record or {}).get("display_name")
        or incoming_message.get("display_target")
        or incoming_message.get("sender")
        or incoming_message.get("target")
        or "Desconocido"
    )
    body = str(incoming_message.get("message") or "").strip()
    preview = body[:80]
    notification_text = f"Nuevo WhatsApp de {display}." + (f" Dice: {preview}" if preview else "")

    voice_announce = _env_bool("JARVIS_WHATSAPP_VOICE_ANNOUNCE_INBOUND", True)
    session = getattr(audio_loop, "session", None) if audio_loop else None

    # Rate-limit the live voice announcement (cooldown). If we announced very
    # recently, fall back to a visual-only notification to avoid flooding Gemini.
    cooldown = float(os.getenv("JARVIS_WHATSAPP_VOICE_ANNOUNCE_COOLDOWN_SECONDS", "12") or 12)
    now = time.time()
    can_voice = voice_announce and session and (now - _last_whatsapp_voice_announce_at) >= cooldown

    if can_voice:
        try:
            _last_whatsapp_voice_announce_at = now
            content_for_voice = body[:400]
            await session.send(
                input=(
                    "[NOTIFICACION INTERNA DEL SISTEMA - NO es una peticion del usuario] "
                    f"Acaba de entrar un mensaje de WhatsApp de {display}. "
                    + (f'El mensaje dice: "{content_for_voice}". ' if content_for_voice else "El mensaje no tiene texto (puede ser una imagen o audio). ")
                    + "Avisa al usuario en voz alta: di de quien es y lee o resume brevemente lo que dice. "
                    "PROHIBIDO: no uses ninguna herramienta, no llames a openclaw_send_message, "
                    "no envies ningun mensaje, no respondas al remitente por tu cuenta. Solo informa de lo que ha llegado."
                ),
                end_of_turn=True,
            )
            return
        except Exception as exc:
            print(f"[SERVER] Could not send WhatsApp inbound notification to JARVIS session: {exc}")

    # Visual-only notification (cooldown active, voice disabled, or no live session)
    await sio.emit("transcription", {"sender": "JARVIS", "text": notification_text, "append": False})


# ---------------------------------------------------------------------------
# WhatsApp provider endpoints (/api/whatsapp/*)
# These work regardless of the configured provider.
# ---------------------------------------------------------------------------

@app.get("/api/whatsapp/provider")
async def api_whatsapp_provider():
    provider = _whatsapp_provider()
    return _api_success({
        "provider": provider,
        "openwa_enabled": openwa_bridge.is_enabled(),
        "openclaw_enabled": openclaw_bridge.is_enabled(),
    })

@app.get("/api/whatsapp/status")
async def api_whatsapp_status():
    provider = _whatsapp_provider()
    if provider == "openwa":
        status = await openwa_bridge.check_status()
        return _api_success({
            **status,
            "provider": "openwa",
            "success": status.get("available", False),
        })
    # Fallback: return openclaw status with whatsapp label
    result = await openclaw_bridge.check_status()
    return _api_from_openclaw_result(result)

@app.post("/api/whatsapp/session/create")
async def api_whatsapp_session_create(data: dict = Body(default={})):
    name = data.get("name") or os.getenv("JARVIS_OPENWA_SESSION_ID", "jarvis-main")
    result = await openwa_bridge.create_session(name=name)
    return _api_success(result) if result.get("success") else _api_error(
        result.get("summary") or "No se pudo crear la sesión OpenWA.",
        data=result,
    )

@app.post("/api/whatsapp/session/start")
async def api_whatsapp_session_start(data: dict = Body(default={})):
    session_id = data.get("session_id") or os.getenv("JARVIS_OPENWA_SESSION_ID", "jarvis-main")
    result = await openwa_bridge.start_session(session_id=session_id)
    return _api_success(result) if result.get("success") else _api_error(
        result.get("summary") or "No se pudo iniciar la sesión OpenWA.",
        data=result,
    )

@app.get("/api/whatsapp/session/qr")
async def api_whatsapp_session_qr(session_id: str = None):
    sid = session_id or os.getenv("JARVIS_OPENWA_SESSION_ID", "jarvis-main")
    result = await openwa_bridge.get_qr(session_id=sid)
    return _api_success(result) if result.get("success") else _api_error(
        result.get("summary") or "No se pudo obtener el QR de OpenWA.",
        data=result,
    )

@app.get("/api/whatsapp/messages")
async def api_whatsapp_messages(limit: int = 30, unread_only: bool = False):
    messages = openclaw_messages_manager.list_messages(
        channel="whatsapp", unread_only=unread_only, limit=limit
    )
    unread_count = openclaw_messages_manager.get_unread_count(channel="whatsapp")
    return _api_success({"messages": messages, "unread_count": unread_count})

@app.post("/api/whatsapp/messages/mark-read")
async def api_whatsapp_messages_mark_read(data: dict = Body(default={})):
    changed = openclaw_messages_manager.mark_read(
        message_ids=data.get("message_ids"),
        channel="whatsapp",
        target=data.get("target"),
    )
    unread_count = openclaw_messages_manager.get_unread_count(channel="whatsapp")
    return _api_success({"marked_read": len(changed), "unread_count": unread_count})

@app.post("/api/whatsapp/send")
async def api_whatsapp_send(data: dict = Body(default={})):
    payload = _build_send_payload_from_request(data)
    if not payload or not payload.get("message"):
        return _api_error("Falta target o mensaje.", warnings=["invalid_request"])
    allowed, target_record = _allowed_whatsapp_target_for_payload(payload)
    if not allowed:
        return _api_error(
            f"{(target_record or {}).get('display_name') or payload.get('target') or 'Ese destino'} no esta en la allowlist.",
            warnings=["not_allowed"],
        )
    pending = pending_actions_manager.create_pending_action(
        "send_message",
        payload,
        _openclaw_human_summary("send_message", payload),
    )
    await dispatch_automation_event(
        "pending_action.created",
        {"pending_action": pending, "source": "api_whatsapp_send", "payload": payload},
    )
    return _api_success({"pending_action_id": pending["id"], "pending_action": pending})


# ---------------------------------------------------------------------------
# WhatsApp contacts and groups from OpenWA session
# ---------------------------------------------------------------------------

def _openwa_phone_to_canonical(contact_id: str) -> str:
    """Convert '34600111222@c.us' to '+34600111222'."""
    phone = str(contact_id or "").split("@")[0].strip()
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    return phone

@app.get("/api/whatsapp/contacts")
async def api_whatsapp_contacts():
    result = await openwa_bridge.get_contacts()
    return _api_success(result) if result.get("success") else _api_error(
        result.get("summary") or "No se pudieron obtener los contactos de OpenWA.",
        data=result,
    )

@app.post("/api/whatsapp/contacts/sync")
async def api_whatsapp_contacts_sync(data: dict = Body(default={})):
    """Import contacts from the active OpenWA session into the local JARVIS agenda."""
    result = await openwa_bridge.get_contacts()
    if not result.get("success"):
        return _api_error(result.get("summary") or "No se pudieron obtener los contactos.", data=result)

    contacts = result.get("contacts") or []
    added = updated = skipped = 0

    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        cid = str(contact.get("id") or "").strip()
        if not cid.endswith("@c.us"):
            continue  # skip groups and broadcast lists
        name = (contact.get("name") or contact.get("pushName") or "").strip()
        if not name:
            continue
        canonical = _openwa_phone_to_canonical(cid)
        if not canonical or canonical == "+":
            continue

        existing = openclaw_targets_manager.find_by_canonical_target("whatsapp", canonical)
        if existing:
            skipped += 1
            continue

        openclaw_targets_manager.add_target(
            channel="whatsapp",
            kind="user",
            display_name=name,
            raw_target=canonical,
            canonical_target=canonical,
            resolved=True,
            allowed=True,
            source="openwa_sync",
        )
        added += 1

    _sync_openclaw_whatsapp_allowlist_best_effort(force=True)
    return _api_success({
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "total_from_openwa": len(contacts),
        "summary": f"Sync completado: {added} añadidos, {skipped} ya existían.",
    })

@app.get("/api/whatsapp/groups")
async def api_whatsapp_groups():
    result = await openwa_bridge.get_groups()
    return _api_success(result) if result.get("success") else _api_error(
        result.get("summary") or "No se pudieron obtener los grupos de OpenWA.",
        data=result,
    )

@app.post("/api/whatsapp/groups/sync")
async def api_whatsapp_groups_sync(data: dict = Body(default={})):
    """Import groups from the active OpenWA session into the local JARVIS agenda."""
    result = await openwa_bridge.get_groups()
    if not result.get("success"):
        return _api_error(result.get("summary") or "No se pudieron obtener los grupos.", data=result)

    groups = result.get("groups") or []
    added = skipped = 0

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = str(group.get("id") or "").strip()
        if not gid.endswith("@g.us"):
            continue
        name = (group.get("name") or group.get("subject") or "").strip()
        if not name:
            name = gid

        existing = openclaw_targets_manager.find_by_canonical_target("whatsapp", gid)
        if existing:
            skipped += 1
            continue

        openclaw_targets_manager.add_target(
            channel="whatsapp",
            kind="group",
            display_name=name,
            raw_target=gid,
            canonical_target=gid,
            resolved=True,
            allowed=True,
            source="openwa_sync",
        )
        added += 1

    _sync_openclaw_whatsapp_allowlist_best_effort(force=True)
    return _api_success({
        "added": added,
        "skipped": skipped,
        "total_from_openwa": len(groups),
        "summary": f"Sync completado: {added} grupos añadidos, {skipped} ya existían.",
    })

@app.post("/api/whatsapp/send-image")
async def api_whatsapp_send_image(data: dict = Body(default={})):
    """Create a pending action to send a WhatsApp image. Requires confirmation."""
    payload = _build_send_payload_from_request(data)
    if not payload:
        return _api_error("Falta target para enviar la imagen.", warnings=["invalid_request"])
    image_url = data.get("image_url") or data.get("url")
    base64_data = data.get("base64")
    if not image_url and not base64_data:
        return _api_error("Falta image_url o base64 para la imagen.", warnings=["invalid_request"])

    payload["action_type"] = "send_image"
    payload["image_url"] = image_url
    payload["base64"] = base64_data
    payload["mimetype"] = data.get("mimetype", "image/jpeg")
    payload["caption"] = data.get("caption") or data.get("message") or ""
    payload["message"] = payload["caption"] or "[imagen]"

    allowed, target_record = _allowed_whatsapp_target_for_payload(payload)
    if not allowed:
        return _api_error(
            f"{(target_record or {}).get('display_name') or payload.get('target') or 'Ese destino'} no esta en la allowlist.",
            warnings=["not_allowed"],
        )
    pending = pending_actions_manager.create_pending_action(
        "send_image",
        payload,
        f"Enviar imagen a {payload.get('display_target') or payload.get('target')}"
        + (f": {payload['caption']}" if payload.get("caption") else ""),
    )
    await dispatch_automation_event(
        "pending_action.created",
        {"pending_action": pending, "source": "api_whatsapp_send_image", "payload": payload},
    )
    return _api_success({"pending_action_id": pending["id"], "pending_action": pending})


@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to J.A.R.V.I.S Backend'}, room=sid)
    await sio.emit('simulation_status', simulation_manager.get_state(), room=sid)

    global authenticator
    
    # Callback for Auth Status
    async def on_auth_status(is_auth):
        print(f"[SERVER] Auth status change: {is_auth}")
        await sio.emit('auth_status', {'authenticated': is_auth})
        if is_auth:
            await dispatch_automation_event("camera.real_person_verified", {"source": "face_auth"})

    # Callback for Auth Camera Frames
    async def on_auth_frame(frame_b64):
        await sio.emit('auth_frame', {'image': frame_b64})

    # Initialize Authenticator if not already done
    if authenticator is None:
        authenticator = FaceAuthenticator(
            reference_image_path=str(REFERENCE_IMAGE_FILE),
            on_status_change=on_auth_status,
            on_frame=on_auth_frame
        )
    
    if SETTINGS.get("face_auth_enabled", False):
        await require_fresh_face_auth(reload_reference=True)
    else:
        print("Face Auth Disabled. Auto-authenticating.")
        await sio.emit('auth_status', {'authenticated': True})

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.event
async def start_audio(sid, data=None):
    global audio_loop, loop_task
    
    # Optional: Block if not authenticated
    # Only block if auth is ENABLED and not authenticated
    if SETTINGS.get("face_auth_enabled", False):
        if not authenticator:
            print("Blocked start_audio: Authenticator not initialized.")
            await sio.emit('error', {'msg': 'Authentication Unavailable'})
            return

        if not authenticator.authenticated:
            print("Blocked start_audio: Not authenticated. Starting face auth now.")
            await require_fresh_face_auth(reload_reference=True)
            await sio.emit('error', {'msg': 'Authentication Required'})
            return

    print("Starting Audio Loop...")
    
    device_index = None
    device_name = None
    if data:
        if 'device_index' in data:
            device_index = data['device_index']
        if 'device_name' in data:
            device_name = data['device_name']
            
    print(f"Using input device: Name='{device_name}', Index={device_index}")
    
    if audio_loop:
        if loop_task and (loop_task.done() or loop_task.cancelled()):
             print("Audio loop task appeared finished/cancelled. Clearing and restarting...")
             audio_loop = None
             loop_task = None
        else:
             print("Audio loop already running. Re-connecting client to session.")
             await sio.emit('status', {'msg': 'J.A.R.V.I.S Already Running'})
             return


    # Callback to send audio data to frontend
    def on_audio_data(data_bytes):
        # We need to schedule this on the event loop
        # This is high frequency, so we might want to downsample or batch if it's too much
        asyncio.create_task(sio.emit('audio_data', {'data': list(data_bytes)}))

    # Callback to send CAL data to frontend
    def on_cad_data(data):
        info = f"{len(data.get('vertices', []))} vertices" if 'vertices' in data else f"{len(data.get('data', ''))} bytes (STL)"
        print(f"Sending CAD data to frontend: {info}")
        asyncio.create_task(sio.emit('cad_data', data))

    # Callback to send Browser data to frontend
    def on_web_data(data):
        print(f"Sending Browser data to frontend: {len(data.get('log', ''))} chars logs")
        asyncio.create_task(sio.emit('browser_frame', data))
        
    # Callback to send Transcription data to frontend
    def on_transcription(data):
        # data = {"sender": "User"|"JARVIS", "text": "..."}
        asyncio.create_task(sio.emit('transcription', data))

    # Callback to send Confirmation Request to frontend
    def on_tool_confirmation(data):
        # data = {"id": "uuid", "tool": "tool_name", "args": {...}}
        print(f"Requesting confirmation for tool: {data.get('tool')}")
        asyncio.create_task(sio.emit('tool_confirmation_request', data))

    # Callback to send CAD status to frontend
    def on_cad_status(status):
        # status can be: 
        # - a string like "generating" (from jarvis.py handle_cad_request)
        # - a dict with {status, attempt, max_attempts, error} (from CadAgent)
        if isinstance(status, dict):
            print(f"Sending CAD Status: {status.get('status')} (attempt {status.get('attempt')}/{status.get('max_attempts')})")
            asyncio.create_task(sio.emit('cad_status', status))
        else:
            # Legacy: simple string
            print(f"Sending CAD Status: {status}")
            asyncio.create_task(sio.emit('cad_status', {'status': status}))

    # Callback to send CAD thoughts to frontend (streaming)
    def on_cad_thought(thought_text):
        asyncio.create_task(sio.emit('cad_thought', {'text': thought_text}))

    # Callback to send Project Update to frontend
    def on_project_update(project_name):
        print(f"Sending Project Update: {project_name}")
        asyncio.create_task(sio.emit('project_update', {'project': project_name}))

    # Callback to send Device Update to frontend
    def on_device_update(devices):
        # devices is a list of dicts
        print(f"Sending Kasa Device Update: {len(devices)} devices")
        asyncio.create_task(sio.emit('kasa_devices', devices))

    def on_simulation_update(message=None):
        asyncio.create_task(emit_simulation_snapshot(message))

    # Callback to send Error to frontend
    def on_error(msg):
        print(f"Sending Error to frontend: {msg}")
        asyncio.create_task(sio.emit('error', {'msg': msg}))

    # Initialize JARVIS
    try:
        print(f"Initializing AudioLoop with device_index={device_index}")
        audio_loop = jarvis.AudioLoop(
            video_mode="none", 
            on_audio_data=on_audio_data,
            on_cad_data=on_cad_data,
            on_web_data=on_web_data,
            on_transcription=on_transcription,
            on_tool_confirmation=on_tool_confirmation,
            on_cad_status=on_cad_status,
            on_cad_thought=on_cad_thought,
            on_project_update=on_project_update,
            on_device_update=on_device_update,
            on_simulation_update=on_simulation_update,
            on_error=on_error,

            input_device_index=device_index,
            input_device_name=device_name,
            kasa_agent=kasa_agent
        )
        print("AudioLoop initialized successfully.")

        # Share the same OpenClaw state managers with the HTTP/dashboard layer.
        # Voice runs inside AudioLoop, but contacts can be imported from the
        # dashboard after startup; using the same objects keeps aliases,
        # pending actions and inbound messages coherent everywhere.
        audio_loop.openclaw_bridge = openclaw_bridge
        audio_loop.openclaw_permissions = openclaw_permissions
        audio_loop.pending_actions_manager = pending_actions_manager
        audio_loop.openclaw_autopilot_manager = openclaw_autopilot_manager
        audio_loop.openclaw_targets_manager = openclaw_targets_manager
        audio_loop.openclaw_messages_manager = openclaw_messages_manager
        audio_loop.music_manager = music_manager

        # Apply current permissions
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
        
        # Check initial mute state
        if data and data.get('muted', False):
            print("Starting with Audio Paused")
            audio_loop.set_paused(True)

        print("Creating asyncio task for AudioLoop.run()")
        loop_task = asyncio.create_task(audio_loop.run())
        
        # Add a done callback to catch silent failures in the loop
        def handle_loop_exit(task):
            try:
                task.result()
            except asyncio.CancelledError:
                print("Audio Loop Cancelled")
            except Exception as e:
                print(f"Audio Loop Crashed: {e}")
                # You could emit 'error' here if you have context
        
        loop_task.add_done_callback(handle_loop_exit)
        
        print("Emitting 'J.A.R.V.I.S Started'")
        await sio.emit('status', {'msg': 'J.A.R.V.I.S Started'})

        # Load saved printers
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers and audio_loop.printer_agent:
            print(f"[SERVER] Loading {len(saved_printers)} saved printers...")
            for p in saved_printers:
                audio_loop.printer_agent.add_printer_manually(
                    name=p.get("name", p["host"]),
                    host=p["host"],
                    port=p.get("port", 80),
                    printer_type=p.get("type", "moonraker"),
                    camera_url=p.get("camera_url")
                )
        
        # Start Printer Monitor
        asyncio.create_task(monitor_printers_loop())
        
    except Exception as e:
        print(f"CRITICAL ERROR STARTING JARVIS: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Failed to start: {str(e)}"})
        audio_loop = None # Ensure we can try again


async def _maybe_dispatch_printer_finished(status_data):
    status_data = status_data or {}
    printer_name = str(status_data.get("printer") or status_data.get("name") or status_data.get("host") or "").strip()
    if not printer_name:
        return

    state = str(status_data.get("state") or "").strip().lower()
    try:
        progress = float(status_data.get("progress_percent") or 0)
    except Exception:
        progress = 0.0
    filename = str(status_data.get("filename") or "unknown").strip()
    finished = state in {"completed", "complete", "finished", "done"} or progress >= 100
    key_prefix = f"{printer_name}|"
    key = f"{key_prefix}{filename}"

    if not finished:
        for existing in list(printer_finished_events):
            if existing.startswith(key_prefix):
                printer_finished_events.discard(existing)
        return

    if key in printer_finished_events:
        return
    printer_finished_events.add(key)
    await dispatch_automation_event("printer.finished", {"printer": printer_name, "status": status_data})


async def monitor_printers_loop():
    """Background task to query printer status periodically."""
    print("[SERVER] Starting Printer Monitor Loop")
    while audio_loop and audio_loop.printer_agent:
        next_sleep = 15
        try:
            if simulation_manager.is_printer_enabled():
                has_active_print = False
                for status_data in printer_simulator.get_all_printer_states():
                    await sio.emit('print_status_update', status_data)
                    await _maybe_dispatch_printer_finished(status_data)
                    state = str(status_data.get("state") or "").lower()
                    has_active_print = has_active_print or any(token in state for token in ("print", "paus", "heat"))
                await emit_simulation_snapshot()
                await asyncio.sleep(5 if has_active_print else 15)
                continue

            agent = audio_loop.printer_agent
            if not agent.printers:
                await asyncio.sleep(next_sleep)
                continue
                
            tasks = []
            for host, printer in agent.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(agent.get_print_status(host))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                has_active_print = False
                for res in results:
                    if isinstance(res, Exception):
                        pass # Ignore errors for now
                    elif res:
                        # res is PrintStatus object
                        status_data = res.to_dict()
                        await sio.emit('print_status_update', status_data)
                        await _maybe_dispatch_printer_finished(status_data)
                        state = str(status_data.get("state") or "").lower()
                        has_active_print = has_active_print or any(token in state for token in ("print", "paus", "heat"))
                next_sleep = 5 if has_active_print else 15
                        
        except asyncio.CancelledError:
            print("[SERVER] Printer Monitor Cancelled")
            break
        except Exception as e:
            print(f"[SERVER] Monitor Loop Error: {e}")
            
        await asyncio.sleep(next_sleep)

@sio.event
async def stop_audio(sid):
    global audio_loop, loop_task
    if audio_loop:
        loop_to_stop = audio_loop
        task_to_stop = loop_task

        print("Stopping Audio Loop")
        loop_to_stop.stop()

        if task_to_stop and not task_to_stop.done():
            try:
                await asyncio.wait_for(asyncio.shield(task_to_stop), timeout=5)
            except asyncio.TimeoutError:
                print("[SERVER] Audio loop did not stop in time. Cancelling task...")
                task_to_stop.cancel()
                try:
                    await task_to_stop
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[SERVER] Audio loop stopped with error: {e}")

        if audio_loop is loop_to_stop:
            audio_loop = None
        if loop_task is task_to_stop:
            loop_task = None

        await sio.emit('status', {'msg': 'J.A.R.V.I.S Stopped'})

        if SETTINGS.get("face_auth_enabled", False) and authenticator:
            print("[SERVER] Face Auth enabled. Clearing auth state after stop; will prompt on next start.")
            authenticator.reset_authentication()

@sio.event
async def pause_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(True)
        print("Pausing Audio")
        await sio.emit('status', {'msg': 'Audio Paused'})

@sio.event
async def resume_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(False)
        print("Resuming Audio")
        await sio.emit('status', {'msg': 'Audio Resumed'})

@sio.event
async def confirm_tool(sid, data):
    # data: { "id": "...", "confirmed": True/False }
    request_id = data.get('id')
    confirmed = data.get('confirmed', False)
    
    print(f"[SERVER DEBUG] Received confirmation response for {request_id}: {confirmed}")

    pending = pending_actions_manager.get_action(request_id)
    if pending:
        if not confirmed:
            action = pending_actions_manager.cancel_action(request_id)
            result = _openclaw_local_result("cancel_pending_action", "Accion cancelada.", raw=action)
            await _notify_pending_action_resolution(result, source="confirmation_popup", room=sid)
            return

        result = await _claim_and_execute_pending_action(request_id)
        await _notify_pending_action_resolution(result, source="confirmation_popup", room=sid)
        return
    
    if audio_loop:
        audio_loop.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Audio loop not active, cannot resolve confirmation.")

async def _handle_text_pending_confirmation(sid, text):
    wants_confirm = _is_text_confirmation(text)
    wants_cancel = _is_text_cancellation(text)
    if not wants_confirm and not wants_cancel:
        return False

    pending_actions = pending_actions_manager.get_pending_actions()
    if not pending_actions:
        return False

    if len(pending_actions) > 1:
        message = "Tienes varias acciones pendientes. Confirma desde el panel para evitar enviar la equivocada."
        await sio.emit('transcription', {'sender': 'JARVIS', 'text': message, 'append': False}, room=sid)
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)
            audio_loop.project_manager.log_chat("JARVIS", message)
        return True

    pending = pending_actions[0]
    if wants_cancel:
        action = pending_actions_manager.cancel_action(pending["id"])
        result = _openclaw_local_result("cancel_pending_action", "Accion cancelada.", raw=action)
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)
        await _notify_pending_action_resolution(result, source="spoken_confirmation", room=sid)
        return True

    result = await _claim_and_execute_pending_action(pending["id"])
    if audio_loop and audio_loop.project_manager:
        audio_loop.project_manager.log_chat("User", text)
    await _notify_pending_action_resolution(result, source="spoken_confirmation", room=sid)
    return True

@sio.event
async def shutdown(sid, data=None):
    """Gracefully shutdown the server when the application closes."""
    global audio_loop, loop_task, authenticator
    
    print("[SERVER] ========================================")
    print("[SERVER] SHUTDOWN SIGNAL RECEIVED FROM FRONTEND")
    print("[SERVER] ========================================")
    
    # Stop audio loop
    if audio_loop:
        print("[SERVER] Stopping Audio Loop...")
        audio_loop.stop()
        audio_loop = None
    
    # Cancel the loop task if running
    if loop_task and not loop_task.done():
        print("[SERVER] Cancelling loop task...")
        loop_task.cancel()
        loop_task = None
    
    # Stop authenticator if running
    if authenticator:
        print("[SERVER] Stopping Authenticator...")
        authenticator.stop()
    
    print("[SERVER] Graceful shutdown complete. Terminating process...")
    
    # Force exit immediately - os._exit bypasses cleanup but ensures termination
    os._exit(0)

@sio.event
async def user_input(sid, data):
    text = data.get('text')
    print(f"[SERVER DEBUG] User input received: '{text}'")

    intent = _simulation_command_intent(text)
    if intent:
        message = await set_simulation_mode(intent == "activate")
        await sio.emit('transcription', {'sender': 'JARVIS', 'text': message, 'append': False})
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("JARVIS", message)
        return

    if _is_capability_question(text):
        message = _jarvis_capability_response()
        await sio.emit('transcription', {'sender': 'JARVIS', 'text': message, 'append': False})
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("JARVIS", message)
        if audio_loop and audio_loop.session:
            try:
                await audio_loop.session.send(
                    input=(
                        "System Notification: The user asked about Jarvis capabilities. "
                        "The app answered directly without mentioning internal gateways, so do not answer this again."
                    ),
                    end_of_turn=False,
                )
            except Exception as e:
                print(f"[SERVER DEBUG] Failed to sync capability answer to live session: {e}")
        return

    if await _handle_text_pending_confirmation(sid, text):
        return

    local_openclaw_intent = route_openclaw_voice_intent(
        text,
        openclaw_targets_manager,
        openclaw_messages_manager,
        pending_actions_manager,
        session_id=sid,
    )
    if local_openclaw_intent.get("handled"):
        message = local_openclaw_intent.get("response") or local_openclaw_intent.get("message") or "He gestionado la accion de WhatsApp."
        await sio.emit('transcription', {'sender': 'JARVIS', 'text': message, 'append': False})
        pending_action = (local_openclaw_intent.get("data") or {}).get("pending_action") or local_openclaw_intent.get("pending_action")
        if pending_action:
            await sio.emit('openclaw_pending_action', pending_action)
            await sio.emit('tool_confirmation_request', {
                "id": pending_action.get("id"),
                "tool": pending_action.get("action_type"),
                "args": pending_action.get("payload"),
            })
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)
            audio_loop.project_manager.log_chat("JARVIS", message)
        if _env_bool("JARVIS_SYNC_LOCAL_WHATSAPP_TO_MODEL", False) and audio_loop and audio_loop.session:
            try:
                await audio_loop.session.send(
                    input=(
                        "System Notification: The app handled this WhatsApp alias/local-message intent directly. "
                        "Do not call OpenClaw for resolve/read and do not answer it again. "
                        f"User text: {text}\nResult: {message}"
                    ),
                    end_of_turn=False,
                )
            except Exception as e:
                print(f"[SERVER DEBUG] Failed to sync local OpenClaw intent: {e}")
        return

    if not audio_loop:
        print("[SERVER DEBUG] [Error] Audio loop is None. Cannot send text.")
        return

    if not audio_loop.session:
        print("[SERVER DEBUG] [Error] Session is None. Cannot send text.")
        return

    if text:
        print(f"[SERVER DEBUG] Sending message to model: '{text}'")
        
        # Log User Input to Project History
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)

        fresh_image = data.get('image')
        if fresh_image:
            print("[SERVER DEBUG] Received fresh webcam frame with text input.")
            await audio_loop.send_frame(fresh_image)

        if _is_camera_question(text, audio_loop):
            print("[SERVER DEBUG] Handling typed camera question with direct vision inspection.")
            camera_result = await audio_loop.inspect_camera_view(text)
            await sio.emit('transcription', {'sender': 'JARVIS', 'text': camera_result, 'append': False})
            if audio_loop.project_manager:
                audio_loop.project_manager.log_chat("JARVIS", camera_result)
            try:
                await audio_loop.session.send(
                    input=(
                        "System Notification: The user asked a camera/vision question. "
                        "The app answered directly using the current webcam frame, so do not answer this again. "
                        f"Question: {text}\nAnswer: {camera_result}"
                    ),
                    end_of_turn=False
                )
            except Exception as e:
                print(f"[SERVER DEBUG] Failed to sync camera answer to live session: {e}")
            print("[SERVER DEBUG] Camera analysis emitted directly to frontend.")
            return

        await audio_loop.session.send(input=text, end_of_turn=True)
        print(f"[SERVER DEBUG] Message sent to model successfully.")

import json
from datetime import datetime
from pathlib import Path

# ... (imports)

@sio.event
async def video_frame(sid, data):
    # data should contain 'image' which is binary (blob) or base64 encoded
    image_data = data.get('image')
    if image_data and audio_loop:
        # We don't await this because we don't want to block the socket handler
        # But send_frame is async, so we create a task
        asyncio.create_task(audio_loop.send_frame(image_data))

@sio.event
async def video_stopped(sid):
    if audio_loop:
        audio_loop.clear_webcam_frame()

@sio.event
async def save_memory(sid, data):
    try:
        messages = data.get('messages', [])
        if not messages:
            print("No messages to save.")
            return

        # Ensure directory exists
        memory_dir = Path("long_term_memory")
        memory_dir.mkdir(exist_ok=True)

        # Generate filename
        # Use provided filename if available, else timestamp
        provided_name = data.get('filename')
        
        if provided_name:
            # Simple sanitization
            if not provided_name.endswith('.txt'):
                provided_name += '.txt'
            # Prevent directory traversal
            filename = memory_dir / Path(provided_name).name 
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = memory_dir / f"memory_{timestamp}.txt"

        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            for msg in messages:
                sender = msg.get('sender', 'Unknown')
                text = msg.get('text', '')
        print(f"Conversation saved to {filename}")
        await sio.emit('status', {'msg': 'Memory Saved Successfully'})

    except Exception as e:
        print(f"Error saving memory: {e}")
        await sio.emit('error', {'msg': f"Failed to save memory: {str(e)}"})

@sio.event
async def upload_memory(sid, data):
    print(f"Received memory upload request")
    try:
        memory_text = data.get('memory', '')
        if not memory_text:
            print("No memory data provided.")
            return

        if not audio_loop:
             print("[SERVER DEBUG] [Error] Audio loop is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (Audio Loop inactive)"})
             return
        
        if not audio_loop.session:
             print("[SERVER DEBUG] [Error] Session is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (No active session)"})
             return

        # Send to model
        print("Sending memory context to model...")
        context_msg = f"System Notification: The user has uploaded a long-term memory file. Please load the following context into your understanding. The format is a text log of previous conversations:\n\n{memory_text}"
        
        await audio_loop.session.send(input=context_msg, end_of_turn=True)
        print("Memory context sent successfully.")
        await sio.emit('status', {'msg': 'Memory Loaded into Context'})

    except Exception as e:
        print(f"Error uploading memory: {e}")
        await sio.emit('error', {'msg': f"Failed to upload memory: {str(e)}"})

@sio.event
async def discover_kasa(sid):
    print(f"Received discover_kasa request")
    try:
        devices = await kasa_agent.discover_devices()
        await sio.emit('kasa_devices', devices)
        await sio.emit('status', {'msg': f"Found {len(devices)} Kasa devices"})

        if simulation_manager.is_kasa_enabled():
            await emit_simulation_snapshot("Detectados dispositivos Kasa simulados")
            return
        
        # Save to settings
        # devices is a list of full device info dicts. minimizing for storage.
        saved_devices = []
        for d in devices:
            saved_devices.append({
                "ip": d["ip"],
                "alias": d["alias"],
                "model": d["model"]
            })
        
        # Merge with existing to preserve any manual overrides? 
        # For now, just overwrite with latest scan result + previously known if we want to be fancy,
        # but user asked for "Any new devices that are scanned are added there".
        # A simple full persistence of current state is safest.
        SETTINGS["kasa_devices"] = saved_devices
        save_settings()
        print(f"[SERVER] Saved {len(saved_devices)} Kasa devices to settings.")
        
    except Exception as e:
        print(f"Error discovering kasa: {e}")
        await sio.emit('error', {'msg': f"Kasa Discovery Failed: {str(e)}"})

@sio.event
async def iterate_cad(sid, data):
    # data: { prompt: "make it bigger" }
    prompt = data.get('prompt')
    print(f"Received iterate_cad request: '{prompt}'")
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        # Notify user work has started
        await sio.emit('status', {'msg': 'Iterating design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Call the agent with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.iterate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending updated CAD data: {info}")
            await sio.emit('cad_data', result)
            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved iterated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design updated'})
        else:
            await sio.emit('error', {'msg': 'Failed to update design'})
            
    except Exception as e:
        print(f"Error iterating CAD: {e}")
        await sio.emit('error', {'msg': f"Iteration Error: {str(e)}"})

@sio.event
async def generate_cad(sid, data):
    # data: { prompt: "make a cube" }
    prompt = data.get('prompt')
    print(f"Received generate_cad request: '{prompt}'")
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Generating new design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Use generate_prototype based on prompt with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending newly generated CAD data: {info}")
            await sio.emit('cad_data', result)


            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved generated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design generated'})
        else:
            await sio.emit('error', {'msg': 'Failed to generate design'})
            
    except Exception as e:
        print(f"Error generating CAD: {e}")
        await sio.emit('error', {'msg': f"Generation Error: {str(e)}"})

@sio.event
async def prompt_web_agent(sid, data):
    # data: { prompt: "find xyz" }
    prompt = data.get('prompt')
    print(f"Received web agent prompt: '{prompt}'")
    
    if not audio_loop or not audio_loop.web_agent:
        await sio.emit('error', {'msg': "Web Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Web Agent running...'})

        async def on_web_update(image_b64, log_text):
            await sio.emit('browser_frame', {'image': image_b64, 'log': log_text})

        result = await audio_loop.web_agent.run_task(prompt, update_callback=on_web_update)
        await sio.emit('browser_frame', {'image': None, 'log': result})
        if getattr(audio_loop, "session", None):
            try:
                await audio_loop.session.send(
                    input=f"System Notification: Web Agent has finished.\nPrompt: {prompt}\nResult: {result}",
                    end_of_turn=False,
                )
            except Exception as exc:
                print(f"[SERVER] Could not attach Web Agent result to live session: {exc}")
        if getattr(audio_loop, "project_manager", None):
            audio_loop.project_manager.log_chat("System", f"Web Agent result for '{prompt}': {result}")
        await sio.emit('status', {'msg': 'Web Agent finished'})
        
    except Exception as e:
        print(f"Error running Web Agent: {e}")
        await sio.emit('error', {'msg': f"Web Agent Error: {str(e)}"})

@sio.event
async def discover_printers(sid):
    print("Received discover_printers request")

    if simulation_manager.is_printer_enabled():
        printers = await printer_simulator.discover_printers()
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Found {len(printers)} demo printers"})
        await emit_simulation_snapshot("Detectadas impresoras simuladas")
        return
    
    # If audio_loop isn't ready yet, return saved printers from settings
    if not audio_loop or not audio_loop.printer_agent:
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers:
            # Convert saved printers to the expected format
            printer_list = []
            for p in saved_printers:
                printer_list.append({
                    "name": p.get("name", p["host"]),
                    "host": p["host"],
                    "port": p.get("port", 80),
                    "printer_type": p.get("type", "unknown"),
                    "camera_url": p.get("camera_url")
                })
            print(f"[SERVER] Returning {len(printer_list)} saved printers (audio_loop not ready)")
            await sio.emit('printer_list', printer_list)
            return
        else:
            await sio.emit('printer_list', [])
            await sio.emit('status', {'msg': "Connect to J.A.R.V.I.S to enable printer discovery"})
            return
        
    try:
        printers = await audio_loop.printer_agent.discover_printers()
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Found {len(printers)} printers"})
        if simulation_manager.is_printer_enabled():
            await emit_simulation_snapshot("Detectadas impresoras simuladas")
    except Exception as e:
        print(f"Error discovering printers: {e}")
        await sio.emit('error', {'msg': f"Printer Discovery Failed: {str(e)}"})

@sio.event
async def add_printer(sid, data):
    # data: { host: "192.168.1.50", name: "My Printer", type: "moonraker" }
    raw_host = data.get('host')
    name = data.get('name') or raw_host
    ptype = data.get('type', "moonraker")
    
    # Parse port if present
    if ":" in raw_host:
        host, port_str = raw_host.split(":")
        port = int(port_str)
    else:
        host = raw_host
        port = 80
    
    print(f"Received add_printer request: {host}:{port} ({ptype})")
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        # Add manually
        camera_url = data.get('camera_url')
        api_key = data.get('api_key')
        printer = audio_loop.printer_agent.add_printer_manually(
            name,
            host,
            port=port,
            printer_type=ptype,
            api_key=api_key,
            camera_url=camera_url
        )
        
        # Probe to confirm/correct type
        print(f"Probing {host} to confirm type...")
        # Try port 7125 (Moonraker) and 4408 (Fluidd/K1) 
        ports_to_try = []
        for candidate_port in [port, 80, 7125, 4408]:
            if candidate_port not in ports_to_try:
                ports_to_try.append(candidate_port)

        actual_type = None
        for probe_port in ports_to_try:
            found_type = await audio_loop.printer_agent._probe_printer_type(host, probe_port)
            if found_type.value != "unknown":
                actual_type = found_type
                # Update port if different
                if probe_port != printer.port:
                    printer.port = probe_port
                break

        if actual_type and actual_type != printer.printer_type:
            printer.printer_type = actual_type
            print(f"Corrected type to {actual_type.value} on port {printer.port}")

        # Save only after probing so settings persist the final corrected port/type.
        printer_config = _build_printer_settings_config(
            name=name,
            host=host,
            printer=printer,
            camera_url=camera_url,
            api_key=api_key
        )
        action = _upsert_printer_setting(printer_config)
        save_settings()
        print(f"[SERVER] {action.capitalize()} printer {name} in settings: {host}:{printer.port} ({printer_config['type']})")
             
        # Refresh list for everyone
        printers = [p.to_dict() for p in audio_loop.printer_agent.printers.values()]
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Added printer: {name}"})
        
    except Exception as e:
        print(f"Error adding printer: {e}")
        await sio.emit('error', {'msg': f"Failed to add printer: {str(e)}"})

@sio.event
async def print_stl(sid, data):
    print(f"Received print_stl request: {data}")
    # data: { stl_path: "path/to.stl" | "current", printer: "name_or_ip", profile: "optional" }

    if simulation_manager.is_printer_enabled():
        printer_name = data.get('printer')
        if not printer_name:
            await sio.emit('error', {'msg': "No printer specified"})
            return
        filename = os.path.splitext(os.path.basename(data.get('stl_path', 'jarvis_demo_part')))[0] or "jarvis_demo_part"
        if not filename.endswith(".gcode"):
            filename = f"{filename}.gcode"
        status_data = await printer_simulator.start_demo_print(printer_name, filename)
        if not status_data:
            await sio.emit('error', {'msg': f"Demo printer not found: {printer_name}"})
            return
        result = {"status": "success", "success": True, "message": f"Demo print started on {status_data['printer']}."}
        await sio.emit('print_result', result)
        await sio.emit('status', {'msg': result["message"]})
        await emit_simulation_snapshot(result["message"])
        return
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        stl_path = data.get('stl_path', 'current')
        printer_name = data.get('printer')
        profile = data.get('profile')
        
        if not printer_name:
             await sio.emit('error', {'msg': "No printer specified"})
             return
             
        await sio.emit('status', {'msg': f"Preparing print for {printer_name}..."})
        
        # Get current project path for resolution
        current_project_path = None
        if audio_loop and audio_loop.project_manager:
            current_project_path = str(audio_loop.project_manager.get_current_project_path())
            print(f"[SERVER DEBUG] Using project path: {current_project_path}")

        # Resolve STL path before slicing so we can preview it
        resolved_stl = audio_loop.printer_agent._resolve_file_path(stl_path, current_project_path)
        
        if resolved_stl and os.path.exists(resolved_stl):
            # Open the STL in the CAD module for preview
            try:
                import base64
                with open(resolved_stl, 'rb') as f:
                    stl_data = f.read()
                stl_b64 = base64.b64encode(stl_data).decode('utf-8')
                stl_filename = os.path.basename(resolved_stl)
                
                print(f"[SERVER] Opening STL in CAD module: {stl_filename}")
                await sio.emit('cad_data', {
                    'format': 'stl',
                    'data': stl_b64,
                    'filename': stl_filename
                })
            except Exception as e:
                print(f"[SERVER] Warning: Could not preview STL: {e}")
        
        # Progress Callback
        async def on_slicing_progress(percent, message):
            await sio.emit('slicing_progress', {
                'printer': printer_name,
                'percent': percent,
                'message': message
            })
            if percent < 100:
                 await sio.emit('status', {'msg': f"Slicing: {percent}%"})

        result = await audio_loop.printer_agent.print_stl(
            stl_path, 
            printer_name, 
            profile,
            progress_callback=on_slicing_progress,
            root_path=current_project_path
        )
        
        await sio.emit('print_result', result)
        await sio.emit('status', {'msg': f"Print Job: {result.get('status', 'unknown')}"})
        if simulation_manager.is_printer_enabled():
            await emit_simulation_snapshot(result.get("message", "Impresion demo iniciada"))
        
    except Exception as e:
        print(f"Error printing STL: {e}")
        await sio.emit('error', {'msg': f"Print Failed: {str(e)}"})

@sio.event
async def get_slicer_profiles(sid):
    """Get available OrcaSlicer profiles for manual selection."""
    print("Received get_slicer_profiles request")
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
    
    try:
        profiles = audio_loop.printer_agent.get_available_profiles()
        await sio.emit('slicer_profiles', profiles)
    except Exception as e:
        print(f"Error getting slicer profiles: {e}")
        await sio.emit('error', {'msg': f"Failed to get profiles: {str(e)}"})

@sio.event
async def control_kasa(sid, data):
    # data: { ip, action: "on"|"off"|"brightness"|"color", value: ... }
    ip = data.get('ip')
    action = data.get('action')
    print(f"Kasa Control: {ip} -> {action}")
    
    try:
        success = False
        if action == "on":
            success = await kasa_agent.turn_on(ip)
        elif action == "off":
            success = await kasa_agent.turn_off(ip)
        elif action == "brightness":
            val = data.get('value')
            success = await kasa_agent.set_brightness(ip, val)
        elif action == "color":
            # value is {h, s, v} - convert to tuple for set_color
            h = data.get('value', {}).get('h', 0)
            s = data.get('value', {}).get('s', 100)
            v = data.get('value', {}).get('v', 100)
            success = await kasa_agent.set_color(ip, (h, s, v))
        
        if success:
            await sio.emit('kasa_update', {
                'ip': ip,
                'is_on': True if action == "on" else (False if action == "off" else None),
                'brightness': data.get('value') if action == "brightness" else None,
            })
            devices = kasa_agent.get_all_states()
            await sio.emit('kasa_devices', devices)
            await dispatch_automation_event(
                "kasa.device_changed",
                {"ip": ip, "action": action, "value": data.get("value"), "devices": devices},
            )
            if simulation_manager.is_kasa_enabled():
                await emit_simulation_snapshot(kasa_simulator.last_operation_message)
  
        else:
             await sio.emit('error', {'msg': f"Failed to control device {ip}"})

    except Exception as e:
         print(f"Error controlling kasa: {e}")
         await sio.emit('error', {'msg': f"Kasa Control Error: {str(e)}"})

@sio.event
async def get_settings(sid):
    await sio.emit('settings', SETTINGS)

@sio.event
async def update_settings(sid, data):
    # Generic update
    print(f"Updating settings: {data}")
    
    # Handle specific keys if needed
    if "tool_permissions" in data:
        SETTINGS["tool_permissions"].update(data["tool_permissions"])
        if audio_loop:
            audio_loop.update_permissions(SETTINGS["tool_permissions"])
            
    if "face_auth_enabled" in data:
        SETTINGS["face_auth_enabled"] = data["face_auth_enabled"]
        if data["face_auth_enabled"]:
             await require_fresh_face_auth(reload_reference=True)
        else:
             await sio.emit('auth_status', {'authenticated': True})
             if authenticator:
                 authenticator.stop() 

    if "camera_flipped" in data:
        SETTINGS["camera_flipped"] = data["camera_flipped"]
        print(f"[SERVER] Camera flip set to: {data['camera_flipped']}")

    save_settings()
    # Broadcast new full settings
    await sio.emit('settings', SETTINGS)


# Deprecated/Mapped for compatibility if frontend still uses specific events
@sio.event
async def get_tool_permissions(sid):
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def update_tool_permissions(sid, data):
    print(f"Updating permissions (legacy event): {data}")
    SETTINGS["tool_permissions"].update(data)
    save_settings()
    
    if audio_loop:
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
    # Broadcast update to all
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

if __name__ == "__main__":
    uvicorn.run(
        "server:app_socketio", 
        host="127.0.0.1", 
        port=8000, 
        reload=False, # Reload enabled causes spawn of worker which might miss the event loop policy patch
        loop="asyncio",
        reload_excludes=["temp_cad_gen.py", "output.stl", "*.stl"]
    )
