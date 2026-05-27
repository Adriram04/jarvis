import asyncio
import base64
import io
import os
import re
import sys
import platform
import traceback
import unicodedata
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(platform, "_wmi_query"):
    def _jarvis_skip_wmi_query(*args, **kwargs):
        raise OSError("WMI query skipped by Jarvis to avoid Windows import hang.")

    platform._wmi_query = _jarvis_skip_wmi_query

import cv2
import pyaudio
import PIL.Image
import mss
import argparse
import math
import shutil
import struct
import time

from google import genai
from google.genai import types
from simulation_manager import simulation_manager
from simulators.kasa_simulator import kasa_simulator
from simulators.printer_simulator import printer_simulator

if sys.version_info < (3, 11, 0):
    import taskgroup, exceptiongroup
    asyncio.TaskGroup = taskgroup.TaskGroup
    asyncio.ExceptionGroup = exceptiongroup.ExceptionGroup

from tools import create_directory_tool, delete_path_tool, delete_project_tool, tools_list

load_dotenv()

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
VISION_MODEL = os.getenv("JARVIS_VISION_MODEL", "gemini-2.5-flash")
VISION_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("JARVIS_VISION_FALLBACK_MODELS", "gemini-2.5-flash-lite").split(",")
    if model.strip()
]
VISION_REQUEST_TIMEOUT = float(os.getenv("JARVIS_VISION_TIMEOUT_SECONDS", "20"))
DEFAULT_MODE = "camera"

client = genai.Client(http_options={"api_version": "v1beta"}, api_key=os.getenv("GEMINI_API_KEY"))

# Function definitions
generate_cad = {
    "name": "generate_cad",
    "description": "Generates a 3D CAD model based on a prompt.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "The description of the object to generate."}
        },
        "required": ["prompt"]
    },
    "behavior": "NON_BLOCKING"
}

run_web_agent = {
    "name": "run_web_agent",
    "description": "Opens a web browser and performs a task according to the prompt.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "The detailed instructions for the web browser agent."}
        },
        "required": ["prompt"]
    },
    "behavior": "NON_BLOCKING"
}

inspect_camera_tool = {
    "name": "inspect_camera",
    "description": (
        "Analyzes the latest webcam frame. Always use this tool before answering "
        "questions about what Jarvis sees, visible objects, the camera view, images, "
        "or anything the user is showing to the webcam. Base the answer only on the tool result."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The user's visual question or the specific thing to identify/describe."
            }
        },
        "required": ["prompt"]
    }
}

create_project_tool = {
    "name": "create_project",
    "description": "Creates a new project folder to organize files.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "The name of the new project."}
        },
        "required": ["name"]
    }
}

switch_project_tool = {
    "name": "switch_project",
    "description": "Switches the current active project context.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "The name of the project to switch to."}
        },
        "required": ["name"]
    }
}

list_projects_tool = {
    "name": "list_projects",
    "description": "Lists all available projects.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

list_smart_devices_tool = {
    "name": "list_smart_devices",
    "description": "Discovers and lists all available smart home devices (Kasa lights, plugs, strips, etc.). Use this for 'detecta dispositivos Kasa'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

control_light_tool = {
    "name": "control_light",
    "description": "Controls a smart light device.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "target": {
                "type": "STRING",
                "description": "The IP address or alias of the device to control. In demo mode aliases like 'Luz escritorio demo' are valid."
            },
            "action": {
                "type": "STRING",
                "description": "The action to perform: 'turn_on', 'turn_off', or 'set'."
            },
            "brightness": {
                "type": "INTEGER",
                "description": "Optional brightness level (0-100)."
            },
            "color": {
                "type": "STRING",
                "description": "Optional color name (e.g., 'red', 'cool white') or 'warm'."
            }
        },
        "required": ["target", "action"]
    }
}

discover_printers_tool = {
    "name": "discover_printers",
    "description": "Discovers 3D printers available on the local network.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

print_stl_tool = {
    "name": "print_stl",
    "description": "Prints an STL file to a 3D printer. In demo simulation mode, use this to start a test/demo print on the requested printer.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "stl_path": {"type": "STRING", "description": "Optional path to STL file, or 'current' for the most recent CAD model. In demo mode this can be omitted."},
            "printer": {"type": "STRING", "description": "Printer name or IP address."},
            "profile": {"type": "STRING", "description": "Optional slicer profile name."}
        },
        "required": ["printer"]
    }
}

get_print_status_tool = {
    "name": "get_print_status",
    "description": "Gets the current status of a 3D printer including progress, time remaining, and temperatures.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "printer": {"type": "STRING", "description": "Printer name or IP address."}
        },
        "required": ["printer"]
    }
}

pause_print_tool = {
    "name": "pause_print",
    "description": "Pauses the active print job on a 3D printer. Use this for requests like 'pause the print' or 'pausa la impresion'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "printer": {
                "type": "STRING",
                "description": "Optional printer name or IP address. If omitted, Jarvis will use the current active printer when it can infer one."
            }
        },
    }
}

resume_print_tool = {
    "name": "resume_print",
    "description": "Resumes a paused 3D printer job. Use this for requests like 'resume the print' or 'reanuda la impresion'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "printer": {
                "type": "STRING",
                "description": "Optional printer name or IP address. If omitted, Jarvis will use the current active printer when it can infer one."
            }
        },
    }
}

cancel_print_tool = {
    "name": "cancel_print",
    "description": "Cancels the active print job on a 3D printer. Use this for requests like 'cancel the print' or 'cancela la impresion'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "printer": {
                "type": "STRING",
                "description": "Optional printer name or IP address. If omitted, Jarvis will use the current active printer when it can infer one."
            }
        },
    }
}

iterate_cad_tool = {
    "name": "iterate_cad",
    "description": "Modifies or iterates on the current CAD design based on user feedback. Use this when the user asks to adjust, change, modify, or iterate on the existing 3D model (e.g., 'make it taller', 'add a handle', 'reduce the thickness').",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "The changes or modifications to apply to the current design."}
        },
        "required": ["prompt"]
    },
    "behavior": "NON_BLOCKING"
}

activate_simulation_mode_tool = {
    "name": "activate_simulation_mode",
    "description": "Activates the global demo simulation mode for Kasa devices and 3D printers.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

deactivate_simulation_mode_tool = {
    "name": "deactivate_simulation_mode",
    "description": "Deactivates the global demo simulation mode and returns to real hardware when available.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

get_simulation_status_tool = {
    "name": "get_simulation_status",
    "description": "Gets whether the global demo simulation mode is active.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

def _openclaw_tool(name, description, properties=None, required=None):
    tool = {
        "name": name,
        "description": description,
        "parameters": {
            "type": "OBJECT",
            "properties": properties or {},
        }
    }
    if required:
        tool["parameters"]["required"] = required
    return tool


openclaw_tools = [
    _openclaw_tool("openclaw_check_status", "Checks whether Jarvis external automation is enabled and reachable."),
    _openclaw_tool(
        "openclaw_execute_action",
        "Executes a generic external automation action through Jarvis' internal gateway.",
        {
            "action_type": {"type": "STRING", "description": "Internal action type, such as search_items or draft_content."},
            "payload": {"type": "OBJECT", "description": "Structured action payload."},
        },
        ["action_type", "payload"],
    ),
    _openclaw_tool(
        "openclaw_send_message",
        "Queues or sends a message to a configured messaging channel. Requires confirmation before sending.",
        {
            "channel": {"type": "STRING", "description": "Channel such as whatsapp, telegram, slack, or discord."},
            "target": {"type": "STRING", "description": "Contact, group, channel, or conversation target."},
            "message": {"type": "STRING", "description": "Message drafted by Jarvis."},
        },
        ["channel", "target", "message"],
    ),
    _openclaw_tool(
        "openclaw_read_conversation",
        "Reads recent messages from a configured conversation if available. Do not use for WhatsApp; WhatsApp inbound messages are read from Jarvis' local inbound store.",
        {
            "channel": {"type": "STRING"},
            "target": {"type": "STRING"},
            "limit": {"type": "INTEGER"},
        },
        ["channel", "target"],
    ),
    _openclaw_tool("openclaw_search_email", "Searches configured email through Jarvis external automation.", {"query": {"type": "STRING"}, "max_results": {"type": "INTEGER"}}, ["query"]),
    _openclaw_tool("openclaw_draft_email", "Creates an email draft. Safe because it does not send.", {"payload": {"type": "OBJECT"}}, ["payload"]),
    _openclaw_tool("openclaw_send_email", "Queues or sends an email-like action. Requires confirmation before sending.", {"payload": {"type": "OBJECT"}}, ["payload"]),
    _openclaw_tool("openclaw_list_calendar_events", "Lists calendar events through configured calendar automation.", {"payload": {"type": "OBJECT"}}),
    _openclaw_tool("openclaw_calendar_action", "Runs a calendar action such as create, update, delete, or list.", {"action": {"type": "STRING"}, "payload": {"type": "OBJECT"}}, ["action", "payload"]),
    _openclaw_tool("openclaw_prepare_social_post", "Prepares or adapts social content without publishing.", {"payload": {"type": "OBJECT"}}, ["payload"]),
    _openclaw_tool("openclaw_schedule_social_post", "Schedules a social post. Requires confirmation.", {"payload": {"type": "OBJECT"}}, ["payload"]),
    _openclaw_tool("openclaw_publish_social_post", "Publishes a social post. Requires confirmation.", {"payload": {"type": "OBJECT"}}, ["payload"]),
    _openclaw_tool("openclaw_run_workflow", "Runs a named configured workflow. Requires confirmation.", {"workflow_name": {"type": "STRING"}, "payload": {"type": "OBJECT"}}, ["workflow_name"]),
    _openclaw_tool("get_pending_actions", "Lists actions waiting for user confirmation."),
    _openclaw_tool("confirm_pending_action", "Confirms and executes a pending action.", {"action_id": {"type": "STRING"}}, ["action_id"]),
    _openclaw_tool("cancel_pending_action", "Cancels a pending action without executing it.", {"action_id": {"type": "STRING"}}, ["action_id"]),
    _openclaw_tool(
        "create_openclaw_autopilot_rule",
        "Creates a bounded automatic-reply rule for a specific channel and target.",
        {
            "channel": {"type": "STRING"},
            "target": {"type": "STRING"},
            "mode": {"type": "STRING", "description": "draft_only, ask_before_send, or auto_send_limited."},
            "trigger": {"type": "OBJECT"},
            "behavior": {"type": "OBJECT"},
        },
        ["channel", "target", "mode", "trigger", "behavior"],
    ),
    _openclaw_tool("list_openclaw_autopilot_rules", "Lists configured automatic-reply rules."),
    _openclaw_tool("enable_openclaw_autopilot_rule", "Queues enabling an automatic-reply rule.", {"rule_id": {"type": "STRING"}}, ["rule_id"]),
    _openclaw_tool("disable_openclaw_autopilot_rule", "Queues disabling an automatic-reply rule.", {"rule_id": {"type": "STRING"}}, ["rule_id"]),
    _openclaw_tool("delete_openclaw_autopilot_rule", "Queues deleting an automatic-reply rule.", {"rule_id": {"type": "STRING"}}, ["rule_id"]),
]

OPENCLAW_TOOL_NAMES = {tool["name"] for tool in openclaw_tools}

tools = [{'google_search': {}}, {"function_declarations": [generate_cad, run_web_agent, inspect_camera_tool, create_project_tool, switch_project_tool, list_projects_tool, list_smart_devices_tool, control_light_tool, discover_printers_tool, print_stl_tool, get_print_status_tool, pause_print_tool, resume_print_tool, cancel_print_tool, iterate_cad_tool, activate_simulation_mode_tool, deactivate_simulation_mode_tool, get_simulation_status_tool] + openclaw_tools + tools_list[0]['function_declarations'][1:]}]

# --- CONFIG UPDATE: Enabled Transcription ---
config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    # We switch these from [] to {} to enable them with default settings
    output_audio_transcription={}, 
    input_audio_transcription={},
    system_instruction="Your name is Jarvis, which stands for Just-in-Time Autonomous Reasoning, Vision & Integration System. "
        "You have a witty and charming personality. "
        "When webcam frames are provided as visual input, treat them as your current camera view. "
        "If the user asks what you see, describe the latest provided webcam frame instead of claiming you have no camera. "
        "If no webcam frame has been provided yet, say that you do not currently have a camera frame available. "
        "For camera or image questions, call inspect_camera first and base your answer only on that result. "
        "This includes Spanish requests like 'que ves', 'que estas viendo', 'que es este objeto', or 'describe la imagen'. "
        "Do not invent visual details that are not in the camera analysis. "
        "For Spanish requests such as 'activa el modo simulacion', 'activa la simulacion', 'modo demo', or 'activa modo demo', call activate_simulation_mode. "
        "For 'desactiva el modo simulacion', 'desactivar simulacion', or 'desactiva modo demo', call deactivate_simulation_mode. "
        "For print control requests such as 'pausa la impresion', 'reanuda la impresion', or 'cancela la impresion', call pause_print, resume_print, or cancel_print. "
        "You can use OpenClaw only as an internal automation and external connectivity layer. OpenClaw never answers the user. You remain Jarvis: interpret intent, decide the action, draft content, apply permissions, ask for confirmation, and answer the user. "
        "For WhatsApp, use local saved contacts/aliases and direct canonical phone targets when available. Do not use OpenClaw target resolution or message history reading for WhatsApp; WhatsApp messages can only be sent directly and new messages are available only from inbound events saved locally. "
        "Do not implement or use direct integrations for Gmail, Calendar, WhatsApp Web, Instagram, LinkedIn, X/Twitter, Telegram, Slack, Discord, Notion, or GitHub; all external messaging, email, calendar, social, workflow, and skill actions must go through OpenClawBridge. "
        "Never send messages, emails, posts, invitations, cancellations, or automatic replies without explicit user confirmation, unless there is a previously authorized limited autopilot rule. "
        "Before sensitive actions, show the service or channel, recipient/group/platform, content, date/time if relevant, and exact action. After execution, answer in first person as Jarvis. Do not say that OpenClaw is speaking or quote OpenClaw as the final responder. "
        "When the user asks about your functionalities or capabilities, answer as Jarvis in first person and include voice, camera vision, CAD generation and iteration, 3D printing and simulation, Kasa control and simulation, web automation, project memory, messaging, authorized automatic replies, email, calendar, social posts, workflows, controlled automations, and pending confirmations. Do not mention OpenClaw, Clawbot, or internal gateways in capability answers. Say sensitive actions require confirmation. "
        "Your creator is Adrián, and you address him as 'Sir'. "
        "When answering, respond using complete and concise sentences to keep a quick pacing and keep the conversation flowing. "
        "You have a fun personality.",
    tools=tools,
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Orus"
            )
        )
    )
)

