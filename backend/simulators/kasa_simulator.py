import asyncio
from copy import deepcopy
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KasaSimulator:
    """Stable Kasa demo devices used when no physical smart-home hardware is present."""

    def __init__(self):
        self._initial_devices = {
            "192.168.1.41": {
                "ip": "192.168.1.41",
                "alias": "Luz escritorio demo",
                "name": "Luz escritorio demo",
                "model": "TP-Link KL130",
                "type": "bulb",
                "is_on": False,
                "brightness": 65,
                "hsv": {"h": 220, "s": 100, "v": 100},
                "color": "azul",
                "has_brightness": True,
                "has_color": True,
                "wifi_signal": -48,
                "energy_w": None,
            },
            "192.168.1.42": {
                "ip": "192.168.1.42",
                "alias": "Enchufe impresora demo",
                "name": "Enchufe impresora demo",
                "model": "TP-Link HS110",
                "type": "plug",
                "is_on": True,
                "brightness": None,
                "hsv": None,
                "color": None,
                "has_brightness": False,
                "has_color": False,
                "wifi_signal": -53,
                "energy_w": 84.6,
            },
            "192.168.1.43": {
                "ip": "192.168.1.43",
                "alias": "Tira LED setup demo",
                "name": "Tira LED setup demo",
                "model": "TP-Link KL430",
                "type": "strip",
                "is_on": False,
                "brightness": 45,
                "hsv": {"h": 190, "s": 100, "v": 100},
                "color": "cyan",
                "has_brightness": True,
                "has_color": True,
                "wifi_signal": -51,
                "energy_w": None,
            },
        }
        self.devices = {}
        self.last_operation_message = ""
        self.reset()

    def reset(self):
        self.devices = deepcopy(self._initial_devices)
        for device in self.devices.values():
            device["last_updated"] = _now_iso()
        self.last_operation_message = "Demo Kasa devices reset."

    async def _network_pause(self):
        await asyncio.sleep(0.2)

    def _device_payload(self, device):
        payload = deepcopy(device)
        if payload["type"] == "plug":
            payload["energy_w"] = 86.2 if payload["is_on"] else 0.0
        return payload

    def _resolve_device(self, target):
        target_text = str(target or "").strip().lower()
        if not target_text:
            return None

        if target_text in self.devices:
            return self.devices[target_text]

        for device in self.devices.values():
            alias = device["alias"].lower()
            name = device["name"].lower()
            if target_text in alias or target_text in name or alias in target_text or name in target_text:
                return device

        if "escritorio" in target_text:
            return self.devices["192.168.1.41"]
        if "enchufe" in target_text or "impresora" in target_text:
            return self.devices["192.168.1.42"]
        if "tira" in target_text or "led" in target_text or "setup" in target_text:
            return self.devices["192.168.1.43"]

        return None

    async def discover_devices(self):
        await self._network_pause()
        return self.get_all_states()

    async def turn_on(self, target):
        await self._network_pause()
        device = self._resolve_device(target)
        if not device:
            self.last_operation_message = f"Device '{target}' is not part of the demo set."
            return False
        device["is_on"] = True
        device["last_updated"] = _now_iso()
        self.last_operation_message = f"{device['alias']} encendida."
        return True

    async def turn_off(self, target):
        await self._network_pause()
        device = self._resolve_device(target)
        if not device:
            self.last_operation_message = f"Device '{target}' is not part of the demo set."
            return False
        device["is_on"] = False
        device["last_updated"] = _now_iso()
        self.last_operation_message = f"{device['alias']} apagada."
        return True

    async def set_brightness(self, target, brightness):
        await self._network_pause()
        device = self._resolve_device(target)
        if not device:
            self.last_operation_message = f"Device '{target}' is not part of the demo set."
            return False
        if not device["has_brightness"]:
            self.last_operation_message = f"{device['alias']} no soporta brillo."
            return False

        device["brightness"] = max(0, min(100, int(brightness)))
        device["is_on"] = True
        device["last_updated"] = _now_iso()
        self.last_operation_message = f"{device['alias']} brillo {device['brightness']}%."
        return True

    async def set_color(self, target, color):
        await self._network_pause()
        device = self._resolve_device(target)
        if not device:
            self.last_operation_message = f"Device '{target}' is not part of the demo set."
            return False
        if not device["has_color"]:
            self.last_operation_message = f"{device['alias']} no soporta color."
            return False

        hsv, color_name = self._parse_color(color)
        device["hsv"] = hsv
        device["color"] = color_name
        device["is_on"] = True
        device["last_updated"] = _now_iso()
        self.last_operation_message = f"{device['alias']} color {color_name}."
        return True

    def _parse_color(self, color):
        color_map = {
            "red": (0, 100, 100),
            "rojo": (0, 100, 100),
            "orange": (30, 100, 100),
            "naranja": (30, 100, 100),
            "yellow": (60, 100, 100),
            "amarillo": (60, 100, 100),
            "green": (120, 100, 100),
            "verde": (120, 100, 100),
            "cyan": (190, 100, 100),
            "azul": (220, 100, 100),
            "blue": (220, 100, 100),
            "purple": (285, 100, 100),
            "morado": (285, 100, 100),
            "pink": (320, 70, 100),
            "rosa": (320, 70, 100),
            "white": (0, 0, 100),
            "blanco": (0, 0, 100),
        }

        if isinstance(color, dict):
            h = int(color.get("h", color.get("hue", 190)))
            s = int(color.get("s", color.get("saturation", 100)))
            v = int(color.get("v", color.get("value", 100)))
            return {"h": h % 361, "s": max(0, min(100, s)), "v": max(0, min(100, v))}, "personalizado"

        if isinstance(color, (list, tuple)) and len(color) == 3:
            h, s, v = color
            return {
                "h": int(h) % 361,
                "s": max(0, min(100, int(s))),
                "v": max(0, min(100, int(v))),
            }, "personalizado"

        key = str(color or "cyan").lower().strip()
        h, s, v = color_map.get(key, color_map["cyan"])
        return {"h": h, "s": s, "v": v}, key if key in color_map else "cyan"

    def get_state(self, target):
        device = self._resolve_device(target)
        return self._device_payload(device) if device else None

    def get_all_states(self):
        return [self._device_payload(device) for device in self.devices.values()]


kasa_simulator = KasaSimulator()
