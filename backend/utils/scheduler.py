"""
backend/utils/scheduler.py — Scan schedule persistence helpers.

Reads/writes data/scan_schedule.json so both the background scheduler
(app.py) and the admin API (routes/admin.py) share one implementation.

Previously _write_last_scheduled_scan() was duplicated in both files
with slightly different implementations (one used a module-level path
constant, the other computed the path inline via current_app.config).
"""
import os
import json
from backend.utils.paths import BASE_DIR

_SCAN_SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "scan_schedule.json")


def read_last_scheduled_scan() -> float:
    """Return the epoch timestamp of the last scheduled scan (0.0 if never run)."""
    try:
        with open(_SCAN_SCHEDULE_FILE, encoding="utf-8") as f:
            return float(json.load(f).get("last_run", 0))
    except Exception:
        return 0.0


def write_last_scheduled_scan(ts: float) -> None:
    """Persist *ts* as the last scheduled scan timestamp."""
    try:
        os.makedirs(os.path.dirname(_SCAN_SCHEDULE_FILE), exist_ok=True)
        with open(_SCAN_SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_run": ts}, f)
    except Exception:
        pass
