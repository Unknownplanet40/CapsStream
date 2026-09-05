# -*- coding: utf-8 -*-
"""
backend/utils/supabase_client.py — Lightweight HTTP client for Supabase REST API (PostgREST).

Enables cross-network media request syncing between Desktop 1 (server/DEV) and Desktop 2 (client).
Uses standard library urllib (with requests fallback) to guarantee zero external dependency issues.
"""
import os
import json
import ssl
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any, Tuple


def get_supabase_config() -> Tuple[str, str]:
    """Retrieve Supabase URL and anon/public key from environment or config.json."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()

    if not url or not key:
        try:
            from backend.settings import load_config
            cfg = load_config()
            if not url:
                url = (cfg.get("supabase_url") or "").strip()
            if not key:
                key = (cfg.get("supabase_anon_key") or "").strip()
        except Exception:
            pass

    return url.rstrip("/"), key


def is_supabase_configured() -> bool:
    """Return True if both Supabase URL and anon key are present."""
    url, key = get_supabase_config()
    return bool(url and key and url.startswith("http"))


def _make_request(method: str, url: str, key: str, data: Optional[Any] = None, prefer: Optional[str] = None, timeout: float = 8.0) -> Tuple[int, Any]:
    """Execute an HTTP request against Supabase REST API using standard urllib."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "CapsStream/2.0"
    }
    if prefer:
        headers["Prefer"] = prefer

    body_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())

    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            status = response.status
            content = response.read().decode("utf-8")
            try:
                parsed = json.loads(content) if content else None
            except Exception:
                parsed = content
            return status, parsed
    except urllib.error.HTTPError as e:
        err_content = e.read().decode("utf-8", errors="ignore")
        try:
            err_parsed = json.loads(err_content)
        except Exception:
            err_parsed = err_content
        return e.code, err_parsed
    except Exception as e:
        return 0, str(e)


def test_supabase_connection(url: Optional[str] = None, key: Optional[str] = None) -> Tuple[bool, str]:
    """Test connectivity to Supabase and verify the media_requests table exists."""
    if not url or not key:
        url, key = get_supabase_config()

    url = (url or "").strip().rstrip("/")
    key = (key or "").strip()

    if not url or not key:
        return False, "Supabase URL and API Key are required."

    if not url.startswith("http://") and not url.startswith("https://"):
        return False, "Invalid Supabase URL scheme (must start with https://)."

    test_endpoint = f"{url}/rest/v1/media_requests?select=id&limit=1"
    status, res = _make_request("GET", test_endpoint, key=key, timeout=6.0)

    if status == 200:
        return True, "Connection successful! 'media_requests' table is accessible."
    elif status in (401, 403):
        return False, f"Authentication failed (HTTP {status}). Please verify your anon key."
    elif status == 404 or (isinstance(res, (str, dict)) and "not found" in str(res).lower()):
        return False, "Connected to Supabase, but the 'media_requests' table was not found. Please run docs/supabase_schema.sql."
    elif status == 0:
        return False, f"Network connection failed: {res}"
    else:
        return False, f"Supabase returned HTTP {status}: {str(res)[:150]}"


def fetch_online_requests(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch requests from Supabase.
    If client_id is provided, filters for that specific client (Desktop 2 client isolation).
    If client_id is None, fetches all requests (Desktop 1 DEV mode).
    """
    url, key = get_supabase_config()
    if not url or not key:
        return []

    endpoint = f"{url}/rest/v1/media_requests?select=*&order=created_at.desc"
    if client_id:
        endpoint += f"&client_id=eq.{client_id}"

    status, res = _make_request("GET", endpoint, key=key)
    if status == 200 and isinstance(res, list):
        return res
    print(f"[Supabase] fetch_online_requests status {status}: {str(res)[:200]}")
    return []


def upsert_online_request(req_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert or update a media request in Supabase."""
    url, key = get_supabase_config()
    if not url or not key:
        return None

    endpoint = f"{url}/rest/v1/media_requests"
    status, res = _make_request("POST", endpoint, key=key, data=req_data, prefer="resolution=merge-duplicates,return=representation")

    if status in (200, 201):
        if isinstance(res, list) and res:
            return res[0]
        return req_data
    print(f"[Supabase] upsert_online_request error HTTP {status}: {str(res)[:200]}")
    return None


def update_online_request(req_id: str, patch_data: Dict[str, Any], client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Update request fields in Supabase.
    If client_id is provided, ensures only the owning client can update the record.
    """
    url, key = get_supabase_config()
    if not url or not key:
        return None

    endpoint = f"{url}/rest/v1/media_requests?id=eq.{req_id}"
    if client_id:
        endpoint += f"&client_id=eq.{client_id}"

    status, res = _make_request("PATCH", endpoint, key=key, data=patch_data, prefer="return=representation")

    if status in (200, 204):
        if isinstance(res, list) and res:
            return res[0]
        return patch_data
    print(f"[Supabase] update_online_request error HTTP {status}: {str(res)[:200]}")
    return None


def delete_online_request(req_id: str, client_id: Optional[str] = None) -> bool:
    """
    Delete a request from Supabase.
    If client_id is provided, ensures the record belongs to the requesting client.
    """
    url, key = get_supabase_config()
    if not url or not key:
        return False

    endpoint = f"{url}/rest/v1/media_requests?id=eq.{req_id}"
    if client_id:
        endpoint += f"&client_id=eq.{client_id}"

    status, _ = _make_request("DELETE", endpoint, key=key)
    return status in (200, 204)
