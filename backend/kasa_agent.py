import asyncio
import platform
import sys

if sys.platform == "win32" and hasattr(platform, "_wmi_query"):
    # aiohttp imports platform.system() during python-kasa import. On some
    # Windows setups WMI can hang indefinitely, which blocks the backend import.
    def _jarvis_skip_wmi_query(*args, **kwargs):
        raise OSError("WMI query skipped by Jarvis to avoid Windows import hang.")

    platform._wmi_query = _jarvis_skip_wmi_query

from kasa import Discover, SmartDevice, SmartBulb, SmartPlug
from simulation_manager import simulation_manager
from simulators.kasa_simulator import kasa_simulator

class KasaAgent:
    def __init__(self, known_devices=None):
        self.devices = {}
        self.known_devices_config = known_devices or []
        self.simulation_manager = simulation_manager
        self.kasa_simulator = kasa_simulator

    async def initialize(self):
        """Initializes devices from the saved configuration."""
        if self.known_devices_config:
            print(f"[KasaAgent] Initializing {len(self.known_devices_config)} known devices...")
            tasks = []
            for d in self.known_devices_config:
                if not d: continue
                ip = d.get('ip')
                alias = d.get('alias')
                if ip:
                    # Create a device instance from IP
                    tasks.append(self._add_known_device(ip, alias, d))
            
            if tasks:
                await asyncio.gather(*tasks)

    async def _add_known_device(self, ip, alias, info):
        """Adds a device from settings without discovery scan."""
        try:
            # We can't know the exact class (Bulb/Plug) without connecting, 
            # but Discover.discover_single might work, or just SmartDevice(ip)
            # SmartDevice is the base class.
            dev = await Discover.discover_single(ip)
            if dev:
                await dev.update()
                self.devices[ip] = dev
                print(f"[KasaAgent] Loaded known device: {dev.alias} ({ip})")
            else:
                 print(f"[KasaAgent] Could not connect to known device at {ip}")
        except Exception as e:
            print(f"[KasaAgent] Error loading known device {ip}: {e}")

    async def discover_devices(self):
        """Discovers devices on the local network."""
        if self.simulation_manager.is_kasa_enabled():
            return await self.kasa_simulator.discover_devices()

        print("Discovering Kasa devices (Broadcast)...")
        # Use explicit broadcast and slightly longer timeout for Windows reliability
        found_devices = await Discover.discover(target="255.255.255.255", timeout=5)
        print(f"[KasaAgent] Raw discovery found {len(found_devices)} devices.")
        
        # We don't wipe self.devices completely, we merge/update
        # But if a device is NOT found, we might want to keep it if it was known?
        # User said: "If a device that is in settings can not be found just list as not found."
        # This implies we might want to mark them offline.
        
        for ip, dev in found_devices.items():
            await dev.update()
            self.devices[ip] = dev
            
        device_list = []
        for ip, dev in self.devices.items():
            # Determine type and capabilities
            dev_type = "unknown"
            if dev.is_bulb:
                dev_type = "bulb"
            elif dev.is_plug:
                dev_type = "plug"
            elif dev.is_strip:
                dev_type = "strip"
            elif dev.is_dimmer:
                dev_type = "dimmer"

            device_info = {
                "ip": ip,
                "alias": dev.alias,
                "model": dev.model,
                "type": dev_type,
                "is_on": dev.is_on,
                "brightness": dev.brightness if dev.is_bulb or dev.is_dimmer else None,
                "hsv": dev.hsv if dev.is_bulb and dev.is_color else None,
                "has_color": dev.is_color if dev.is_bulb else False,
                "has_brightness": dev.is_dimmable if dev.is_bulb or dev.is_dimmer else False
            }
            device_list.append(device_info)
            
        print(f"Total Kasa devices (found + cached): {len(device_list)}")
        return device_list

    def get_device_by_alias(self, alias):
        """Finds a device by its alias (case-insensitive)."""
        for ip, dev in self.devices.items():
            if dev.alias.lower() == alias.lower():
                return dev
        return None

    def _resolve_device(self, target):
        """Resolves a target string (IP or Alias) to a device object."""
        # check if it is an IP 
        if target in self.devices:
            return self.devices[target]
        
        # Check alias
        dev = self.get_device_by_alias(target)
        if dev:
            return dev
            
        return None

    def name_to_hsv(self, color_name):
        """Converts common color names to HSV (Hue, Saturation, Value).
           Hue: 0-360, Sat: 0-100, Val: 0-100
        """
        color_name = color_name.lower().strip()
        colors = {
            "red": (0, 100, 100),
            "orange": (30, 100, 100),
            "yellow": (60, 100, 100),
            "green": (120, 100, 100),
            "cyan": (180, 100, 100),
            "blue": (240, 100, 100),
            "purple": (300, 100, 100),
            "pink": (300, 50, 100),
            "white": (0, 0, 100),
            "warm": (30, 20, 100), # Warm White approx
            "cool": (200, 10, 100), # Cool White approx
            "daylight": (0, 0, 100),
        }
        return colors.get(color_name, None)

    async def turn_on(self, target):
        """Turns on the device (Target: IP or Alias)."""
        if self.simulation_manager.is_kasa_enabled():
            return await self.kasa_simulator.turn_on(target)

        dev = self._resolve_device(target)
        if dev:
            try:
                await dev.turn_on()
                await dev.update()
                return True
            except Exception as e:
                print(f"Error turning on {target}: {e}")
                return False
        
        # Fallback: Try to discover single if it looks like an IP
        if target.count(".") == 3:
             try:
                dev = await Discover.discover_single(target)
                if dev:
                    self.devices[target] = dev
                    await dev.turn_on()
                    await dev.update()
                    return True
             except Exception:
                 pass
        return False

    async def turn_off(self, target):
        """Turns off the device (Target: IP or Alias)."""
        if self.simulation_manager.is_kasa_enabled():
            return await self.kasa_simulator.turn_off(target)

        dev = self._resolve_device(target)
        if dev:
            try:
                await dev.turn_off()
                await dev.update()
                return True
            except Exception as e:
                print(f"Error turning off {target}: {e}")
                return False
        
        if target.count(".") == 3:
             try:
                dev = await Discover.discover_single(target)
                if dev:
                    self.devices[target] = dev
                    await dev.turn_off()
                    await dev.update()
                    return True
             except Exception:
                 pass
        return False

    async def set_brightness(self, target, brightness):
        """Sets brightness (0-100)."""
        if self.simulation_manager.is_kasa_enabled():
            return await self.kasa_simulator.set_brightness(target, brightness)

        dev = self._resolve_device(target)
        if dev and (dev.is_dimmable or dev.is_bulb):
            try:
                await dev.set_brightness(int(brightness))
                await dev.update()
                return True
            except Exception as e:
                 print(f"Error setting brightness for {target}: {e}")
        return False

    async def set_color(self, target, color_input):
        """Sets color by name or direct HSV tuple."""
        if self.simulation_manager.is_kasa_enabled():
            return await self.kasa_simulator.set_color(target, color_input)

        dev = self._resolve_device(target)
        if not dev or not dev.is_color:
            return False

        hsv = None
        if isinstance(color_input, str):
            hsv = self.name_to_hsv(color_input)
        elif isinstance(color_input, (tuple, list)) and len(color_input) == 3:
            hsv = color_input
        
        if hsv:
            try:
                # Kasa expects Hue (0-360), Sat (0-100), Val (0-100)
                await dev.set_hsv(int(hsv[0]), int(hsv[1]), int(hsv[2]))
                await dev.update()
                return True
            except Exception as e:
                 print(f"Error setting color for {target}: {e}")
        return False

    def get_state(self, target):
        if self.simulation_manager.is_kasa_enabled():
            return self.kasa_simulator.get_state(target)

        dev = self._resolve_device(target)
        if not dev:
            return None
        return self._device_to_info(dev.host if hasattr(dev, "host") else target, dev)

    def get_all_states(self):
        if self.simulation_manager.is_kasa_enabled():
            return self.kasa_simulator.get_all_states()
        return self.get_devices_list()

    def get_devices_list(self):
        device_list = []
        for ip, dev in self.devices.items():
            device_list.append(self._device_to_info(ip, dev))
        return device_list

    def _device_to_info(self, ip, dev):
        dev_type = "unknown"
        if dev.is_bulb:
            dev_type = "bulb"
        elif dev.is_plug:
            dev_type = "plug"
        elif dev.is_strip:
            dev_type = "strip"
        elif dev.is_dimmer:
            dev_type = "dimmer"

        return {
            "ip": ip,
            "alias": dev.alias,
            "name": dev.alias,
            "model": dev.model,
            "type": dev_type,
            "is_on": dev.is_on,
            "brightness": dev.brightness if dev.is_bulb or dev.is_dimmer else None,
            "hsv": dev.hsv if dev.is_bulb and dev.is_color else None,
            "has_color": dev.is_color if dev.is_bulb else False,
            "has_brightness": dev.is_dimmable if dev.is_bulb or dev.is_dimmer else False,
            "wifi_signal": None,
            "energy_w": None,
            "last_updated": None,
        }

# Standalone test
if __name__ == "__main__":
    async def main():
        agent = KasaAgent()
        await agent.discover_devices()
        print("Devices:", agent.devices)
        
        # Example Test
        # await agent.turn_on("Bedroom Light")
        # await agent.set_color("Bedroom Light", "Red")
    
    asyncio.run(main())