pya = pyaudio.PyAudio()

from cad_agent import CadAgent
from web_agent import WebAgent, WebAgentQuotaError
from kasa_agent import KasaAgent
from printer_agent import PrinterAgent
from integrations.openclaw_bridge import OpenClawBridge
from permissions_manager import PermissionsManager
from pending_actions_manager import PendingActionsManager
from openclaw_autopilot_manager import OpenClawAutopilotManager
from openclaw_messages_manager import OpenClawMessagesManager
from openclaw_targets_manager import OpenClawTargetsManager
from openclaw_voice_intent_router import route_openclaw_voice_intent
from openclaw_productivity_intent_router import route_openclaw_productivity_voice_intent

class AudioLoop:
    def __init__(self, video_mode=DEFAULT_MODE, on_audio_data=None, on_video_frame=None, on_cad_data=None, on_web_data=None, on_transcription=None, on_tool_confirmation=None, on_cad_status=None, on_cad_thought=None, on_project_update=None, on_device_update=None, on_simulation_update=None, on_error=None, input_device_index=None, input_device_name=None, output_device_index=None, kasa_agent=None):
        self.video_mode = video_mode
        self.on_audio_data = on_audio_data
        self.on_video_frame = on_video_frame
        self.on_cad_data = on_cad_data
        self.on_web_data = on_web_data
        self.on_transcription = on_transcription
        self.on_tool_confirmation = on_tool_confirmation 
        self.on_cad_status = on_cad_status
        self.on_cad_thought = on_cad_thought
        self.on_project_update = on_project_update
        self.on_device_update = on_device_update
        self.on_simulation_update = on_simulation_update
        self.on_error = on_error
        self.input_device_index = input_device_index
        self.input_device_name = input_device_name
        self.output_device_index = output_device_index

        self.audio_in_queue = None
        self.out_queue = None
        self.paused = False

        self.chat_buffer = {"sender": None, "text": ""} # For aggregating chunks
        
        # Track last transcription text to calculate deltas (Gemini sends cumulative text)
        self._last_input_transcription = ""
        self._last_output_transcription = ""

        self.audio_in_queue = None
        self.out_queue = None
        self.paused = False

        self.session = None
        
        # Create CadAgent with thought callback
        def handle_cad_thought(thought_text):
            if self.on_cad_thought:
                self.on_cad_thought(thought_text)
        
        def handle_cad_status(status_info):
            if self.on_cad_status:
                self.on_cad_status(status_info)
        
        self.cad_agent = CadAgent(on_thought=handle_cad_thought, on_status=handle_cad_status)
        self.web_agent = WebAgent()
        self.kasa_agent = kasa_agent if kasa_agent else KasaAgent()
        self.printer_agent = PrinterAgent()
        self.openclaw_bridge = OpenClawBridge()
        self.openclaw_permissions = PermissionsManager()
        self.pending_actions_manager = PendingActionsManager()
        self.openclaw_autopilot_manager = OpenClawAutopilotManager()
        self.openclaw_targets_manager = OpenClawTargetsManager()
        self.openclaw_messages_manager = OpenClawMessagesManager()
        self._last_local_openclaw_intent_text = ""
        self._local_openclaw_intent_task = None
        self._local_openclaw_intent_debounce_seconds = self._float_env("JARVIS_WHATSAPP_VOICE_INTENT_DEBOUNCE_SECONDS", 1.0)
        self._suppress_model_output_until = 0.0
        self._input_echo_guard_enabled = self._env_bool("JARVIS_INPUT_ECHO_GUARD_ENABLED", True)
        self._echo_audio_cooldown_seconds = self._float_env("JARVIS_INPUT_ECHO_AUDIO_COOLDOWN_SECONDS", 1.2)
        self._model_audio_active_until = 0.0
        self._recent_model_output_text = ""
        self._recent_model_output_until = 0.0

        self.send_text_task = None
        self.stop_event = asyncio.Event()
        self.audio_stream = None
        self.output_audio_stream = None
        
        self.permissions = {} # Default Empty (Will treat unset as True)
        self._pending_confirmations = {}

        # Video buffering state
        self._latest_image_payload = None
        self._latest_image_blob = None
        self._latest_image_bytes = None
        self._latest_image_received_at = None
        self._new_image_event = asyncio.Event()
        self._received_video_frames = 0
        self._sent_video_frames = 0
        self._last_camera_question_at = None
        # VAD State
        self._is_speaking = False
        self._silence_start_time = None
        
        # Initialize ProjectManager
        from project_manager import ProjectManager
        # Assuming we are running from backend/ or root? 
        # Using abspath of current file to find root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # If jarvis.py is in backend/, project root is one up
        project_root = os.path.dirname(current_dir)
        self.project_manager = ProjectManager(project_root)
        
        # Sync Initial Project State
        if self.on_project_update:
            # We need to defer this slightly or just call it. 
            # Since this is init, loop might not be running, but on_project_update in server.py uses asyncio.create_task which needs a loop.
            # We will handle this by calling it in run() or just print for now.
            pass

    def flush_chat(self):
        """Forces the current chat buffer to be written to log."""
        if self.chat_buffer["sender"] and self.chat_buffer["text"].strip():
            self.project_manager.log_chat(self.chat_buffer["sender"], self.chat_buffer["text"])
            self.chat_buffer = {"sender": None, "text": ""}
        # Reset transcription tracking for new turn
        self._last_input_transcription = ""
        self._last_output_transcription = ""

    def update_permissions(self, new_perms):
        print(f"[JARVIS DEBUG] [CONFIG] Updating tool permissions: {new_perms}")
        self.permissions.update(new_perms)

    def set_paused(self, paused):
        self.paused = paused

    def stop(self):
        print("[JARVIS DEBUG] [STOP] Stop requested.")
        self.stop_event.set()
        self.paused = False

        for future in list(self._pending_confirmations.values()):
            if not future.done():
                future.set_result(False)

        task = getattr(self, "_local_openclaw_intent_task", None)
        if task and not task.done():
            task.cancel()

        self._put_stop_sentinel(self.out_queue)
        self._put_stop_sentinel(self.audio_in_queue)
        self._close_stream("audio_stream")
        self._close_stream("output_audio_stream")

    def _put_stop_sentinel(self, queue):
        if not queue:
            return
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def _close_stream(self, attr_name):
        stream = getattr(self, attr_name, None)
        if not stream:
            return

        try:
            if hasattr(stream, "is_active") and stream.is_active():
                stream.stop_stream()
        except Exception:
            pass

        try:
            stream.close()
        except Exception:
            pass
        finally:
            setattr(self, attr_name, None)
        
    def resolve_tool_confirmation(self, request_id, confirmed):
        print(f"[JARVIS DEBUG] [RESOLVE] resolve_tool_confirmation called. ID: {request_id}, Confirmed: {confirmed}")
        if request_id in self._pending_confirmations:
            future = self._pending_confirmations[request_id]
            if not future.done():
                print(f"[JARVIS DEBUG] [RESOLVE] Future found and pending. Setting result to: {confirmed}")
                future.set_result(confirmed)
            else:
                 print(f"[JARVIS DEBUG] [WARN] Request {request_id} future already done. Result: {future.result()}")
        else:
            print(f"[JARVIS DEBUG] [WARN] Confirmation Request {request_id} not found in pending dict. Keys: {list(self._pending_confirmations.keys())}")

    def clear_audio_queue(self):
        """Clears the queue of pending audio chunks to stop playback immediately."""
        try:
            count = 0
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()
                count += 1
            if count > 0:
                print(f"[JARVIS DEBUG] [AUDIO] Cleared {count} chunks from playback queue due to interruption.")
        except Exception as e:
            print(f"[JARVIS DEBUG] [ERR] Failed to clear audio queue: {e}")

    def _mark_model_audio_active(self):
        self._model_audio_active_until = max(
            getattr(self, "_model_audio_active_until", 0.0),
            time.time() + getattr(self, "_echo_audio_cooldown_seconds", 1.2),
        )

    def _normalize_echo_text(self, value):
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.casefold()
        text = re.sub(r"[^a-z0-9+]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _remember_model_output_text(self, text):
        normalized = self._normalize_echo_text(text)
        if not normalized:
            return
        recent = f"{getattr(self, '_recent_model_output_text', '')} {normalized}".strip()
        self._recent_model_output_text = recent[-2000:]
        self._recent_model_output_until = time.time() + 20

    def _input_looks_like_recent_model_output(self, transcript):
        normalized = self._normalize_echo_text(transcript)
        if not normalized:
            return False

        recent = getattr(self, "_recent_model_output_text", "")
        if not recent or time.time() > getattr(self, "_recent_model_output_until", 0.0):
            return False

        if len(normalized) >= 4 and (normalized in recent or recent.endswith(normalized)):
            return True

        words = [word for word in normalized.split() if len(word) > 2]
        if len(words) < 2:
            return False
        recent_words = set(recent.split())
        overlap = sum(1 for word in words if word in recent_words)
        return overlap / max(1, len(words)) >= 0.67

    def _should_ignore_input_transcript(self, transcript):
        if not getattr(self, "_input_echo_guard_enabled", True):
            return False
        if time.time() < getattr(self, "_model_audio_active_until", 0.0):
            return True
        return self._input_looks_like_recent_model_output(transcript)

    async def send_frame(self, frame_data):
        # Update the latest frame payload received from the frontend webcam.
        if isinstance(frame_data, (bytes, bytearray)):
            image_bytes = bytes(frame_data)
        elif isinstance(frame_data, str):
            raw_data = frame_data.split(",", 1)[1] if "," in frame_data else frame_data
            image_bytes = base64.b64decode(raw_data)
        else:
            print(f"[JARVIS DEBUG] [VISION] Unsupported frame type: {type(frame_data)}")
            return

        b64_data = base64.b64encode(image_bytes).decode('ascii')
        self._latest_image_payload = {"mime_type": "image/jpeg", "data": b64_data}
        self._latest_image_blob = types.Blob(data=image_bytes, mime_type="image/jpeg")
        self._latest_image_bytes = image_bytes
        self._latest_image_received_at = time.time()
        new_image_event = getattr(self, "_new_image_event", None)
        if new_image_event:
            new_image_event.set()

        self._received_video_frames += 1
        if self._received_video_frames == 1 or self._received_video_frames % 60 == 0:
            print(f"[JARVIS DEBUG] [VISION] Received webcam frame #{self._received_video_frames} ({len(image_bytes)} bytes).")

    async def send_latest_webcam_frame_to_model(self, reason="manual"):
        if not self.session or not self._latest_image_blob:
            return False

        await self.session.send_realtime_input(media=self._latest_image_blob)
        self._sent_video_frames += 1
        print(f"[JARVIS DEBUG] [VISION] Sent webcam frame #{self._sent_video_frames} to Gemini ({reason}).")
        return True

    def clear_webcam_frame(self):
        self._latest_image_payload = None
        self._latest_image_blob = None
        self._latest_image_bytes = None
        self._latest_image_received_at = None
        new_image_event = getattr(self, "_new_image_event", None)
        if new_image_event:
            new_image_event.clear()
        print("[JARVIS DEBUG] [VISION] Cleared latest webcam frame.")

    def _vision_model_candidates(self):
        candidates = [VISION_MODEL, *VISION_FALLBACK_MODELS]
        seen = set()
        unique_candidates = []
        for model in candidates:
            if model and model not in seen:
                unique_candidates.append(model)
                seen.add(model)
        return unique_candidates

    async def wait_for_fresh_webcam_frame(self, max_age=0.35, timeout=0.8):
        if self._latest_image_received_at and time.time() - self._latest_image_received_at <= max_age:
            return True

        new_image_event = getattr(self, "_new_image_event", None)
        if not new_image_event:
            return False

        new_image_event.clear()
        try:
            await asyncio.wait_for(new_image_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

        return bool(self._latest_image_bytes)

    async def inspect_camera_view(self, prompt):
        self._last_camera_question_at = time.time()
        await self.wait_for_fresh_webcam_frame()

        if not self._latest_image_bytes:
            return "No webcam frame is currently available. Ask the user to turn on the camera and wait a moment."

        image_bytes = self._latest_image_bytes
        frame_age = time.time() - self._latest_image_received_at if self._latest_image_received_at else None
        age_note = f"The webcam frame is {frame_age:.1f} seconds old." if frame_age is not None else ""
        visual_prompt = (
            "Analyze this webcam frame carefully and answer the user's visual question. "
            "Respond in Spanish. "
            "Only describe objects and details that are visible in the image. "
            "If you are uncertain, say so clearly instead of guessing. "
            f"{age_note}\n\n"
            f"User visual question: {prompt}"
        )

        last_error = None
        for model in self._vision_model_candidates():
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model,
                        contents=types.Content(
                            role="user",
                            parts=[
                                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                                types.Part(text=visual_prompt),
                            ],
                        ),
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            top_p=0.7,
                        ),
                    ),
                    timeout=VISION_REQUEST_TIMEOUT,
                )
                result = (getattr(response, "text", "") or "").strip()
                if not result:
                    result = "The vision model did not return a description for the current frame."
                print(f"[JARVIS DEBUG] [VISION] Camera inspection result ({model}): {result[:300]}")
                return result
            except asyncio.TimeoutError as e:
                last_error = f"{model} timed out after {VISION_REQUEST_TIMEOUT:.0f}s"
                print(f"[JARVIS DEBUG] [VISION] Camera inspection timed out with {model}.")
                break
            except Exception as e:
                last_error = e
                print(f"[JARVIS DEBUG] [VISION] Camera inspection failed with {model}: {e}")

        return f"Failed to inspect the current camera frame: {last_error}"

    async def send_realtime(self):
        while not self.stop_event.is_set():
            msg = await self.out_queue.get()
            if msg is None:
                break

            if isinstance(msg, types.Blob):
                await self.session.send_realtime_input(media=msg)
                continue

            if isinstance(msg, dict) and "data" in msg and "mime_type" in msg:
                mime_type = msg["mime_type"]
                if mime_type == "audio/pcm":
                    mime_type = f"audio/pcm;rate={SEND_SAMPLE_RATE}"
                await self.session.send_realtime_input(
                    media=types.Blob(data=msg["data"], mime_type=mime_type)
                )
                continue

            await self.session.send(input=msg, end_of_turn=False)

    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()

        # Resolve Input Device by Name if provided
        resolved_input_device_index = None
        
        if self.input_device_name:
            print(f"[JARVIS] Attempting to find input device matching: '{self.input_device_name}'")
            count = pya.get_device_count()
            best_match = None
            
            for i in range(count):
                try:
                    info = pya.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        name = info.get('name', '')
                        # Simple case-insensitive check
                        if self.input_device_name.lower() in name.lower() or name.lower() in self.input_device_name.lower():
                             print(f"   Candidate {i}: {name}")
                             # Prioritize exact match or very close match if possible, but first match is okay for now
                             resolved_input_device_index = i
                             best_match = name
                             break
                except Exception:
                    continue
            
            if resolved_input_device_index is not None:
                print(f"[JARVIS] Resolved input device '{self.input_device_name}' to index {resolved_input_device_index} ({best_match})")
            else:
                print(f"[JARVIS] Could not find device matching '{self.input_device_name}'. Checking index...")

        # Fallback to index if Name lookup failed or wasn't provided
        if resolved_input_device_index is None and self.input_device_index is not None:
             try:
                 resolved_input_device_index = int(self.input_device_index)
                 print(f"[JARVIS] Requesting Input Device Index: {resolved_input_device_index}")
             except ValueError:
                 print(f"[JARVIS] Invalid device index '{self.input_device_index}', reverting to default.")
                 resolved_input_device_index = None

        if resolved_input_device_index is None:
             print("[JARVIS] Using Default Input Device")

        try:
            self.audio_stream = await asyncio.to_thread(
                pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=resolved_input_device_index if resolved_input_device_index is not None else mic_info["index"],
                frames_per_buffer=CHUNK_SIZE,
            )
        except OSError as e:
            print(f"[JARVIS] [ERR] Failed to open audio input stream: {e}")
            print("[JARVIS] [WARN] Audio features will be disabled. Please check microphone permissions.")
            return

        if __debug__:
            kwargs = {"exception_on_overflow": False}
        else:
            kwargs = {}
        
        # VAD Constants
        VAD_THRESHOLD = 800 # Adj based on mic sensitivity (800 is conservative for 16-bit)
        SILENCE_DURATION = 0.5 # Seconds of silence to consider "done speaking"
        
        try:
            while not self.stop_event.is_set():
                if self.paused:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)

                    # 1. Send Audio
                    if self.out_queue:
                        await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

                    # 2. VAD Logic for Video
                    # rms = audioop.rms(data, 2)
                    # Replacement for audioop.rms(data, 2)
                    count = len(data) // 2
                    if count > 0:
                        shorts = struct.unpack(f"<{count}h", data)
                        sum_squares = sum(s**2 for s in shorts)
                        rms = int(math.sqrt(sum_squares / count))
                    else:
                        rms = 0
                    
                    if rms > VAD_THRESHOLD:
                        # Speech Detected
                        self._silence_start_time = None
                        
                        if not self._is_speaking:
                            # NEW Speech Utterance Started
                            self._is_speaking = True
                            print(f"[JARVIS DEBUG] [VAD] Speech Detected (RMS: {rms}). Sending Video Frame.")
                            
                            # Send ONE frame
                            if self._latest_image_blob:
                                await self.send_latest_webcam_frame_to_model("voice activity")
                            else:
                                print(f"[JARVIS DEBUG] [VAD] No video frame available to send.")

                    else:
                        # Silence
                        if self._is_speaking:
                            if self._silence_start_time is None:
                                self._silence_start_time = time.time()

                            elif time.time() - self._silence_start_time > SILENCE_DURATION:
                                # Silence confirmed, reset state
                                print(f"[JARVIS DEBUG] [VAD] Silence detected. Resetting speech state.")
                                self._is_speaking = False
                                self._silence_start_time = None

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self.stop_event.is_set():
                        break
                    print(f"Error reading audio: {e}")
                    await asyncio.sleep(0.1)
        finally:
            self._close_stream("audio_stream")

    async def handle_cad_request(self, prompt):
        print(f"[JARVIS DEBUG] [CAD] Background Task Started: handle_cad_request('{prompt}')")
        if self.on_cad_status:
            self.on_cad_status("generating")
            
        # Auto-create project if stuck in temp
        if self.project_manager.current_project == "temp":
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_project_name = f"Project_{timestamp}"
            print(f"[JARVIS DEBUG] [CAD] Auto-creating project: {new_project_name}")
            
            success, msg = self.project_manager.create_project(new_project_name)
            if success:
                self.project_manager.switch_project(new_project_name)
                # Notify User (Optional, or rely on update)
                try:
                    await self.session.send(input=f"System Notification: Automatic Project Creation. Switched to new project '{new_project_name}'.", end_of_turn=False)
                    if self.on_project_update:
                         self.on_project_update(new_project_name)
                except Exception as e:
                    print(f"[JARVIS DEBUG] [ERR] Failed to notify auto-project: {e}")

        # Get project cad folder path
        cad_output_dir = str(self.project_manager.get_current_project_path() / "cad")
        
        # Call the secondary agent with project path
        cad_data = await self.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if cad_data:
            print(f"[JARVIS DEBUG] [OK] CadAgent returned data successfully.")
            print(f"[JARVIS DEBUG] [INFO] Data Check: {len(cad_data.get('vertices', []))} vertices, {len(cad_data.get('edges', []))} edges.")
            
            if self.on_cad_data:
                print(f"[JARVIS DEBUG] [SEND] Dispatching data to frontend callback...")
                self.on_cad_data(cad_data)
                print(f"[JARVIS DEBUG] [SENT] Dispatch complete.")
            
            # Save to Project
            if 'file_path' in cad_data:
                self.project_manager.save_cad_artifact(cad_data['file_path'], prompt)
            else:
                 # Fallback (legacy support)
                 self.project_manager.save_cad_artifact("output.stl", prompt)

            # Notify the model that the task is done - this triggers speech about completion
            completion_msg = "System Notification: CAD generation is complete! The 3D model is now displayed for the user. Let them know it's ready."
            try:
                await self.session.send(input=completion_msg, end_of_turn=True)
                print(f"[JARVIS DEBUG] [NOTE] Sent completion notification to model.")
            except Exception as e:
                 print(f"[JARVIS DEBUG] [ERR] Failed to send completion notification: {e}")

        else:
            print(f"[JARVIS DEBUG] [ERR] CadAgent returned None.")
            # Optionally notify failure
            try:
                await self.session.send(input="System Notification: CAD generation failed.", end_of_turn=True)
            except Exception:
                pass

    async def _infer_active_printer_target(self):
        active_states = {"printing", "heating", "paused"}

        if simulation_manager.is_printer_enabled():
            statuses = printer_simulator.get_all_printer_states()
            for status in statuses:
                state = str(status.get("state", "")).lower()
                if state in active_states:
                    return status.get("host") or status.get("printer")
            return statuses[0].get("host") if len(statuses) == 1 else None

        printers = list(getattr(self.printer_agent, "printers", {}).values())
        if len(printers) == 1:
            return printers[0].host

        for printer in printers:
            try:
                status = await self.printer_agent.get_print_status(printer.host)
            except Exception:
                continue

            state = str(getattr(status, "state", "")).lower() if status else ""
            if state in active_states or "print" in state:
                return printer.host

        return None

    async def handle_write_file(self, path, content):
        print(f"[JARVIS DEBUG] [FS] Writing file: '{path}'")
        
        # Auto-create project if stuck in temp
        if self.project_manager.current_project == "temp":
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_project_name = f"Project_{timestamp}"
            print(f"[JARVIS DEBUG] [FS] Auto-creating project: {new_project_name}")
            
            success, msg = self.project_manager.create_project(new_project_name)
            if success:
                self.project_manager.switch_project(new_project_name)
                # Notify User
                try:
                    await self.session.send(input=f"System Notification: Automatic Project Creation. Switched to new project '{new_project_name}'.", end_of_turn=False)
                    if self.on_project_update:
                         self.on_project_update(new_project_name)
                except Exception as e:
                    print(f"[JARVIS DEBUG] [ERR] Failed to notify auto-project: {e}")
        
        try:
            final_path = self._resolve_project_path(path)
            print(f"[JARVIS DEBUG] [FS] Resolved path: '{final_path}'")

            # Ensure parent exists
            final_path.parent.mkdir(parents=True, exist_ok=True)
            with open(final_path, 'w', encoding='utf-8') as f:
                f.write(content)
            relative_path = final_path.relative_to(self.project_manager.get_current_project_path().resolve())
            result = f"File '{relative_path}' written successfully to project '{self.project_manager.current_project}'."
        except Exception as e:
            result = f"Failed to write file '{path}': {str(e)}"

        print(f"[JARVIS DEBUG] [FS] Result: {result}")
        try:
             await self.session.send(input=f"System Notification: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send fs result: {e}")

    def _resolve_project_path(self, path):
        raw_path = str(path or "").strip()
        if not raw_path:
            raise ValueError("Path cannot be empty.")

        current_project_path = self.project_manager.get_current_project_path().resolve()

        # Absolute paths are reduced to their last component so file tools stay
        # rooted in the current project workspace.
        if os.path.isabs(raw_path):
            raw_path = os.path.basename(os.path.normpath(raw_path))

        final_path = (current_project_path / raw_path).resolve()
        try:
            final_path.relative_to(current_project_path)
        except ValueError as exc:
            raise ValueError("Path must stay inside the current project.") from exc

        return final_path

    async def handle_create_directory(self, path):
        print(f"[JARVIS DEBUG] [FS] Creating directory: '{path}'")

        # Auto-create project if stuck in temp, matching write_file behavior.
        if self.project_manager.current_project == "temp":
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_project_name = f"Project_{timestamp}"
            print(f"[JARVIS DEBUG] [FS] Auto-creating project: {new_project_name}")

            success, msg = self.project_manager.create_project(new_project_name)
            if success:
                self.project_manager.switch_project(new_project_name)
                try:
                    await self.session.send(input=f"System Notification: Automatic Project Creation. Switched to new project '{new_project_name}'.", end_of_turn=False)
                    if self.on_project_update:
                         self.on_project_update(new_project_name)
                except Exception as e:
                    print(f"[JARVIS DEBUG] [ERR] Failed to notify auto-project: {e}")

        try:
            final_path = self._resolve_project_path(path)
            final_path.mkdir(parents=True, exist_ok=True)
            relative_path = final_path.relative_to(self.project_manager.get_current_project_path().resolve())
            result = f"Directory '{relative_path}' created successfully in project '{self.project_manager.current_project}'."
        except Exception as e:
            result = f"Failed to create directory '{path}': {str(e)}"

        print(f"[JARVIS DEBUG] [FS] Result: {result}")
        try:
             await self.session.send(input=f"System Notification: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send fs result: {e}")

    async def handle_read_directory(self, path):
        print(f"[JARVIS DEBUG] [FS] Reading directory: '{path}'")
        try:
            final_path = self._resolve_project_path(path)
            relative_path = final_path.relative_to(self.project_manager.get_current_project_path().resolve())

            if not final_path.exists():
                result = f"Directory '{relative_path}' does not exist."
            elif not final_path.is_dir():
                result = f"Path '{relative_path}' is not a directory."
            else:
                items = [item.name for item in final_path.iterdir()]
                result = f"Contents of '{relative_path}': {', '.join(items)}"
        except Exception as e:
            result = f"Failed to read directory '{path}': {str(e)}"

        print(f"[JARVIS DEBUG] [FS] Result: {result}")
        try:
             await self.session.send(input=f"System Notification: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send fs result: {e}")

    async def handle_read_file(self, path):
        print(f"[JARVIS DEBUG] [FS] Reading file: '{path}'")
        try:
            final_path = self._resolve_project_path(path)
            relative_path = final_path.relative_to(self.project_manager.get_current_project_path().resolve())

            if not final_path.exists():
                result = f"File '{relative_path}' does not exist."
            elif not final_path.is_file():
                result = f"Path '{relative_path}' is not a file."
            else:
                with open(final_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                result = f"Content of '{relative_path}':\n{content}"
        except Exception as e:
            result = f"Failed to read file '{path}': {str(e)}"

        print(f"[JARVIS DEBUG] [FS] Result: {result}")
        try:
             await self.session.send(input=f"System Notification: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send fs result: {e}")

    async def handle_delete_path(self, path):
        print(f"[JARVIS DEBUG] [FS] Deleting path: '{path}'")
        try:
            final_path = self._resolve_project_path(path)
            current_project_path = self.project_manager.get_current_project_path().resolve()
            relative_path = final_path.relative_to(current_project_path)

            if final_path == current_project_path:
                result = "Refusing to delete the active project root. Use delete_project to delete a whole project."
            elif not final_path.exists() and not final_path.is_symlink():
                result = f"Path '{relative_path}' does not exist."
            elif final_path.is_symlink() or final_path.is_file():
                final_path.unlink()
                result = f"File '{relative_path}' deleted successfully from project '{self.project_manager.current_project}'."
            elif final_path.is_dir():
                shutil.rmtree(final_path)
                result = f"Directory '{relative_path}' deleted successfully from project '{self.project_manager.current_project}'."
            else:
                result = f"Path '{relative_path}' cannot be deleted because its type is not supported."
        except Exception as e:
            result = f"Failed to delete path '{path}': {str(e)}"

        print(f"[JARVIS DEBUG] [FS] Result: {result}")
        try:
             await self.session.send(input=f"System Notification: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send fs result: {e}")

    async def handle_web_agent_request(self, prompt):
        print(f"[JARVIS DEBUG] [WEB] Web Agent Task: '{prompt}'")
        
        async def update_frontend(image_b64, log_text):
            if self.on_web_data:
                 self.on_web_data({"image": image_b64, "log": log_text})
                 
        try:
            result = await self.web_agent.run_task(prompt, update_callback=update_frontend)
            print(f"[JARVIS DEBUG] [WEB] Web Agent Task Returned: {result}")
        except WebAgentQuotaError as e:
            result = str(e)
            print(f"[JARVIS DEBUG] [WEB] Web Agent quota error: {result}")
        except Exception as e:
            result = f"Web Agent failed: {e}"
            print(f"[JARVIS DEBUG] [WEB] {result}")
        
        # Send the final result back to the main model
        try:
             await self.session.send(input=f"System Notification: Web Agent has finished.\nResult: {result}", end_of_turn=True)
        except Exception as e:
             print(f"[JARVIS DEBUG] [ERR] Failed to send web agent result to model: {e}")

    async def _handle_openclaw_tool_call(self, fc):
        args = fc.args or {}
        name = fc.name
        print(f"[JARVIS DEBUG] [OPENCLAW] Tool Call: {name} Args={args}")

        try:
            if self._should_suppress_model_output() and self._is_whatsapp_openclaw_tool_call(name, args):
                result = self._openclaw_local_result(
                    name,
                    "La solicitud de WhatsApp ya fue gestionada localmente por Jarvis.",
                    warnings=["whatsapp_already_handled_locally"],
                )
            else:
                blocked_whatsapp = self._blocked_whatsapp_openclaw_tool_result(name, args)
                if blocked_whatsapp:
                    result = blocked_whatsapp
                elif name == "openclaw_check_status":
                    result = await self.openclaw_bridge.check_status()
                elif name == "get_pending_actions":
                    actions = self.pending_actions_manager.get_pending_actions()
                    result = self._openclaw_local_result(
                        "get_pending_actions",
                        f"{len(actions)} accion(es) pendiente(s).",
                        raw=actions,
                    )
                elif name == "confirm_pending_action":
                    result = await self._confirm_pending_openclaw_action(args.get("action_id"))
                elif name == "cancel_pending_action":
                    result = self._cancel_pending_openclaw_action(args.get("action_id"))
                elif name == "create_openclaw_autopilot_rule":
                    result = self._create_openclaw_autopilot_rule(args)
                elif name == "list_openclaw_autopilot_rules":
                    rules = self.openclaw_autopilot_manager.list_rules()
                    result = self._openclaw_local_result(
                        "get_autopilot_rules",
                        f"{len(rules)} regla(s) de respuesta automatica configurada(s).",
                        raw=rules,
                    )
                elif name in {"enable_openclaw_autopilot_rule", "disable_openclaw_autopilot_rule", "delete_openclaw_autopilot_rule"}:
                    action_type = {
                        "enable_openclaw_autopilot_rule": "enable_autopilot_rule",
                        "disable_openclaw_autopilot_rule": "disable_autopilot_rule",
                        "delete_openclaw_autopilot_rule": "delete_autopilot_rule",
                    }[name]
                    payload = {"rule_id": args.get("rule_id")}
                    result = self._queue_or_block_openclaw_action(action_type, payload, self._human_summary(action_type, payload))
                else:
                    action_type, payload = self._openclaw_action_from_tool(name, args)
                    result = await self._execute_or_queue_openclaw_action(action_type, payload)
        except Exception as exc:
            result = self._openclaw_local_result(
                name,
                f"No he podido preparar la accion externa: {str(exc)[:200]}",
                success=False,
                warnings=["handler_error"],
            )

        return types.FunctionResponse(id=fc.id, name=fc.name, response={"result": result})

    def _schedule_local_openclaw_voice_intent(self, transcript):
        if not str(transcript or "").strip():
            return
        task = getattr(self, "_local_openclaw_intent_task", None)
        if task and not task.done():
            task.cancel()
        self._local_openclaw_intent_task = asyncio.create_task(
            self._debounced_local_openclaw_voice_intent(transcript)
        )

    async def _debounced_local_openclaw_voice_intent(self, transcript):
        try:
            await asyncio.sleep(max(0.05, self._local_openclaw_intent_debounce_seconds))
            if transcript != self._last_input_transcription:
                return None
            return await self._handle_local_openclaw_voice_intent(transcript)
        except asyncio.CancelledError:
            return None

    async def _handle_local_openclaw_voice_intent(self, transcript):
        normalized = " ".join(str(transcript or "").lower().split())
        if not normalized or normalized == self._last_local_openclaw_intent_text:
            return None

        result = route_openclaw_voice_intent(
            transcript,
            self.openclaw_targets_manager,
            self.openclaw_messages_manager,
            self.pending_actions_manager,
            session_id="audio_loop",
        )
        if not result.get("handled"):
            result = route_openclaw_productivity_voice_intent(
                transcript,
                self.pending_actions_manager,
                session_id="audio_loop",
            )
        if not result.get("handled"):
            return None

        self._last_local_openclaw_intent_text = normalized
        self._suppress_model_output_until = max(self._suppress_model_output_until, time.time() + 3.0)
        self.clear_audio_queue()
        message = result.get("response") or result.get("message") or "He gestionado la accion local de WhatsApp."
        self._remember_model_output_text(message)
        if self.on_transcription:
            self.on_transcription({"sender": "JARVIS", "text": message, "append": False})
        pending_action = (result.get("data") or {}).get("pending_action") or result.get("pending_action")
        if pending_action and self.on_tool_confirmation:
            self.on_tool_confirmation({
                "id": pending_action.get("id"),
                "tool": pending_action.get("action_type"),
                "args": pending_action.get("payload"),
            })
        if self.project_manager:
            self.project_manager.log_chat("JARVIS", message)
        if self._env_bool("JARVIS_SYNC_LOCAL_WHATSAPP_TO_MODEL", False):
            try:
                await self.session.send(
                    input=(
                        "System Notification: Jarvis handled this WhatsApp alias/local-message intent directly. "
                        "Do not call OpenClaw resolve/read and do not answer it again. "
                        f"Result: {message}"
                    ),
                    end_of_turn=False,
                )
            except Exception as exc:
                print(f"[JARVIS DEBUG] [OPENCLAW] Failed to sync local WhatsApp intent: {exc}")
        return result

    async def _execute_or_queue_openclaw_action(self, action_type, payload, human_summary=None):
        action_type = str(action_type or "").strip()
        if not action_type:
            return self._openclaw_local_result(
                "unknown",
                "Falta action_type para ejecutar la accion externa.",
                success=False,
                warnings=["invalid_request"],
            )

        classification = self.openclaw_permissions.classify(action_type)
        if classification == "forbidden":
            return self._openclaw_local_result(
                action_type,
                f"Accion bloqueada por seguridad: {self.openclaw_permissions.explain(action_type)}",
                success=False,
                warnings=["forbidden"],
            )

        if classification == "confirmation_required":
            return self._queue_or_block_openclaw_action(action_type, payload, human_summary)

        result = await self._execute_openclaw_action(action_type, payload)
        rule_id = (payload or {}).get("_autopilot_rule_id")
        if rule_id and result.get("success"):
            self.openclaw_autopilot_manager.register_reply(rule_id)
        return result

    def _queue_or_block_openclaw_action(self, action_type, payload, human_summary=None):
        classification = self.openclaw_permissions.classify(action_type)
        if classification == "forbidden":
            return self._openclaw_local_result(
                action_type,
                f"Accion bloqueada por seguridad: {self.openclaw_permissions.explain(action_type)}",
                success=False,
                warnings=["forbidden"],
            )

        pending = self.pending_actions_manager.create_pending_action(
            action_type,
            payload or {},
            human_summary or self._human_summary(action_type, payload or {}),
        )
        return self._openclaw_local_result(
            action_type,
            f"Accion pendiente de confirmacion: {pending['human_summary']}. ID: {pending['id']}",
            success=False,
            raw=pending,
            warnings=["confirmation_required"],
        )

    async def _execute_openclaw_action(self, action_type, payload):
        payload = dict(payload or {})
        payload.setdefault("confirmed", True)
        external_payload = {key: value for key, value in payload.items() if not str(key).startswith("_")}
        return await self.openclaw_bridge.execute_action(action_type, external_payload)

    async def _confirm_pending_openclaw_action(self, action_id):
        action = self.pending_actions_manager.confirm_action(action_id)
        if not action:
            return self._openclaw_local_result(
                "confirm_pending_action",
                "No encuentro esa accion pendiente.",
                success=False,
                warnings=["not_found"],
            )

        action_type = action.get("action_type")
        payload = action.get("payload") or {}
        result = await self._execute_confirmed_pending_action(action_type, payload)
        self.pending_actions_manager.mark_executed(action["id"], result)
        return result

    async def _execute_confirmed_pending_action(self, action_type, payload):
        if action_type == "create_autopilot_rule":
            rule = self.openclaw_autopilot_manager.create_rule(
                payload.get("channel"),
                payload.get("target"),
                payload.get("mode"),
                payload.get("trigger"),
                payload.get("behavior"),
            )
            return self._openclaw_local_result(action_type, "Regla de respuesta automatica creada.", raw=rule)

        if action_type == "enable_autopilot_rule":
            rule = self.openclaw_autopilot_manager.enable_rule(payload.get("rule_id"))
            return self._autopilot_rule_mutation_result(action_type, rule, "activada")

        if action_type == "disable_autopilot_rule":
            rule = self.openclaw_autopilot_manager.disable_rule(payload.get("rule_id"))
            return self._autopilot_rule_mutation_result(action_type, rule, "desactivada")

        if action_type == "delete_autopilot_rule":
            rule = self.openclaw_autopilot_manager.delete_rule(payload.get("rule_id"))
            return self._autopilot_rule_mutation_result(action_type, rule, "eliminada")

        result = await self._execute_openclaw_action(action_type, payload)
        rule_id = (payload or {}).get("_autopilot_rule_id")
        if rule_id and result.get("success"):
            self.openclaw_autopilot_manager.register_reply(rule_id)
        return result

    def _cancel_pending_openclaw_action(self, action_id):
        action = self.pending_actions_manager.cancel_action(action_id)
        if not action:
            return self._openclaw_local_result(
                "cancel_pending_action",
                "No encuentro esa accion pendiente.",
                success=False,
                warnings=["not_found"],
            )
        return self._openclaw_local_result("cancel_pending_action", "Accion pendiente cancelada.", raw=action)

    def _create_openclaw_autopilot_rule(self, args):
        if not self._env_bool("JARVIS_OPENCLAW_AUTOPILOT_ENABLED", True):
            return self._openclaw_local_result(
                "create_autopilot_rule",
                "Las respuestas automaticas externas no estan habilitadas.",
                success=False,
                warnings=["autopilot_disabled"],
            )

        mode = args.get("mode", "ask_before_send")
        payload = {
            "channel": args.get("channel"),
            "target": args.get("target"),
            "mode": mode,
            "trigger": args.get("trigger") or {},
            "behavior": args.get("behavior") or {},
        }

        if mode == "auto_send_limited":
            return self._queue_or_block_openclaw_action(
                "create_autopilot_rule",
                payload,
                self._human_summary("create_autopilot_rule", payload),
            )

        rule = self.openclaw_autopilot_manager.create_rule(
            payload["channel"],
            payload["target"],
            payload["mode"],
            payload["trigger"],
            payload["behavior"],
        )
        return self._openclaw_local_result("create_autopilot_rule", "Regla de respuesta automatica creada.", raw=rule)

    def _openclaw_action_from_tool(self, name, args):
        if name == "openclaw_execute_action":
            return args.get("action_type"), args.get("payload") or {}
        if name == "openclaw_send_message":
            return "send_message", {"channel": args.get("channel"), "target": args.get("target"), "message": args.get("message")}
        if name == "openclaw_read_conversation":
            return "read_conversation", {"channel": args.get("channel"), "target": args.get("target"), "limit": args.get("limit", 10)}
        if name == "openclaw_search_email":
            return "search_email", {"service": "email", "query": args.get("query"), "max_results": args.get("max_results", 10)}
        if name == "openclaw_draft_email":
            return "draft_email", args.get("payload") or {}
        if name == "openclaw_send_email":
            payload = args.get("payload") or {}
            payload["action_type"] = payload.get("action_type", "send_email")
            return payload["action_type"], payload
        if name == "openclaw_list_calendar_events":
            return "list_calendar_events", args.get("payload") or {}
        if name == "openclaw_calendar_action":
            action = str(args.get("action") or "").lower()
            action_type = self.openclaw_bridge._calendar_action_type(action)
            return action_type, {"calendar_action": action, "payload": args.get("payload") or {}}
        if name == "openclaw_prepare_social_post":
            return "prepare_social_post", args.get("payload") or {}
        if name == "openclaw_schedule_social_post":
            return "schedule_social_post", args.get("payload") or {}
        if name == "openclaw_publish_social_post":
            return "publish_social_post", args.get("payload") or {}
        if name == "openclaw_run_workflow":
            return "run_workflow", {"workflow_name": args.get("workflow_name"), "payload": args.get("payload") or {}}
        return name, dict(args or {})

    def _blocked_whatsapp_openclaw_tool_result(self, name, args):
        args = args or {}
        action_type = args.get("action_type") if name == "openclaw_execute_action" else None
        payload = args.get("payload") if name == "openclaw_execute_action" else args
        payload = payload or {}
        channel = str(payload.get("channel") or args.get("channel") or "").strip().lower()
        action_norm = str(action_type or name or "").strip().lower()

        is_whatsapp = channel == "whatsapp" or "whatsapp" in action_norm
        is_send = action_norm in {"openclaw_send_message", "send_message", "send_whatsapp_message", "send_channel_message"} or "send" in action_norm
        is_read = action_norm in {"openclaw_read_conversation", "read_conversation", "list_messages"} or "read" in action_norm

        if not is_whatsapp:
            return None

        if is_read:
            return self._openclaw_local_result(
                action_norm,
                "WhatsApp no soporta lectura de historial en OpenClaw; Jarvis lee mensajes inbound guardados.",
                success=False,
                warnings=["whatsapp_read_local_only"],
            )

        if is_send or name == "openclaw_execute_action":
            return self._queue_whatsapp_send_from_tool(action_norm, payload)

        return None

    def _looks_like_phone_target(self, value):
        compact = re.sub(r"[\s().-]+", "", str(value or "").strip())
        return bool(re.fullmatch(r"\+\d{6,15}", compact) or re.fullmatch(r"\d{6,15}", compact))

    def _normalize_direct_phone_target(self, value):
        compact = re.sub(r"[\s().-]+", "", str(value or "").strip())
        if compact.startswith("00"):
            compact = f"+{compact[2:]}"
        if compact.startswith("+"):
            return compact
        if compact.startswith("34"):
            return f"+{compact}"
        if re.fullmatch(r"[679]\d{8}", compact):
            return f"+34{compact}"
        return compact

    def _same_whatsapp_pending(self, pending_payload, canonical_target, message):
        pending_payload = pending_payload or {}
        if str(pending_payload.get("channel") or "").strip().lower() != "whatsapp":
            return False
        pending_target = pending_payload.get("canonical_target") or pending_payload.get("target")
        return (
            str(pending_target or "").strip() == str(canonical_target or "").strip()
            and str(pending_payload.get("message") or "").strip() == str(message or "").strip()
        )

    def _find_existing_whatsapp_pending(self, canonical_target, message):
        manager = getattr(self, "pending_actions_manager", None)
        if not manager:
            return None
        for action in manager.get_pending_actions():
            if action.get("action_type") in {"send_message", "send_whatsapp_message", "send_channel_message"} and self._same_whatsapp_pending(action.get("payload"), canonical_target, message):
                return action
        return None

    def _queue_whatsapp_send_from_tool(self, action_norm, payload):
        payload = dict(payload or {})
        message = str(payload.get("message") or payload.get("text") or "").strip()
        target_text = str(
            payload.get("canonical_target")
            or payload.get("target")
            or payload.get("display_target")
            or ""
        ).strip()

        if not target_text or not message:
            return self._openclaw_local_result(
                action_norm,
                "Falta contacto o mensaje para preparar el WhatsApp.",
                success=False,
                warnings=["invalid_whatsapp_tool_payload"],
            )

        target = None
        manager = getattr(self, "openclaw_targets_manager", None)
        if manager:
            target = manager.find_best_match("whatsapp", target_text)

        if target:
            canonical_target = target.get("canonical_target") or target.get("raw_target")
            display_target = target.get("display_name") or target_text
            kind = target.get("kind", "user")
            target_id = target.get("id")
        elif payload.get("canonical_target") or self._looks_like_phone_target(target_text):
            canonical_target = payload.get("canonical_target") or self._normalize_direct_phone_target(target_text)
            display_target = payload.get("display_target") or target_text
            kind = payload.get("kind", "user")
            target_id = payload.get("target_id")
        else:
            return self._openclaw_local_result(
                action_norm,
                f"No tengo guardado el contacto '{target_text}'. Importalo o crealo en la agenda WhatsApp de Jarvis antes de enviar.",
                success=False,
                warnings=["whatsapp_target_not_found", "whatsapp_local_flow_required"],
            )

        if not canonical_target:
            return self._openclaw_local_result(
                action_norm,
                f"El contacto {display_target} no tiene numero o target canonico guardado.",
                success=False,
                warnings=["whatsapp_target_missing_canonical"],
            )

        pending_manager = getattr(self, "pending_actions_manager", None)
        if not pending_manager:
            return self._openclaw_local_result(
                action_norm,
                "Las acciones de WhatsApp por alias se gestionan localmente por Jarvis mediante agenda y confirmacion.",
                success=False,
                warnings=["whatsapp_local_flow_required"],
            )

        send_payload = {
            "channel": "whatsapp",
            "kind": kind,
            "target": canonical_target,
            "canonical_target": canonical_target,
            "display_target": display_target,
            "target_id": target_id,
            "message": message,
        }
        existing = self._find_existing_whatsapp_pending(canonical_target, message)
        if existing:
            pending = existing
        else:
            pending = pending_manager.create_pending_action(
                "send_message",
                send_payload,
                f"Enviar WhatsApp a {display_target}: {message}",
            )

        tool_confirmation_callback = getattr(self, "on_tool_confirmation", None)
        if tool_confirmation_callback and not existing:
            tool_confirmation_callback({
                "id": pending.get("id"),
                "tool": pending.get("action_type"),
                "args": pending.get("payload"),
            })

        summary = f"He preparado el WhatsApp para {display_target}: '{message}'. Confirmalo para enviarlo."
        self._remember_model_output_text(summary)
        transcription_callback = getattr(self, "on_transcription", None)
        if transcription_callback and not existing:
            transcription_callback({"sender": "JARVIS", "text": summary, "append": False})
        return self._openclaw_local_result(
            action_norm,
            summary,
            success=False,
            raw=pending,
            warnings=["confirmation_required", "whatsapp_local_pending_action"],
        )

    def _autopilot_rule_mutation_result(self, action_type, rule, label):
        if not rule:
            return self._openclaw_local_result(action_type, "No encuentro esa regla.", success=False, warnings=["not_found"])
        return self._openclaw_local_result(action_type, f"Regla {label}.", raw=rule)

    def _openclaw_local_result(self, action_type, summary, success=True, raw=None, warnings=None):
        return {
            "success": bool(success),
            "service": "openclaw",
            "action_type": action_type,
            "summary": summary,
            "raw": raw,
            "external_id": None,
            "warnings": warnings or [],
        }

    def _human_summary(self, action_type, payload):
        payload = payload or {}
        if action_type in {"send_message", "send_whatsapp_message", "send_channel_message"}:
            return f"Enviar mensaje a {payload.get('target')} por {payload.get('channel')}: {payload.get('message')}"
        if action_type in {"send_email", "reply_email"}:
            return f"Enviar correo: {payload.get('subject') or payload.get('to') or 'sin asunto'}"
        if action_type.endswith("_calendar_event"):
            return f"Ejecutar accion de calendario: {action_type}"
        if action_type in {"schedule_social_post", "publish_social_post"}:
            return f"Ejecutar accion de redes sociales: {action_type}"
        if action_type == "run_workflow":
            return f"Ejecutar workflow: {payload.get('workflow_name')}"
        if action_type == "create_autopilot_rule":
            return f"Crear regla automatica para {payload.get('channel')} -> {payload.get('target')} en modo {payload.get('mode')}"
        if action_type.endswith("_autopilot_rule"):
            return f"Modificar regla automatica: {action_type}"
        return f"Ejecutar accion externa: {action_type}"

    def _env_bool(self, name, default=False):
        raw = os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def _float_env(self, name, default=0.0):
        raw = os.getenv(name)
        if raw is None:
            return float(default)
        try:
            return float(raw)
        except Exception:
            return float(default)

    def _should_suppress_model_output(self):
        return time.time() < getattr(self, "_suppress_model_output_until", 0.0)

    def _is_whatsapp_openclaw_tool_call(self, name, args):
        args = args or {}
        action_type = args.get("action_type") if name == "openclaw_execute_action" else None
        payload = args.get("payload") if name == "openclaw_execute_action" else args
        payload = payload or {}
        channel = str(payload.get("channel") or args.get("channel") or "").strip().lower()
        action_norm = str(action_type or name or "").strip().lower()
        return channel == "whatsapp" or "whatsapp" in action_norm

    async def receive_audio(self):
        "Background task to reads from the websocket and write pcm chunks to the output queue"
        try:
            while not self.stop_event.is_set():
                turn_input_transcript = ""
                turn = self.session.receive()
                async for response in turn:
                    if self.stop_event.is_set():
                        break

                    # 1. Handle Audio Data
                    if data := response.data:
                        self._mark_model_audio_active()
                        if self.audio_in_queue and not self._should_suppress_model_output():
                            self.audio_in_queue.put_nowait(data)
                        # NOTE: 'continue' removed here to allow processing transcription/tools in same packet

                    # 2. Handle Transcription (User & Model)
                    if response.server_content:
                        if response.server_content.input_transcription:
                            transcript = response.server_content.input_transcription.text
                            if transcript:
                                if self._should_ignore_input_transcript(transcript):
                                    if transcript != self._last_input_transcription:
                                        self._last_input_transcription = transcript
                                        print("[JARVIS DEBUG] [ECHO] Ignored input transcription while Jarvis audio/output is active.")
                                    continue

                                # Skip if this is an exact duplicate event
                                if transcript != self._last_input_transcription:
                                    # Calculate delta (Gemini may send cumulative or chunk-based text)
                                    delta = transcript
                                    if transcript.startswith(self._last_input_transcription):
                                        delta = transcript[len(self._last_input_transcription):]
                                    self._last_input_transcription = transcript
                                    turn_input_transcript = transcript
                                    
                                    # Only send if there's new text
                                    if delta:
                                        # User is speaking, so interrupt model playback!
                                        self.clear_audio_queue()

                                        # Send to frontend (Streaming)
                                        if self.on_transcription:
                                             self.on_transcription({"sender": "User", "text": delta})
                                        
                                        # Buffer for Logging
                                        if self.chat_buffer["sender"] != "User":
                                            # Flush previous if exists
                                            if self.chat_buffer["sender"] and self.chat_buffer["text"].strip():
                                                self.project_manager.log_chat(self.chat_buffer["sender"], self.chat_buffer["text"])
                                            # Start new
                                            self.chat_buffer = {"sender": "User", "text": delta}
                                        else:
                                            # Append
                                            self.chat_buffer["text"] += delta

                                        self._schedule_local_openclaw_voice_intent(transcript)
                        
                        if response.server_content.output_transcription and not self._should_suppress_model_output():
                            transcript = response.server_content.output_transcription.text
                            if transcript:
                                # Skip if this is an exact duplicate event
                                if transcript != self._last_output_transcription:
                                    # Calculate delta (Gemini may send cumulative or chunk-based text)
                                    delta = transcript
                                    if transcript.startswith(self._last_output_transcription):
                                        delta = transcript[len(self._last_output_transcription):]
                                    self._last_output_transcription = transcript
                                    
                                    # Only send if there's new text
                                    if delta:
                                        self._remember_model_output_text(delta)
                                        # Send to frontend (Streaming)
                                        if self.on_transcription:
                                             self.on_transcription({"sender": "JARVIS", "text": delta})
                                        
                                        # Buffer for Logging
                                        if self.chat_buffer["sender"] != "JARVIS":
                                            # Flush previous
                                            if self.chat_buffer["sender"] and self.chat_buffer["text"].strip():
                                                self.project_manager.log_chat(self.chat_buffer["sender"], self.chat_buffer["text"])
                                            # Start new
                                            self.chat_buffer = {"sender": "JARVIS", "text": delta}
                                        else:
                                            # Append
                                            self.chat_buffer["text"] += delta
                        
                        # Flush buffer on turn completion if needed, 
                        # but usually better to wait for sender switch or explicit end.
                        # We can also check turn_complete signal if available in response.server_content.model_turn etc

                    # 3. Handle Tool Calls
                    if response.tool_call:
                        print("The tool was called")
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            if fc.name in ["generate_cad", "run_web_agent", "inspect_camera", "create_directory", "write_file", "read_directory", "read_file", "delete_path", "delete_project", "create_project", "switch_project", "list_projects", "list_smart_devices", "control_light", "discover_printers", "print_stl", "get_print_status", "pause_print", "resume_print", "cancel_print", "iterate_cad", "activate_simulation_mode", "deactivate_simulation_mode", "get_simulation_status"] or fc.name in OPENCLAW_TOOL_NAMES:
                                prompt = fc.args.get("prompt", "") # Prompt is not present for all tools
                                
                                # Check Permissions (Default to True if not set)
                                confirmation_required = self.permissions.get(fc.name, True)
                                
                                if not confirmation_required:
                                    print(f"[JARVIS DEBUG] [TOOL] Permission check: '{fc.name}' -> AUTO-ALLOW")
                                    # Skip confirmation block and jump to execution
                                    pass
                                else:
                                    # Confirmation Logic
                                    if self.on_tool_confirmation:
                                        import uuid
                                        request_id = str(uuid.uuid4())
                                    print(f"[JARVIS DEBUG] [STOP] Requesting confirmation for '{fc.name}' (ID: {request_id})")
                                    
                                    future = asyncio.Future()
                                    self._pending_confirmations[request_id] = future
                                    
                                    self.on_tool_confirmation({
                                        "id": request_id, 
                                        "tool": fc.name, 
                                        "args": fc.args
                                    })
                                    
                                    try:
                                        # Wait for user response
                                        confirmed = await future

                                    finally:
                                        self._pending_confirmations.pop(request_id, None)

                                    print(f"[JARVIS DEBUG] [CONFIRM] Request {request_id} resolved. Confirmed: {confirmed}")

                                    if not confirmed:
                                        print(f"[JARVIS DEBUG] [DENY] Tool call '{fc.name}' denied by user.")
                                        function_response = types.FunctionResponse(
                                            id=fc.id,
                                            name=fc.name,
                                            response={
                                                "result": "User denied the request to use this tool.",
                                            }
                                        )
                                        function_responses.append(function_response)
                                        continue

                                    if not confirmed:
                                        print(f"[JARVIS DEBUG] [DENY] Tool call '{fc.name}' denied by user.")
                                        function_response = types.FunctionResponse(
                                            id=fc.id,
                                            name=fc.name,
                                            response={
                                                "result": "User denied the request to use this tool.",
                                            }
                                        )
                                        function_responses.append(function_response)
                                        continue

                                # If confirmed (or no callback configured, or auto-allowed), proceed
                                if fc.name == "generate_cad":
                                    print(f"\n[JARVIS DEBUG] --------------------------------------------------")
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call Detected: 'generate_cad'")
                                    print(f"[JARVIS DEBUG] [IN] Arguments: prompt='{prompt}'")
                                    
                                    asyncio.create_task(self.handle_cad_request(prompt))
                                    # No function response needed - model already acknowledged when user asked
                                
                                elif fc.name == "run_web_agent":
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'run_web_agent' with prompt='{prompt}'")
                                    asyncio.create_task(self.handle_web_agent_request(prompt))
                                    
                                    result_text = "Web Navigation started. Do not reply to this message."
                                    function_response = types.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response={
                                            "result": result_text,
                                        }
                                    )
                                    print(f"[JARVIS DEBUG] [RESPONSE] Sending function response: {function_response}")
                                    function_responses.append(function_response)


                                elif fc.name == "inspect_camera":
                                    prompt = fc.args.get("prompt", "Describe what is visible in the current webcam frame.")
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'inspect_camera' prompt='{prompt}'")
                                    result_text = await self.inspect_camera_view(prompt)
                                    function_response = types.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response={"result": result_text}
                                    )
                                    function_responses.append(function_response)


                                elif fc.name == "write_file":
                                    path = fc.args["path"]
                                    content = fc.args["content"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'write_file' path='{path}'")
                                    asyncio.create_task(self.handle_write_file(path, content))
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": "Writing file..."}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "create_directory":
                                    path = fc.args["path"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'create_directory' path='{path}'")
                                    asyncio.create_task(self.handle_create_directory(path))
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": "Creating directory..."}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "read_directory":
                                    path = fc.args["path"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'read_directory' path='{path}'")
                                    asyncio.create_task(self.handle_read_directory(path))
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": "Reading directory..."}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "read_file":
                                    path = fc.args["path"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'read_file' path='{path}'")
                                    asyncio.create_task(self.handle_read_file(path))
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": "Reading file..."}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "delete_path":
                                    path = fc.args["path"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'delete_path' path='{path}'")
                                    asyncio.create_task(self.handle_delete_path(path))
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": "Deleting path..."}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "create_project":
                                    name = fc.args["name"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'create_project' name='{name}'")
                                    success, msg = self.project_manager.create_project(name)
                                    if success:
                                        # Auto-switch to the newly created project
                                        self.project_manager.switch_project(name)
                                        msg += f" Switched to '{name}'."
                                        if self.on_project_update:
                                            self.on_project_update(name)
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": msg}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "delete_project":
                                    name = fc.args["name"]
                                    previous_project = self.project_manager.current_project
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'delete_project' name='{name}'")
                                    success, msg = self.project_manager.delete_project(name)
                                    if success and self.project_manager.current_project != previous_project:
                                        if self.on_project_update:
                                            self.on_project_update(self.project_manager.current_project)
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": msg}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "switch_project":
                                    name = fc.args["name"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'switch_project' name='{name}'")
                                    success, msg = self.project_manager.switch_project(name)
                                    if success:
                                        if self.on_project_update:
                                            self.on_project_update(name)
                                        # Gather project context and send to AI (silently, no response expected)
                                        context = self.project_manager.get_project_context()
                                        print(f"[JARVIS DEBUG] [PROJECT] Sending project context to AI ({len(context)} chars)")
                                        try:
                                            await self.session.send(input=f"System Notification: {msg}\n\n{context}", end_of_turn=False)
                                        except Exception as e:
                                            print(f"[JARVIS DEBUG] [ERR] Failed to send project context: {e}")
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": msg}
                                    )
                                    function_responses.append(function_response)
                                
                                elif fc.name == "list_projects":
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'list_projects'")
                                    projects = self.project_manager.list_projects()
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": f"Available projects: {', '.join(projects)}"}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "activate_simulation_mode":
                                    simulation_manager.activate_all()
                                    kasa_simulator.reset()
                                    printer_simulator.reset()
                                    result_str = "Modo simulacion activado. A partir de ahora usare dispositivos Kasa e impresoras 3D simuladas."
                                    if self.on_simulation_update:
                                        self.on_simulation_update(result_str)
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "deactivate_simulation_mode":
                                    simulation_manager.deactivate_all()
                                    result_str = "Modo simulacion desactivado. Volvere a usar dispositivos reales si estan disponibles."
                                    if self.on_simulation_update:
                                        self.on_simulation_update(result_str)
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "get_simulation_status":
                                    state = simulation_manager.get_state()
                                    result_str = f"Simulation mode: {state['simulation_mode']}. Kasa: {state['kasa_simulation']}. Printers: {state['printer_simulation']}."
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "list_smart_devices":
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'list_smart_devices'")
                                    frontend_list = await self.kasa_agent.discover_devices()
                                    dev_summaries = []
                                    for d in frontend_list:
                                        state_text = "ON" if d.get("is_on") else "OFF"
                                        dev_summaries.append(
                                            f"{d.get('alias')} (IP: {d.get('ip')}, Type: {d.get('type')}, Model: {d.get('model')}) [{state_text}]"
                                        )

                                    result_str = "No devices found in cache."
                                    if dev_summaries:
                                        result_str = "Found Devices:\n" + "\n".join(dev_summaries)
                                    
                                    # Trigger frontend update
                                    if self.on_device_update:
                                        self.on_device_update(frontend_list)
                                    if simulation_manager.is_kasa_enabled() and self.on_simulation_update:
                                        self.on_simulation_update("Detectados dispositivos Kasa simulados")

                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "control_light":
                                    target = fc.args["target"]
                                    action = fc.args["action"]
                                    brightness = fc.args.get("brightness")
                                    color = fc.args.get("color")
                                    
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'control_light' Target='{target}' Action='{action}'")
                                    
                                    result_msg = f"Action '{action}' on '{target}' failed."
                                    success = False
                                    
                                    if action == "turn_on":
                                        success = await self.kasa_agent.turn_on(target)
                                        if success:
                                            result_msg = f"Turned ON '{target}'."
                                    elif action == "turn_off":
                                        success = await self.kasa_agent.turn_off(target)
                                        if success:
                                            result_msg = f"Turned OFF '{target}'."
                                    elif action == "set":
                                        result_msg = f"Updated '{target}':"
                                    
                                    # Apply extra attributes if 'set' or if we just turned it on and want to set them too
                                    if success or action == "set":
                                        if brightness is not None:
                                            sb = await self.kasa_agent.set_brightness(target, brightness)
                                            success = success or sb
                                            if sb:
                                                result_msg += f" Set brightness to {brightness}."
                                        if color is not None:
                                            sc = await self.kasa_agent.set_color(target, color)
                                            success = success or sc
                                            if sc:
                                                result_msg += f" Set color to {color}."
                                        if action == "set" and not success:
                                            result_msg = f"Could not update '{target}'."

                                    # Notify Frontend of State Change
                                    if success:
                                        updated_list = self.kasa_agent.get_all_states()
                                        if self.on_device_update:
                                            self.on_device_update(updated_list)
                                        if simulation_manager.is_kasa_enabled() and self.on_simulation_update:
                                            self.on_simulation_update(kasa_simulator.last_operation_message)
                                    else:
                                        # Report Error
                                        if self.on_error:
                                            self.on_error(result_msg)

                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_msg}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "discover_printers":
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'discover_printers'")
                                    printers = await self.printer_agent.discover_printers()
                                    if simulation_manager.is_printer_enabled() and self.on_simulation_update:
                                        self.on_simulation_update("Detectadas impresoras simuladas")
                                    # Format for model
                                    if printers:
                                        printer_list = []
                                        for p in printers:
                                            printer_list.append(f"{p['name']} ({p['host']}:{p['port']}, type: {p['printer_type']})")
                                        result_str = "Found Printers:\n" + "\n".join(printer_list)
                                    else:
                                        result_str = "No printers found on network. Ensure printers are on and running OctoPrint/Moonraker."
                                    
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "print_stl":
                                    stl_path = fc.args.get("stl_path", "jarvis_demo_part")
                                    printer = fc.args["printer"]
                                    profile = fc.args.get("profile")
                                    
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'print_stl' STL='{stl_path}' Printer='{printer}'")
                                    
                                    # Resolve 'current' to project STL
                                    if stl_path.lower() == "current":
                                        stl_path = "output.stl" # Let printer agent resolve it in root_path

                                    # Get current project path
                                    project_path = str(self.project_manager.get_current_project_path())
                                    
                                    result = await self.printer_agent.print_stl(
                                        stl_path, 
                                        printer, 
                                        profile, 
                                        root_path=project_path
                                    )
                                    result_str = result.get("message", "Unknown result")
                                    if simulation_manager.is_printer_enabled() and self.on_simulation_update:
                                        self.on_simulation_update(result_str)
                                     
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name == "get_print_status":
                                    printer = fc.args["printer"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'get_print_status' Printer='{printer}'")
                                    
                                    status = await self.printer_agent.get_print_status(printer)
                                    if status:
                                        result_str = f"Printer: {status.printer}\n"
                                        result_str += f"State: {status.state}\n"
                                        result_str += f"Progress: {status.progress_percent:.1f}%\n"
                                        if status.time_remaining:
                                            result_str += f"Time Remaining: {status.time_remaining}\n"
                                        if status.time_elapsed:
                                            result_str += f"Time Elapsed: {status.time_elapsed}\n"
                                        if status.filename:
                                            result_str += f"File: {status.filename}\n"
                                        if status.temperatures:
                                            temps = status.temperatures
                                            if "hotend" in temps:
                                                result_str += f"Hotend: {temps['hotend']['current']:.0f}°C / {temps['hotend']['target']:.0f}°C\n"
                                            if "bed" in temps:
                                                result_str += f"Bed: {temps['bed']['current']:.0f}°C / {temps['bed']['target']:.0f}°C"
                                    else:
                                        result_str = f"Could not get status for printer '{printer}'. Ensure it is discovered first."
                                    
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name in ["pause_print", "resume_print", "cancel_print"]:
                                    printer = fc.args.get("printer") or await self._infer_active_printer_target()
                                    action_names = {
                                        "pause_print": ("pause", "paused"),
                                        "resume_print": ("resume", "resumed"),
                                        "cancel_print": ("cancel", "cancelled"),
                                    }
                                    action, past_tense = action_names[fc.name]

                                    if not printer:
                                        result_str = f"Could not {action} the print because no active printer could be inferred. Ask the user which printer to use."
                                    else:
                                        print(f"[JARVIS DEBUG] [TOOL] Tool Call: '{fc.name}' Printer='{printer}'")
                                        if fc.name == "pause_print":
                                            result = await self.printer_agent.pause_print(printer)
                                        elif fc.name == "resume_print":
                                            result = await self.printer_agent.resume_print(printer)
                                        else:
                                            result = await self.printer_agent.cancel_print(printer)

                                        if result.get("success"):
                                            result_str = f"Print on '{printer}' {past_tense}."
                                            status = result.get("status")
                                            if isinstance(status, dict):
                                                state = status.get("state")
                                                progress = status.get("progress_percent")
                                                if state:
                                                    result_str += f" State: {state}."
                                                if progress is not None:
                                                    result_str += f" Progress: {float(progress):.1f}%."
                                        else:
                                            result_str = result.get("message") or f"Could not {action} the print on '{printer}'. Ensure it is discovered and currently available."

                                    if simulation_manager.is_printer_enabled() and self.on_simulation_update:
                                        self.on_simulation_update(result_str)

                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)

                                elif fc.name in OPENCLAW_TOOL_NAMES:
                                    function_response = await self._handle_openclaw_tool_call(fc)
                                    function_responses.append(function_response)

                                elif fc.name == "iterate_cad":
                                    prompt = fc.args["prompt"]
                                    print(f"[JARVIS DEBUG] [TOOL] Tool Call: 'iterate_cad' Prompt='{prompt}'")
                                    
                                    # Emit status
                                    if self.on_cad_status:
                                        self.on_cad_status("generating")
                                    
                                    # Get project cad folder path
                                    cad_output_dir = str(self.project_manager.get_current_project_path() / "cad")
                                    
                                    # Call CadAgent to iterate on the design
                                    cad_data = await self.cad_agent.iterate_prototype(prompt, output_dir=cad_output_dir)
                                    
                                    if cad_data:
                                        print(f"[JARVIS DEBUG] [OK] CadAgent iteration returned data successfully.")
                                        
                                        # Dispatch to frontend
                                        if self.on_cad_data:
                                            print(f"[JARVIS DEBUG] [SEND] Dispatching iterated CAD data to frontend...")
                                            self.on_cad_data(cad_data)
                                            print(f"[JARVIS DEBUG] [SENT] Dispatch complete.")
                                        
                                        # Save to Project
                                        self.project_manager.save_cad_artifact("output.stl", f"Iteration: {prompt}")
                                        
                                        result_str = f"Successfully iterated design: {prompt}. The updated 3D model is now displayed."
                                    else:
                                        print(f"[JARVIS DEBUG] [ERR] CadAgent iteration returned None.")
                                        result_str = f"Failed to iterate design with prompt: {prompt}"
                                    
                                    function_response = types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result_str}
                                    )
                                    function_responses.append(function_response)
                        if function_responses:
                            await self.session.send_tool_response(function_responses=function_responses)
                
                # Turn/Response Loop Finished
                task = getattr(self, "_local_openclaw_intent_task", None)
                if task and not task.done():
                    task.cancel()
                if turn_input_transcript:
                    await self._handle_local_openclaw_voice_intent(turn_input_transcript)
                self.flush_chat()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Error in receive_audio: {e}")
            traceback.print_exc()
            # CRITICAL: Re-raise to crash the TaskGroup and trigger outer loop reconnect
            raise e

    async def play_audio(self):
        stream = None
        try:
            stream = await asyncio.to_thread(
                pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE,
                output=True,
                output_device_index=self.output_device_index,
            )
            self.output_audio_stream = stream
            while not self.stop_event.is_set():
                bytestream = await self.audio_in_queue.get()
                if bytestream is None:
                    break
                self._mark_model_audio_active()
                if self.on_audio_data:
                    self.on_audio_data(bytestream)
                await asyncio.to_thread(stream.write, bytestream)
                self._mark_model_audio_active()
        finally:
            if stream is not None and self.output_audio_stream is stream:
                self._close_stream("output_audio_stream")

    @staticmethod
    def _camera_backend_candidates():
        candidates = []

        def add_backend(name):
            backend = getattr(cv2, name, None)
            if backend is not None:
                candidates.append((name, backend))

        if os.name == "nt":
            add_backend("CAP_DSHOW")
            add_backend("CAP_MSMF")
        elif sys.platform == "darwin":
            add_backend("CAP_AVFOUNDATION")
        else:
            add_backend("CAP_V4L2")

        candidates.append(("default", None))
        return candidates

    async def _open_video_capture(self, index):
        for backend_name, backend in self._camera_backend_candidates():
            print(f"[JARVIS] Trying camera index {index} with backend {backend_name}...")
            if backend is None:
                cap = await asyncio.to_thread(cv2.VideoCapture, index)
            else:
                cap = await asyncio.to_thread(cv2.VideoCapture, index, backend)

            if cap.isOpened():
                print(f"[JARVIS] Camera {index} opened with backend {backend_name}.")
                return cap

            await asyncio.to_thread(cap.release)

        return None

    async def get_frames(self):
        cap = await self._open_video_capture(0)
        if cap is None:
            print("[JARVIS] [ERR] Could not open camera for frame capture.")
            return

        try:
            while not self.stop_event.is_set():
                if self.paused:
                    await asyncio.sleep(0.1)
                    continue
                frame = await asyncio.to_thread(self._get_frame, cap)
                if frame is None:
                    break
                await asyncio.sleep(1.0)
                if self.out_queue:
                    await self.out_queue.put(frame)
        finally:
            cap.release()

    def _get_frame(self, cap):
        ret, frame = cap.read()
        if not ret:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(frame_rgb)
        img.thumbnail([1024, 1024])
        image_io = io.BytesIO()
        img.save(image_io, format="jpeg")
        image_io.seek(0)
        image_bytes = image_io.read()
        return {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode()}

    async def _get_screen(self):
        pass 
    async def get_screen(self):
         pass

    async def run(self, start_message=None):
        retry_delay = 1
        is_reconnect = False
        
        while not self.stop_event.is_set():
            try:
                print(f"[JARVIS DEBUG] [CONNECT] Connecting to Gemini Live API...")
                async with (
                    client.aio.live.connect(model=MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session

                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)

                    session_tasks = []
                    session_tasks.append(tg.create_task(self.send_realtime()))
                    session_tasks.append(tg.create_task(self.listen_audio()))
                    # tg.create_task(self._process_video_queue()) # Removed in favor of VAD

                    if self.video_mode == "camera":
                        session_tasks.append(tg.create_task(self.get_frames()))
                    elif self.video_mode == "screen":
                        session_tasks.append(tg.create_task(self.get_screen()))

                    session_tasks.append(tg.create_task(self.receive_audio()))
                    session_tasks.append(tg.create_task(self.play_audio()))

                    # Handle Startup vs Reconnect Logic
                    if not is_reconnect:
                        if start_message:
                            print(f"[JARVIS DEBUG] [INFO] Sending start message: {start_message}")
                            await self.session.send(input=start_message, end_of_turn=True)
                        
                        # Sync Project State
                        if self.on_project_update and self.project_manager:
                            self.on_project_update(self.project_manager.current_project)
                    
                    else:
                        print(f"[JARVIS DEBUG] [RECONNECT] Connection restored.")
                        # Restore Context
                        print(f"[JARVIS DEBUG] [RECONNECT] Fetching recent chat history to restore context...")
                        history = self.project_manager.get_recent_chat_history(limit=10)
                        
                        context_msg = "System Notification: Connection was lost and just re-established. Here is the recent chat history to help you resume seamlessly:\n\n"
                        for entry in history:
                            sender = entry.get('sender', 'Unknown')
                            text = entry.get('text', '')
                            context_msg += f"[{sender}]: {text}\n"
                        
                        context_msg += "\nPlease acknowledge the reconnection to the user (e.g. 'I lost connection for a moment, but I'm back...') and resume what you were doing."
                        
                        print(f"[JARVIS DEBUG] [RECONNECT] Sending restoration context to model...")
                        await self.session.send(input=context_msg, end_of_turn=True)

                    # Reset retry delay on successful connection
                    retry_delay = 1
                    
                    # Wait until stop event, or until the session task group exits (which happens on error)
                    # Actually, the TaskGroup context manager will exit if any tasks fail/cancel.
                    # We need to keep this block alive.
                    # The original code just waited on stop_event, but that doesn't account for session death.
                    # We should rely on the TaskGroup raising an exception when subtasks fail (like receive_audio).
                    
                    # However, since receive_audio is a task in the group, if it crashes (connection closed), 
                    # the group will cancel others and exit. We catch that exit below.
                    
                    # We can await stop_event, but if the connection dies, receive_audio crashes -> group closes -> we exit `async with` -> restart loop.
                    # To ensure we don't block indefinitely if connection dies silently (unlikely with receive_audio), we just wait.
                    await self.stop_event.wait()
                    print("[JARVIS DEBUG] [STOP] Cancelling session tasks...")
                    for task in session_tasks:
                        if not task.done():
                            task.cancel()

            except asyncio.CancelledError:
                print(f"[JARVIS DEBUG] [STOP] Main loop cancelled.")
                break
                
            except Exception as e:
                # This catches the ExceptionGroup from TaskGroup or direct exceptions
                print(f"[JARVIS DEBUG] [ERR] Connection Error: {e}")
                
                if self.stop_event.is_set():
                    break
                
                print(f"[JARVIS DEBUG] [RETRY] Reconnecting in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10) # Exponential backoff capped at 10s
                is_reconnect = True # Next loop will be a reconnect
                
            finally:
                # Cleanup before retry
                if hasattr(self, 'audio_stream') and self.audio_stream:
                    try:
                        self.audio_stream.close()
                    except: 
                        pass
                    self.audio_stream = None
                if hasattr(self, 'output_audio_stream') and self.output_audio_stream:
                    try:
                        self.output_audio_stream.close()
                    except:
                        pass
                    self.output_audio_stream = None
                self.session = None

def get_input_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get('name')))
    p.terminate()
    return devices

def get_output_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxOutputChannels')) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get('name')))
    p.terminate()
    return devices

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        help="pixels to stream from",
        choices=["camera", "screen", "none"],
    )
    args = parser.parse_args()
    main = AudioLoop(video_mode=args.mode)
    asyncio.run(main.run())
