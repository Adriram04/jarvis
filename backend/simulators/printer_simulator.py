import asyncio
import math
import time
from copy import deepcopy
from datetime import datetime, timezone


HOTEND_TARGET = 210.0
BED_TARGET = 60.0
AMBIENT_HOTEND = 24.0
AMBIENT_BED = 25.0
HEATING_SECONDS = 7.0
DEFAULT_PRINT_SECONDS = 180.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


class PrinterSimulator:
    """Stable 3D-printer demo simulator for presentations without physical printers."""

    def __init__(self):
        self._initial_printers = {
            "192.168.1.80": {
                "name": "Creality K1 Demo",
                "host": "192.168.1.80",
                "port": 7125,
                "printer_type": "moonraker",
                "state": "idle",
                "filename": None,
                "progress_percent": 0.0,
            },
            "192.168.1.81": {
                "name": "OctoPrint Demo",
                "host": "192.168.1.81",
                "port": 5000,
                "printer_type": "octoprint",
                "state": "printing",
                "filename": "benchy_demo.gcode",
                "progress_percent": 20.0,
            },
        }
        self.printers = {}
        self.reset()

    def reset(self):
        now = time.monotonic()
        self.printers = deepcopy(self._initial_printers)
        for printer in self.printers.values():
            printer["_duration_seconds"] = DEFAULT_PRINT_SECONDS
            printer["_heating_started_at"] = None
            printer["_print_started_at"] = None
            printer["_elapsed_before_current"] = 0.0
            printer["_paused_from_state"] = None
            printer["last_updated"] = _now_iso()

            if printer["state"] == "printing":
                printer["_print_started_at"] = now
                printer["_elapsed_before_current"] = DEFAULT_PRINT_SECONDS * (printer["progress_percent"] / 100.0)

    async def _network_pause(self):
        await asyncio.sleep(0.25)

    def _resolve_printer(self, target):
        target_text = str(target or "").strip().lower()
        if not target_text:
            return None
        if target_text in self.printers:
            return self.printers[target_text]

        for printer in self.printers.values():
            name = printer["name"].lower()
            host = printer["host"].lower()
            if target_text == host or target_text in name or name in target_text:
                return printer

        if "creality" in target_text or "k1" in target_text:
            return self.printers["192.168.1.80"]
        if "octoprint" in target_text or "benchy" in target_text:
            return self.printers["192.168.1.81"]

        return None

    def _refresh_printer(self, printer):
        now = time.monotonic()
        state = printer["state"]

        if state == "heating":
            elapsed = now - (printer["_heating_started_at"] or now)
            if elapsed >= HEATING_SECONDS:
                printer["state"] = "printing"
                printer["_print_started_at"] = now
                printer["_heating_started_at"] = None

        if printer["state"] == "printing":
            started_at = printer["_print_started_at"] or now
            elapsed_total = printer["_elapsed_before_current"] + (now - started_at)
            progress = min(100.0, (elapsed_total / printer["_duration_seconds"]) * 100.0)
            printer["progress_percent"] = progress
            if progress >= 100.0:
                printer["state"] = "completed"
                printer["progress_percent"] = 100.0
                printer["_elapsed_before_current"] = printer["_duration_seconds"]
                printer["_print_started_at"] = None

        printer["last_updated"] = _now_iso()

    def _temperatures_for(self, printer):
        state = printer["state"]
        now = time.monotonic()

        if state == "heating":
            elapsed = now - (printer["_heating_started_at"] or now)
            ratio = max(0.0, min(1.0, elapsed / HEATING_SECONDS))
            hotend = AMBIENT_HOTEND + (HOTEND_TARGET - AMBIENT_HOTEND) * ratio
            bed = AMBIENT_BED + (BED_TARGET - AMBIENT_BED) * ratio
        elif state in {"printing", "paused"}:
            elapsed = printer["_elapsed_before_current"]
            if printer["_print_started_at"]:
                elapsed += now - printer["_print_started_at"]
            hotend = HOTEND_TARGET + math.sin(elapsed / 6.0) * 1.8
            bed = BED_TARGET + math.sin(elapsed / 9.0) * 0.8
        elif state == "completed":
            hotend = 72.0
            bed = 38.0
        else:
            hotend = AMBIENT_HOTEND
            bed = AMBIENT_BED

        return {
            "hotend": {"current": round(hotend, 1), "target": HOTEND_TARGET if state in {"heating", "printing", "paused"} else 0.0},
            "bed": {"current": round(bed, 1), "target": BED_TARGET if state in {"heating", "printing", "paused"} else 0.0},
        }

    def _elapsed_seconds(self, printer):
        elapsed = printer["_elapsed_before_current"]
        if printer["_print_started_at"]:
            elapsed += time.monotonic() - printer["_print_started_at"]
        return min(elapsed, printer["_duration_seconds"])

    def _status_payload(self, printer):
        self._refresh_printer(printer)
        elapsed = self._elapsed_seconds(printer)
        remaining = max(0.0, printer["_duration_seconds"] - elapsed)
        state = printer["state"]
        if state in {"idle", "cancelled"}:
            elapsed = 0.0
            remaining = 0.0

        return {
            "printer": printer["name"],
            "name": printer["name"],
            "host": printer["host"],
            "port": printer["port"],
            "printer_type": printer["printer_type"],
            "state": state,
            "filename": printer["filename"],
            "progress_percent": round(printer["progress_percent"], 1),
            "temperatures": self._temperatures_for(printer),
            "time_elapsed": _format_duration(elapsed),
            "time_remaining": _format_duration(remaining),
            "last_updated": printer["last_updated"],
        }

    async def discover_printers(self):
        await self._network_pause()
        return [
            {
                "name": status["name"],
                "host": status["host"],
                "port": status["port"],
                "printer_type": status["printer_type"],
                "status": status,
            }
            for status in self.get_all_printer_states()
        ]

    async def get_print_status(self, target):
        await self._network_pause()
        printer = self._resolve_printer(target)
        return self._status_payload(printer) if printer else None

    async def start_demo_print(self, target, filename="jarvis_demo_part.gcode"):
        await self._network_pause()
        printer = self._resolve_printer(target)
        if not printer:
            return None

        printer["state"] = "heating"
        printer["filename"] = filename or "jarvis_demo_part.gcode"
        printer["progress_percent"] = 0.0
        printer["_duration_seconds"] = DEFAULT_PRINT_SECONDS
        printer["_heating_started_at"] = time.monotonic()
        printer["_print_started_at"] = None
        printer["_elapsed_before_current"] = 0.0
        printer["_paused_from_state"] = None
        printer["last_updated"] = _now_iso()
        return self._status_payload(printer)

    async def pause_print(self, target):
        await self._network_pause()
        printer = self._resolve_printer(target)
        if not printer:
            return None
        self._refresh_printer(printer)
        if printer["state"] in {"heating", "printing"}:
            printer["_elapsed_before_current"] = self._elapsed_seconds(printer)
            printer["_print_started_at"] = None
            printer["_heating_started_at"] = None
            printer["_paused_from_state"] = printer["state"]
            printer["state"] = "paused"
            printer["last_updated"] = _now_iso()
        return self._status_payload(printer)

    async def resume_print(self, target):
        await self._network_pause()
        printer = self._resolve_printer(target)
        if not printer:
            return None
        if printer["state"] == "paused":
            printer["state"] = "printing"
            printer["_print_started_at"] = time.monotonic()
            printer["_paused_from_state"] = None
            printer["last_updated"] = _now_iso()
        return self._status_payload(printer)

    async def cancel_print(self, target):
        await self._network_pause()
        printer = self._resolve_printer(target)
        if not printer:
            return None
        self._refresh_printer(printer)
        printer["_elapsed_before_current"] = self._elapsed_seconds(printer)
        printer["_print_started_at"] = None
        printer["_heating_started_at"] = None
        printer["_paused_from_state"] = None
        printer["state"] = "cancelled"
        printer["last_updated"] = _now_iso()
        return self._status_payload(printer)

    def get_all_printer_states(self):
        return [self._status_payload(printer) for printer in self.printers.values()]


printer_simulator = PrinterSimulator()
