"""services/friday_car.py — OBD-II vehicle telemetry, read-only. Fed by an
ESP32 + Bluetooth ELM327 dongle riding in each car, posting to
POST /friday/car/report. Real sensor data in, real low-fuel/check-engine
alerts, no fabricated readings — same convention as friday_health.py.

OBD-II is a standardized diagnostics bus, not a control bus: this can
report fuel level, RPM, speed, coolant temp and trouble codes, but it
cannot lock, unlock, or start the vehicle — that's not exposed over the
public PID set on any car.
"""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
CAR_LOG = BASE_DIR / "memory" / "friday_car_log.json"

LOW_FUEL_THRESHOLD = 15.0  # percent


class FridayCarMonitor:

    def log_from_obd(self, vehicle: str, fuel_level: float = None, rpm: float = None,
                      speed: float = None, coolant_temp: float = None,
                      dtc_codes: list = None, voltage: float = None) -> dict:
        vehicle = (vehicle or "").strip()
        if not vehicle:
            return {"error": "vehicle name required"}

        dtc_codes = dtc_codes or []
        entry = {
            "vehicle": vehicle, "ts": datetime.now().isoformat(),
            "fuel_level": fuel_level, "rpm": rpm, "speed": speed,
            "coolant_temp": coolant_temp, "dtc_codes": dtc_codes, "voltage": voltage,
        }

        log = self._load()
        vehicle_log = log.setdefault(vehicle, {"entries": []})
        previous = vehicle_log["entries"][-1] if vehicle_log["entries"] else None
        vehicle_log["entries"].append(entry)
        vehicle_log["entries"] = vehicle_log["entries"][-2000:]
        self._save(log)

        self._check_alerts(entry, previous)
        return entry

    def get_status(self, vehicle: str = None) -> dict:
        log = self._load()
        if vehicle:
            entries = log.get(vehicle, {}).get("entries", [])
            return entries[-1] if entries else None
        return {
            name: (v["entries"][-1] if v.get("entries") else None)
            for name, v in log.items()
        }

    def _check_alerts(self, entry: dict, previous: dict):
        alerts = []

        fuel = entry.get("fuel_level")
        prev_fuel = previous.get("fuel_level") if previous else None
        if fuel is not None and fuel < LOW_FUEL_THRESHOLD and (prev_fuel is None or prev_fuel >= LOW_FUEL_THRESHOLD):
            alerts.append(f"Boss, {entry['vehicle']} is low on fuel — {fuel:.0f}% left.")

        prev_codes = set(previous.get("dtc_codes") or []) if previous else set()
        new_codes = set(entry.get("dtc_codes") or []) - prev_codes
        if new_codes:
            alerts.append(f"Boss, check engine light on {entry['vehicle']} — code{'s' if len(new_codes) > 1 else ''} {', '.join(sorted(new_codes))}.")

        if not alerts:
            return
        try:
            from services.friday_voice import speak
            for alert in alerts:
                speak(alert)
        except Exception:
            pass

    def _load(self) -> dict:
        if CAR_LOG.exists():
            try:
                return json.loads(CAR_LOG.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        CAR_LOG.parent.mkdir(parents=True, exist_ok=True)
        CAR_LOG.write_text(json.dumps(data, indent=2))


friday_car = FridayCarMonitor()
