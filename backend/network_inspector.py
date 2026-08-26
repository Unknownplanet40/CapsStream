import time
import datetime
import threading
from collections import deque
from urllib.parse import urlparse

# Thread-safe ring buffer for last 200 outgoing requests
_LOCK = threading.Lock()
_BUFFER = deque(maxlen=200)
_COUNTER = 0
_INITIALIZED = False


def _detect_service(url):
    """Categorize the outgoing target into user-friendly services."""
    if not url:
        return "Unknown"
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if "themoviedb.org" in netloc or "tmdb.org" in netloc:
        if "image.tmdb.org" in netloc:
            return "TMDb CDN"
        return "TMDb API"
    if "opensubtitles" in netloc:
        return "OpenSubtitles"
    if "aniskip" in netloc:
        return "AniSkip"
    if "jikan.moe" in netloc:
        return "Jikan / MAL"
    if "github.com" in netloc or "githubusercontent.com" in netloc:
        return "GitHub"
    if "yts-subs" in netloc or "yifysubtitles" in netloc:
        return "YTS Subs"
    if "subdl" in netloc:
        return "SubDL"
    if "wikidata.org" in netloc or "wikipedia.org" in netloc:
        return "Wikidata"
    return netloc or "External HTTP"


def record_request(method, url, status_code, duration_ms, error=None, size_bytes=0):
    """Record an outgoing HTTP request into the ring buffer."""
    global _COUNTER
    now = datetime.datetime.now()
    service = _detect_service(url)

    with _LOCK:
        _COUNTER += 1
        entry = {
            "id": _COUNTER,
            "timestamp": now.strftime("%H:%M:%S"),
            "timestamp_full": now.isoformat(),
            "method": (method or "GET").upper(),
            "url": url,
            "service": service,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 1),
            "error": str(error) if error else None,
            "size_bytes": size_bytes or 0,
            "ok": bool(status_code and 200 <= status_code < 400 and not error),
        }
        _BUFFER.appendleft(entry)


def get_recorded_requests(limit=100, service_filter=None, status_filter=None):
    """Retrieve recorded requests with summary statistics."""
    with _LOCK:
        snapshot = list(_BUFFER)

    items = snapshot
    if service_filter and service_filter != "all":
        items = [i for i in items if i["service"].lower() == service_filter.lower()]

    if status_filter == "error":
        items = [i for i in items if not i["ok"]]
    elif status_filter == "success":
        items = [i for i in items if i["ok"]]

    limited_items = items[:limit]

    # Calculate summary metrics from the locked snapshot (never iterate _BUFFER directly)
    total = len(snapshot)
    success = sum(1 for i in snapshot if i["ok"])
    failed = total - success
    avg_latency = round(sum(i["duration_ms"] for i in snapshot) / total, 1) if total > 0 else 0

    return {
        "requests": limited_items,
        "summary": {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": round(100 * success / total, 1) if total > 0 else 100,
            "avg_latency_ms": avg_latency,
        },
    }


def clear_recorded_requests():
    """Clear the request ring buffer."""
    with _LOCK:
        _BUFFER.clear()
    return True


def init_network_inspector():
    """Monkey-patch requests and urllib.request to seamlessly record all outgoing HTTP calls."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    # 1. Hook requests.Session.send (covers all requests.get, requests.post, etc.)
    try:
        import requests.sessions

        _orig_session_send = requests.sessions.Session.send

        def _hooked_session_send(self, request, **kwargs):
            t0 = time.time()
            status_code = None
            error = None
            size_bytes = 0
            try:
                resp = _orig_session_send(self, request, **kwargs)
                status_code = resp.status_code
                try:
                    if hasattr(resp, "content"):
                        size_bytes = len(resp.content)
                except Exception:
                    pass
                return resp
            except Exception as exc:
                error = exc
                raise
            finally:
                duration_ms = (time.time() - t0) * 1000
                record_request(
                    method=getattr(request, "method", "GET"),
                    url=getattr(request, "url", ""),
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error=error,
                    size_bytes=size_bytes,
                )

        requests.sessions.Session.send = _hooked_session_send
    except Exception as e:
        print(f"[NetworkInspector] Failed to hook requests: {e}")

    # 2. Hook urllib.request.OpenerDirector.open (covers urllib.request.urlopen)
    try:
        import urllib.request

        _orig_opener_open = urllib.request.OpenerDirector.open

        def _hooked_opener_open(self, fullurl, data=None, timeout=None, **kwargs):
            t0 = time.time()
            status_code = None
            error = None
            size_bytes = 0
            url = fullurl.get_full_url() if hasattr(fullurl, "get_full_url") else str(fullurl)
            method = fullurl.get_method() if hasattr(fullurl, "get_method") else ("POST" if data else "GET")

            try:
                # Python OpenerDirector.open signature takes (self, fullurl, data=None, [timeout])
                if timeout is not None:
                    resp = _orig_opener_open(self, fullurl, data, timeout)
                else:
                    resp = _orig_opener_open(self, fullurl, data)
                status_code = getattr(resp, "status", getattr(resp, "code", 200))
                return resp
            except urllib.error.HTTPError as he:
                status_code = he.code
                error = str(he)
                raise
            except Exception as exc:
                error = exc
                raise
            finally:
                duration_ms = (time.time() - t0) * 1000
                record_request(
                    method=method,
                    url=url,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error=error,
                    size_bytes=size_bytes,
                )

        urllib.request.OpenerDirector.open = _hooked_opener_open
    except Exception as e:
        print(f"[NetworkInspector] Failed to hook urllib: {e}")
