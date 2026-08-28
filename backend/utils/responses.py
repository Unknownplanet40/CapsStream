"""
backend/utils/responses.py — Standard Flask JSON response helpers.

Enforces a consistent envelope shape across all CapsStream API endpoints:
  Success:  {"ok": True, ...extra}
  Error:    {"error": "<message>", ...extra}

Use these helpers instead of bare jsonify({...}) in route handlers so
the frontend JavaScript always finds the same keys regardless of which
endpoint it's calling.

Migration note: existing jsonify({...}) calls are not broken — migrate
new/edited routes to api_ok / api_error going forward.
"""
from flask import jsonify
from typing import Any


def api_ok(**data: Any):
    """Return a 200 JSON response with ok=True plus any extra keyword fields."""
    return jsonify({"ok": True, **data})


def api_error(message: str, status: int = 400, **extra: Any):
    """Return a JSON error response with a consistent shape and HTTP status."""
    return jsonify({"error": message, **extra}), status
