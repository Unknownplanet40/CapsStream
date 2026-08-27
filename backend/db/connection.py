"""
db.py — SQLite database schema, initialization, and query helpers for CapsStream.
"""

import hashlib
import hmac
import sqlite3
import os
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "capsstream.db")
TEMPLATE_DB_PATH = os.path.join(DATA_DIR, "templates", "fresh_capsstream.db")


def _apply_pragmas(conn):
    """Apply connection-scoped PRAGMAs once per connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")


class _RequestConnProxy:
    """
    Thin proxy around a SQLite connection that makes close() and standalone
    commit() calls no-ops when the connection is owned by the Flask request
    context.

    Why: every legacy DB helper ends with conn.commit(); conn.close().  With
    the new pooled approach that same object is reused across all DB calls in
    a single request.  If close() actually closed the socket, the next helper
    would raise "Cannot operate on a closed database".  Instead we swallow
    close() here and let release_conn() do the real commit+close at teardown.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    # Pass all attribute access through to the real connection
    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_conn"), name, value)

    # Make close() a no-op — release_conn() handles real teardown
    def close(self):
        pass

    # commit() is also a no-op inside request context; release_conn() commits
    def commit(self):
        pass

    # Context-manager support (used by `with get_conn() as conn:` patterns)
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass  # no-op close


def get_conn():
    """
    Return a SQLite connection with row_factory for dict-like access.

    Within a Flask request context the *same* connection is reused across all
    calls so we pay the open + 5 PRAGMA cost only once per request instead of
    once per DB helper call.  The returned object is a _RequestConnProxy whose
    close() and commit() methods are no-ops — the real commit+close happens in
    the teardown hook via release_conn().

    Outside a request context (background threads, startup) a plain fresh
    connection is returned each time (close() works normally).
    """
    try:
        from flask import g as _g
        proxy = getattr(_g, "_db_conn", None)
        if proxy is None:
            raw = sqlite3.connect(DB_PATH, timeout=30.0)
            raw.row_factory = sqlite3.Row
            _apply_pragmas(raw)
            proxy = _RequestConnProxy(raw)
            _g._db_conn = proxy
        return proxy
    except RuntimeError:
        # Outside an application context (background thread / startup)
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        return conn


def release_conn():
    """
    Commit and close the per-request connection stored in Flask g, if any.
    Called automatically by the teardown hook registered in app.py.
    """
    try:
        from flask import g as _g
        proxy = getattr(_g, "_db_conn", None)
        if proxy is not None:
            raw = object.__getattribute__(proxy, "_conn")
            try:
                raw.commit()
            except Exception:
                pass
            raw.close()
            _g._db_conn = None
    except RuntimeError:
        pass



