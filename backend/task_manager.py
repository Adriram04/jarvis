"""Task & subtask manager shared between the HTTP layer (server.py) and the
live voice loop (jarvis.py).

A *task* is a process made of several *subtasks* (a checklist). Progress is
ALWAYS derived from the subtasks (completed / total), never set by hand. The
manager owns persistence (a local JSON file) and emits a Socket.IO event on
every mutation through an injected emitter, so the UI stays in sync whether the
change came from the dashboard or from a voice command.

It can also recommend an execution order for the pending subtasks, using Gemini
when available (reasoning about urgency, estimated time and logical
dependencies) and falling back to a deterministic heuristic otherwise.
"""

import os
import json
import time
import uuid
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional, List, Dict, Any

DEFAULT_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks_store.json")
VALID_PRIORITIES = ("low", "medium", "high")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize(text: str) -> str:
    """Lowercase + strip accents/punctuation for fuzzy name matching."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


class TaskManager:
    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self.store_path = Path(store_path)
        self._lock = RLock()
        self._tasks: List[Dict[str, Any]] = []
        self._emit_fn = None
        self._load()

    # ------------------------------------------------------------- wiring
    def set_emitter(self, emit_fn):
        """server.py injects ``lambda event, data: asyncio.create_task(sio.emit(event, data))``."""
        self._emit_fn = emit_fn

    def _emit_changed(self):
        if not self._emit_fn:
            return
        try:
            self._emit_fn("tasks_update", {"tasks": self.list_tasks()})
        except Exception as exc:  # never let emit break a mutation
            print(f"[TASKS] emit failed: {exc}")

    # ------------------------------------------------------------- persistence
    def _load(self):
        try:
            if self.store_path.exists():
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._tasks = data
                elif isinstance(data, dict):
                    self._tasks = data.get("tasks", [])
                print(f"[TASKS] Loaded {len(self._tasks)} task(s) from {self.store_path}")
        except Exception as exc:
            print(f"[TASKS] [WARN] Could not load store ({exc}); starting empty.")
            self._tasks = []

    def _save(self):
        try:
            tmp = self.store_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"tasks": self._tasks}, f, ensure_ascii=False, indent=2)
            tmp.replace(self.store_path)
        except Exception as exc:
            print(f"[TASKS] [ERR] Could not persist store: {exc}")

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _progress(task: Dict[str, Any]) -> int:
        subs = task.get("subtasks", [])
        if not subs:
            return 0
        done = sum(1 for s in subs if s.get("completed"))
        return round(100 * done / len(subs))

    def _decorate(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy with the always-computed progress + counters."""
        subs = task.get("subtasks", [])
        done = sum(1 for s in subs if s.get("completed"))
        return {
            **task,
            "progress": self._progress(task),
            "subtask_count": len(subs),
            "completed_count": done,
            "pending_count": len(subs) - done,
        }

    def _find(self, task_id: str) -> Optional[Dict[str, Any]]:
        return next((t for t in self._tasks if t["id"] == task_id), None)

    def find_task_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Resolve a task from a fuzzy spoken name (exact id, exact title,
        then substring match on the normalized title)."""
        if not name:
            return None
        target = _normalize(name)
        by_id = self._find(name)
        if by_id:
            return by_id
        exact = [t for t in self._tasks if _normalize(t["title"]) == target]
        if exact:
            return exact[0]
        partial = [t for t in self._tasks if target in _normalize(t["title"]) or _normalize(t["title"]) in target]
        return partial[0] if len(partial) >= 1 else None

    @staticmethod
    def _find_subtask_by_name(task: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
        if not task or not name:
            return None
        target = _normalize(name)
        subs = task.get("subtasks", [])
        by_id = next((s for s in subs if s["id"] == name), None)
        if by_id:
            return by_id
        exact = [s for s in subs if _normalize(s["title"]) == target]
        if exact:
            return exact[0]
        partial = [s for s in subs if target in _normalize(s["title"]) or _normalize(s["title"]) in target]
        return partial[0] if partial else None

    # ------------------------------------------------------------- task CRUD
    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._decorate(t) for t in self._tasks]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._find(task_id)
            return self._decorate(task) if task else None

    def create_task(self, title: str, description: str = "") -> Optional[Dict[str, Any]]:
        title = (title or "").strip()
        if not title:
            return None
        with self._lock:
            now = _now_iso()
            task = {
                "id": _new_id(),
                "title": title,
                "description": (description or "").strip(),
                "created_at": now,
                "updated_at": now,
                "subtasks": [],
            }
            self._tasks.append(task)
            self._save()
            self._emit_changed()
            return self._decorate(task)

    def update_task(self, task_id: str, *, title: Optional[str] = None, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._find(task_id)
            if not task:
                return None
            if title is not None and title.strip():
                task["title"] = title.strip()
            if description is not None:
                task["description"] = description.strip()
            task["updated_at"] = _now_iso()
            self._save()
            self._emit_changed()
            return self._decorate(task)

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._find(task_id)
            if not task:
                return False
            self._tasks.remove(task)
            self._save()
            self._emit_changed()
            return True

    # ------------------------------------------------------------- subtask CRUD
    def add_subtask(self, task_id: str, title: str, *, estimated_duration: Optional[str] = None,
                    priority: Optional[str] = None) -> Optional[Dict[str, Any]]:
        title = (title or "").strip()
        if not title:
            return None
        with self._lock:
            task = self._find(task_id)
            if not task:
                return None
            now = _now_iso()
            subtask = {
                "id": _new_id(),
                "title": title,
                "completed": False,
                "estimated_duration": (estimated_duration or "").strip() or None,
                "priority": priority if priority in VALID_PRIORITIES else None,
                "created_at": now,
                "updated_at": now,
            }
            task.setdefault("subtasks", []).append(subtask)
            task["updated_at"] = now
            self._save()
            self._emit_changed()
            return self._decorate(task)

    def update_subtask(self, task_id: str, subtask_id: str, *, title: Optional[str] = None,
                       completed: Optional[bool] = None, estimated_duration: Optional[str] = None,
                       priority: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._find(task_id)
            if not task:
                return None
            subtask = next((s for s in task.get("subtasks", []) if s["id"] == subtask_id), None)
            if not subtask:
                return None
            if title is not None and title.strip():
                subtask["title"] = title.strip()
            if completed is not None:
                subtask["completed"] = bool(completed)
            if estimated_duration is not None:
                subtask["estimated_duration"] = estimated_duration.strip() or None
            if priority is not None:
                subtask["priority"] = priority if priority in VALID_PRIORITIES else None
            subtask["updated_at"] = _now_iso()
            task["updated_at"] = subtask["updated_at"]
            self._save()
            self._emit_changed()
            return self._decorate(task)

    def delete_subtask(self, task_id: str, subtask_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._find(task_id)
            if not task:
                return None
            subs = task.get("subtasks", [])
            target = next((s for s in subs if s["id"] == subtask_id), None)
            if not target:
                return None
            subs.remove(target)
            task["updated_at"] = _now_iso()
            self._save()
            self._emit_changed()
            return self._decorate(task)

    # ------------------------------------------------------------- recommendation
    def _heuristic_order(self, pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        priority_rank = {"high": 0, "medium": 1, "low": 2, None: 3}

        def duration_minutes(value):
            # Best-effort parse of strings like "2h", "30 min", "1 dia".
            text = _normalize(value or "")
            num = "".join(ch for ch in text if ch.isdigit())
            n = int(num) if num else 999
            if "h" in text or "hora" in text:
                n *= 60
            elif "dia" in text or "day" in text:
                n *= 1440
            return n

        return sorted(
            pending,
            key=lambda s: (priority_rank.get(s.get("priority"), 3), duration_minutes(s.get("estimated_duration"))),
        )

    def recommend_order(self, task_id: str) -> Dict[str, Any]:
        """Recommend the order to tackle the pending subtasks. Uses Gemini when
        available, otherwise a deterministic priority/duration heuristic."""
        with self._lock:
            task = self._find(task_id)
            if not task:
                return {"success": False, "error": "Task not found."}
            pending = [s for s in task.get("subtasks", []) if not s.get("completed")]
            title = task["title"]

        if not pending:
            return {"success": True, "order": [], "message": "No hay subtareas pendientes.", "method": "none"}

        gemini = self._recommend_with_gemini(title, pending)
        if gemini:
            return gemini

        ordered = self._heuristic_order(pending)
        return {
            "success": True,
            "method": "heuristic",
            "order": [{"title": s["title"], "reason": self._heuristic_reason(s)} for s in ordered],
            "message": "Orden sugerido por prioridad y duración estimada.",
        }

    @staticmethod
    def _heuristic_reason(subtask: Dict[str, Any]) -> str:
        bits = []
        if subtask.get("priority"):
            bits.append(f"prioridad {subtask['priority']}")
        if subtask.get("estimated_duration"):
            bits.append(f"~{subtask['estimated_duration']}")
        return ", ".join(bits) or "sin metadatos adicionales"

    def _recommend_with_gemini(self, task_title: str, pending: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
            items = "\n".join(
                f"- {s['title']}"
                + (f" (prioridad: {s['priority']})" if s.get("priority") else "")
                + (f" (duracion estimada: {s['estimated_duration']})" if s.get("estimated_duration") else "")
                for s in pending
            )
            prompt = (
                f"Eres un asistente de planificacion. La tarea es: \"{task_title}\".\n"
                f"Estas son las subtareas pendientes:\n{items}\n\n"
                "Ordenalas en el orden mas logico para ejecutarlas, teniendo en cuenta urgencia, "
                "tiempo estimado y dependencias logicas (lo que conviene hacer antes que otra cosa). "
                "Devuelve SOLO un JSON con esta forma exacta: "
                '{\"order\": [{\"title\": \"...\", \"reason\": \"motivo breve\"}]}. '
                "Usa exactamente los mismos titulos que te he dado. Responde en espanol."
            )
            model = os.getenv("JARVIS_TASKS_MODEL", "gemini-2.5-flash")
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(resp.text)
            order = data.get("order") or []
            valid_titles = {_normalize(s["title"]) for s in pending}
            cleaned = [
                {"title": str(o.get("title", "")).strip(), "reason": str(o.get("reason", "")).strip()}
                for o in order
                if _normalize(o.get("title", "")) in valid_titles
            ]
            if not cleaned:
                return None
            return {
                "success": True,
                "method": "gemini",
                "order": cleaned,
                "message": "Orden recomendado por urgencia, tiempo y dependencias.",
            }
        except Exception as exc:
            print(f"[TASKS] [WARN] Gemini recommendation failed ({exc}); using heuristic.")
            return None


# Module-level singleton shared by server.py and jarvis.py.
task_manager = TaskManager()
