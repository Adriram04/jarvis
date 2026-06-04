"""Music orchestrator shared between the HTTP layer (server.py) and the live
voice loop (jarvis.py).

It owns the provider + preferences and the *current playback intent* state. It
never plays audio; instead it emits Socket.IO events through an injected emitter
so the frontend YouTube embed can react. Both the HTTP endpoints and the voice
tools call the same singleton, keeping behaviour consistent everywhere.
"""

import os

from music_preferences_manager import music_preferences_manager

try:  # pragma: no cover - relative vs absolute import depending on entry point
    from integrations.youtube_music_provider import YouTubeMusicProvider
except ImportError:  # pragma: no cover
    from backend.integrations.youtube_music_provider import YouTubeMusicProvider


VALID_COMMANDS = {"pause", "resume", "stop", "next", "previous", "volume_up", "volume_down", "set_volume"}
VOLUME_STEP = 10


def _env_bool(name, default=True):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _clamp_volume(value, fallback=50):
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return fallback


class MusicManager:
    def __init__(self, provider=None, preferences=None):
        self.preferences = preferences or music_preferences_manager
        self.provider = provider or YouTubeMusicProvider(preferences_manager=self.preferences)
        self._emit_fn = None
        self.volume = _clamp_volume(self.preferences.get_preferences().get("default_volume", 50))
        self.playing = False
        self.current = {}

    # ------------------------------------------------------------- wiring
    def set_emitter(self, emit_fn):
        """server.py injects ``lambda event, data: asyncio.create_task(sio.emit(event, data))``."""
        self._emit_fn = emit_fn

    def _emit(self, event, data):
        if not self._emit_fn:
            return
        try:
            self._emit_fn(event, data)
        except Exception as exc:  # never let emit break the action
            print(f"[MUSIC] emit '{event}' failed: {exc}")

    def is_enabled(self):
        return _env_bool("JARVIS_MUSIC_ENABLED", True)

    def provider_name(self):
        return os.getenv("JARVIS_MUSIC_PROVIDER", "youtube").strip().lower() or "youtube"

    # ------------------------------------------------------------- playback
    async def play(self, query, mode="search"):
        if not self.is_enabled():
            return self._disabled("music")
        try:
            result = await self.provider.play(query, mode)
        except Exception as exc:
            return self._error(f"No pude preparar la reproduccion: {str(exc)[:200]}")

        payload = self._apply_and_payload(result)
        self.playing = True
        payload["playing"] = True
        self.preferences.add_history(
            {
                "query": payload.get("query"),
                "title": payload.get("title"),
                "provider": payload.get("provider"),
                "fallback": payload.get("fallback"),
                "mode": payload.get("mode"),
            }
        )
        self._emit("music_play", payload)
        return payload

    async def search(self, query, mode="search"):
        if not self.is_enabled():
            return self._disabled("music")
        try:
            return await self.provider.search(query, mode)
        except Exception as exc:
            return self._error(f"No pude buscar musica: {str(exc)[:200]}")

    async def random(self):
        choice = self.provider.random_from_preferences()
        return await self.play(choice.get("query", ""), choice.get("mode", "random"))

    def command(self, command, volume=None):
        command = str(command or "").strip().lower()
        if command not in VALID_COMMANDS:
            return self._error(f"Comando de musica no soportado: {command}")

        if command == "pause":
            self.playing = False
        elif command == "resume":
            self.playing = True
        elif command == "stop":
            self.playing = False
        elif command == "volume_up":
            self.volume = _clamp_volume(self.volume + VOLUME_STEP)
        elif command == "volume_down":
            self.volume = _clamp_volume(self.volume - VOLUME_STEP)
        elif command == "set_volume":
            self.volume = _clamp_volume(volume if volume is not None else self.volume)

        payload = {
            "success": True,
            "command": command,
            "volume": self.volume,
            "playing": self.playing,
            "status": self.status(),
        }
        self._emit("music_command", payload)
        return payload

    # ------------------------------------------------------------- state
    def status(self):
        return {
            "success": True,
            "enabled": self.is_enabled(),
            "provider": self.provider_name(),
            "has_api_key": bool(getattr(self.provider, "has_api_key", lambda: False)()),
            "volume": self.volume,
            "playing": self.playing,
            "current": dict(self.current),
        }

    def get_preferences(self):
        return self.preferences.get_preferences()

    def update_preferences(self, payload):
        updated = self.preferences.update_preferences(payload)
        if isinstance(payload, dict) and "default_volume" in payload:
            self.volume = _clamp_volume(updated.get("default_volume", self.volume))
        self._emit("music_status", self.status())
        return updated

    def get_history(self, limit=20):
        return self.preferences.get_history(limit=limit)

    # ------------------------------------------------------------- helpers
    def _apply_and_payload(self, result):
        result = dict(result or {})
        self.current = {
            "provider": result.get("provider", self.provider_name()),
            "mode": result.get("mode"),
            "query": result.get("query"),
            "title": result.get("title"),
            "url": result.get("url"),
            "embed_url": result.get("embed_url"),
            "video_id": result.get("video_id"),
            "fallback": bool(result.get("fallback")),
        }
        payload = dict(result)
        payload["volume"] = self.volume
        return payload

    def _disabled(self, action):
        payload = {
            "success": False,
            "provider": self.provider_name(),
            "enabled": False,
            "error": "El modulo de musica esta deshabilitado (JARVIS_MUSIC_ENABLED=false).",
            "action": action,
        }
        self._emit("music_error", payload)
        return payload

    def _error(self, message):
        payload = {"success": False, "provider": self.provider_name(), "error": message}
        self._emit("music_error", payload)
        return payload


music_manager = MusicManager()
