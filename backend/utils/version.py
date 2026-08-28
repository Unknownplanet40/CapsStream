"""
backend/utils/version.py — App version and dev-mode helpers.

Moving these here (instead of keeping them in app.py) eliminates the
`from app import is_dev_mode` layer violation in routes/admin.py and
provides a single source of truth for both helpers.

Previously:
  get_app_version() was defined in BOTH app.py AND routes/admin.py (exact copies).
  is_dev_mode()     was defined in app.py and imported by routes/admin.py via
                    `from app import is_dev_mode` — a blueprint→entrypoint violation.
"""
import os
from backend.utils.paths import BASE_DIR


def get_app_version() -> str:
    """Read the version from the VERSION file (fallback: '2.0.0.0')."""
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "2.0.0.0"
    except Exception:
        return "2.0.0.0"


def is_dev_mode() -> bool:
    """True when a local DEV file exists with a truthy development flag."""
    try:
        dev_file = os.path.join(BASE_DIR, "DEV")
        if os.path.isfile(dev_file):
            with open(dev_file, "r", encoding="utf-8") as f:
                val = f.read().strip().lower()
                return val in ("development", "dev", "true", "1", "yes", "on")
    except Exception:
        pass
    return False
