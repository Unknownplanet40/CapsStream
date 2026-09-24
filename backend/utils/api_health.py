"""Non-blocking, process-local health snapshots for metadata integrations."""
import hashlib
import logging
import os
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 120
_API_HEALTH_LOCK = threading.Lock()
_API_HEALTH_CACHE = {"key_fingerprint": None, "checked_at": 0.0, "data": None}
_API_HEALTH_REFRESHING = set()
_API_HEALTH_ACTIVE_KEY = None


def _probe_url(url, timeout=4):
    """Return (reachable, latency_ms). Any HTTP response counts as reachable."""
    start = time.monotonic()
    try:
        req = Request(url, headers={"User-Agent": "CapsStream-Diagnostics"})
        with urlopen(req, timeout=timeout) as response:
            response.read(256)
        return True, int((time.monotonic() - start) * 1000)
    except HTTPError:
        return True, int((time.monotonic() - start) * 1000)
    except Exception:
        return False, None


def _initial_health(tmdb_configured):
    return {
        "tmdb": {"status": "checking" if tmdb_configured else "unconfigured", "latency_ms": None},
        "aniskip": {"status": "checking", "latency_ms": None},
        "skipdb": {"status": "checking", "latency_ms": None},
        "poster_cache": {"status": "checking", "latency_ms": None},
    }


def _copy_health(data):
    return {name: dict(status) for name, status in data.items()}


def _refresh_health(tmdb_key, key_fingerprint, metadata_dir):
    try:
        health = {}
        if tmdb_key:
            ok, latency = _probe_url(f"https://api.themoviedb.org/3/configuration?api_key={tmdb_key}")
            health["tmdb"] = {"status": "ok" if ok else "error", "latency_ms": latency}
        else:
            health["tmdb"] = {"status": "unconfigured", "latency_ms": None}

        ok, latency = _probe_url("https://api.aniskip.com/v2/skip-times/21/1?types=op&episodeLength=0")
        health["aniskip"] = {"status": "ok" if ok else "error", "latency_ms": latency}

        ok, latency = _probe_url("https://skipdb.tv/api/segments?imdb_id=tt0903747&season=1&episode=1")
        health["skipdb"] = {"status": "ok" if ok else "error", "latency_ms": latency}

        try:
            os.makedirs(metadata_dir, exist_ok=True)
            health["poster_cache"] = {"status": "ok", "latency_ms": None}
        except Exception:
            health["poster_cache"] = {"status": "error", "latency_ms": None}

        with _API_HEALTH_LOCK:
            if _API_HEALTH_ACTIVE_KEY == key_fingerprint:
                _API_HEALTH_CACHE.update({"key_fingerprint": key_fingerprint, "checked_at": time.time(), "data": health})
    except Exception:
        logger.debug("Metadata health refresh failed", exc_info=True)
    finally:
        with _API_HEALTH_LOCK:
            _API_HEALTH_REFRESHING.discard(key_fingerprint)


def get_api_health_snapshot(config, base_dir):
    """Return a cached health snapshot immediately and refresh it in a daemon thread."""
    global _API_HEALTH_ACTIVE_KEY
    tmdb_key = (config.get("tmdb_api_key") or "").strip()
    key_fingerprint = hashlib.sha256(tmdb_key.encode("utf-8")).hexdigest()
    now = time.time()
    metadata_dir = os.path.join(base_dir, "data", "metadata")

    with _API_HEALTH_LOCK:
        _API_HEALTH_ACTIVE_KEY = key_fingerprint
        same_key = _API_HEALTH_CACHE["key_fingerprint"] == key_fingerprint
        data = _API_HEALTH_CACHE["data"] if same_key else None
        is_fresh = same_key and data is not None and now - _API_HEALTH_CACHE["checked_at"] < CACHE_TTL_SECONDS
        if is_fresh:
            return _copy_health(data)

        if key_fingerprint not in _API_HEALTH_REFRESHING:
            _API_HEALTH_REFRESHING.add(key_fingerprint)
            try:
                threading.Thread(
                    target=_refresh_health,
                    args=(tmdb_key, key_fingerprint, metadata_dir),
                    daemon=True,
                    name="capsstream-api-health",
                ).start()
            except Exception:
                _API_HEALTH_REFRESHING.discard(key_fingerprint)
                logger.debug("Could not start metadata health refresh", exc_info=True)

        return _copy_health(data if data is not None else _initial_health(bool(tmdb_key)))
