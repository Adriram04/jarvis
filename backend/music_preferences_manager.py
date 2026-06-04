import json
import os
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


DEFAULT_MOODS = {
    "programar": [],
    "entrenar": [],
    "relajarse": [],
}


def _default_volume():
    try:
        return max(0, min(100, int(os.getenv("JARVIS_MUSIC_DEFAULT_VOLUME", "50") or 50)))
    except Exception:
        return 50


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_list(value):
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",")]
    if not isinstance(value, list):
        return []
    seen = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


class MusicPreferencesManager:
    """Stores local music preferences and play history as JSON."""

    def __init__(self, storage_path=None, max_history=50):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "music_preferences.json"
        self.max_history = max_history
        self._lock = Lock()
        self._state = self._default_state()
        self._load()

    def _default_state(self):
        return {
            "favorite_artists": [],
            "favorite_genres": [],
            "moods": deepcopy(DEFAULT_MOODS),
            "history": [],
            "default_volume": _default_volume(),
        }

    # ------------------------------------------------------------------ public
    def get_preferences(self):
        with self._lock:
            return deepcopy(self._state)

    def update_preferences(self, payload):
        payload = payload or {}
        with self._lock:
            if "favorite_artists" in payload:
                self._state["favorite_artists"] = _clean_list(payload.get("favorite_artists"))
            if "favorite_genres" in payload:
                self._state["favorite_genres"] = _clean_list(payload.get("favorite_genres"))
            if "moods" in payload and isinstance(payload.get("moods"), dict):
                moods = deepcopy(DEFAULT_MOODS)
                for key, value in payload["moods"].items():
                    moods[str(key).strip() or "otros"] = _clean_list(value)
                self._state["moods"] = moods
            if "default_volume" in payload:
                try:
                    self._state["default_volume"] = max(0, min(100, int(payload.get("default_volume"))))
                except Exception:
                    pass
            self._save()
            return deepcopy(self._state)

    def add_history(self, entry):
        entry = dict(entry or {})
        entry.setdefault("played_at", _now_iso())
        with self._lock:
            history = self._state.get("history") or []
            history.insert(0, entry)
            self._state["history"] = history[: self.max_history]
            self._save()
            return deepcopy(entry)

    def get_history(self, limit=20):
        with self._lock:
            history = self._state.get("history") or []
            return deepcopy(history[: max(0, int(limit or 20))])

    def choose_random_query(self):
        """Picks a query+mode from favorite artists/genres/moods at random."""
        with self._lock:
            artists = list(self._state.get("favorite_artists") or [])
            genres = list(self._state.get("favorite_genres") or [])
            moods = {k: list(v or []) for k, v in (self._state.get("moods") or {}).items()}

        pool = []
        for artist in artists:
            pool.append({"query": artist, "mode": "artist"})
        for genre in genres:
            pool.append({"query": genre, "mode": "genre"})
        for mood_name, items in moods.items():
            if items:
                pool.append({"query": mood_name, "mode": "mood"})

        if not pool:
            return {"query": "", "mode": "random"}
        return deepcopy(random.choice(pool))

    def like_current(self, entry):
        """Promotes the current track's artist into favorites (best effort)."""
        entry = entry or {}
        artist = str(entry.get("artist") or entry.get("query") or "").strip()
        if not artist:
            return self.get_preferences()
        with self._lock:
            artists = self._state.get("favorite_artists") or []
            if artist not in artists:
                artists.append(artist)
                self._state["favorite_artists"] = artists
                self._save()
            return deepcopy(self._state)

    def dislike_current(self, entry):
        """Removes the current track's artist/query from favorites (best effort)."""
        entry = entry or {}
        target = str(entry.get("artist") or entry.get("query") or "").strip()
        if not target:
            return self.get_preferences()
        with self._lock:
            self._state["favorite_artists"] = [a for a in (self._state.get("favorite_artists") or []) if a != target]
            self._save()
            return deepcopy(self._state)

    # ------------------------------------------------------------- persistence
    def _load(self):
        if not self.storage_path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        state = self._default_state()
        state["favorite_artists"] = _clean_list(loaded.get("favorite_artists"))
        state["favorite_genres"] = _clean_list(loaded.get("favorite_genres"))
        moods = deepcopy(DEFAULT_MOODS)
        if isinstance(loaded.get("moods"), dict):
            for key, value in loaded["moods"].items():
                moods[str(key)] = _clean_list(value)
        state["moods"] = moods
        history = loaded.get("history")
        state["history"] = history[: self.max_history] if isinstance(history, list) else []
        try:
            state["default_volume"] = max(0, min(100, int(loaded.get("default_volume", _default_volume()))))
        except Exception:
            state["default_volume"] = _default_volume()
        self._state = state
        self._save()

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


music_preferences_manager = MusicPreferencesManager()
