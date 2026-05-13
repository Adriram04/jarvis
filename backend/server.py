import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import socketio
import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import threading
import sys
import os
import json
import time
import unicodedata
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
from authenticator import FaceAuthenticator
from kasa_agent import KasaAgent
from simulation_manager import simulation_manager
from simulators.kasa_simulator import kasa_simulator
from simulators.printer_simulator import printer_simulator

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
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

def _normalize_text_for_match(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower().strip()

def _is_camera_question(text, loop=None):
    normalized = _normalize_text_for_match(text)
    if any(phrase in normalized for phrase in CAMERA_QUERY_PHRASES):
        return True

    if normalized in CAMERA_FOLLOWUP_PHRASES and loop:
        last_camera_question_at = getattr(loop, "_last_camera_question_at", None)
        if last_camera_question_at and (time.time() - last_camera_question_at) < 120:
            return True

    return False

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
SETTINGS_FILE = BACKEND_DIR / "settings.json"
REFERENCE_IMAGE_FILE = BACKEND_DIR / "reference.jpg"

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
        "get_simulation_status": False
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

@app.on_event("startup")
async def startup_event():
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

@app.get("/status")
async def status():
    return {"status": "running", "service": "J.A.R.V.I.S Backend"}

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


async def monitor_printers_loop():
    """Background task to query printer status periodically."""
    print("[SERVER] Starting Printer Monitor Loop")
    while audio_loop and audio_loop.printer_agent:
        try:
            if simulation_manager.is_printer_enabled():
                for status_data in printer_simulator.get_all_printer_states():
                    await sio.emit('print_status_update', status_data)
                await emit_simulation_snapshot()
                await asyncio.sleep(2)
                continue

            agent = audio_loop.printer_agent
            if not agent.printers:
                await asyncio.sleep(5)
                continue
                
            tasks = []
            for host, printer in agent.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(agent.get_print_status(host))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        pass # Ignore errors for now
                    elif res:
                        # res is PrintStatus object
                        await sio.emit('print_status_update', res.to_dict())
                        
        except asyncio.CancelledError:
            print("[SERVER] Printer Monitor Cancelled")
            break
        except Exception as e:
            print(f"[SERVER] Monitor Loop Error: {e}")
            
        await asyncio.sleep(2) # Update every 2 seconds for responsiveness

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
    
    if audio_loop:
        audio_loop.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Audio loop not active, cannot resolve confirmation.")

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
        await sio.emit('transcription', {'sender': 'JARVIS', 'text': message})
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("JARVIS", message)
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
            await sio.emit('transcription', {'sender': 'JARVIS', 'text': camera_result})
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
