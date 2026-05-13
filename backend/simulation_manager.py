import json
from pathlib import Path
from threading import Lock


DEFAULT_SIMULATION_STATE = {
    "simulation_mode": False,
    "kasa_simulation": False,
    "printer_simulation": False,
}


class SimulationManager:
    """Persistent demo-mode switch used for TFG presentations without hardware."""

    def __init__(self, state_path=None):
        base_dir = Path(__file__).resolve().parent
        self.state_path = Path(state_path) if state_path else base_dir / "demo_state" / "simulation_state.json"
        self._lock = Lock()
        self._state = DEFAULT_SIMULATION_STATE.copy()
        self._load()

    def _load(self):
        if not self.state_path.exists():
            self._save()
            return

        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}

        self._state = DEFAULT_SIMULATION_STATE.copy()
        for key in DEFAULT_SIMULATION_STATE:
            self._state[key] = bool(loaded.get(key, DEFAULT_SIMULATION_STATE[key]))
        self._save()

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _set_state(self, **updates):
        with self._lock:
            for key, value in updates.items():
                if key in DEFAULT_SIMULATION_STATE:
                    self._state[key] = bool(value)
            self._save()
            return self.get_state()

    def activate_all(self):
        return self._set_state(
            simulation_mode=True,
            kasa_simulation=True,
            printer_simulation=True,
        )

    def deactivate_all(self):
        return self._set_state(
            simulation_mode=False,
            kasa_simulation=False,
            printer_simulation=False,
        )

    def activate_kasa(self):
        return self._set_state(simulation_mode=True, kasa_simulation=True)

    def activate_printers(self):
        return self._set_state(simulation_mode=True, printer_simulation=True)

    def is_simulation_enabled(self):
        return bool(self._state.get("simulation_mode"))

    def is_kasa_enabled(self):
        return bool(self._state.get("simulation_mode") and self._state.get("kasa_simulation"))

    def is_printer_enabled(self):
        return bool(self._state.get("simulation_mode") and self._state.get("printer_simulation"))

    def get_state(self):
        return {key: bool(self._state.get(key)) for key in DEFAULT_SIMULATION_STATE}


simulation_manager = SimulationManager()
