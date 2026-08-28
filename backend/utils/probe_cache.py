"""
backend/utils/probe_cache.py — Shared ffprobe result cache.

Avoids re-spawning ffprobe (slow over network storage) for the same file.
Keyed by (absolute_path, st_size, st_mtime) — invalidates automatically
when the file changes on disk.

Eviction is a simple bulk-clear once the dict exceeds _MAX entries —
cheap and sufficient for a local media server that will typically hold
a few hundred entries at most.

Previously implemented independently (with identical logic) in both:
  backend/audio_probe.py  — _PROBE_CACHE / _PROBE_CACHE_MAX
  backend/video_probe.py  — _PROBE_CACHE / _PROBE_CACHE_MAX
"""
from typing import Any, Optional

_STORE: dict = {}
_MAX: int = 4096


def get(key: tuple) -> Optional[Any]:
    """Return the cached result for *key*, or None if not present."""
    return _STORE.get(key)


def put(key: tuple, value: Any) -> None:
    """Store *value* under *key*, evicting all entries when capacity is exceeded."""
    if len(_STORE) >= _MAX:
        _STORE.clear()
    _STORE[key] = value


def clear() -> None:
    """Manually flush the entire cache (e.g. after a library rescan)."""
    _STORE.clear()
