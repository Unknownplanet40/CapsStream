# -*- coding: utf-8 -*-
"""
CapsStream Backend Test Suite Package
Provides shared test fixtures, temporary in-memory database helpers, and mock utilities.
"""
import os
import sys
import tempfile
import sqlite3
from unittest.mock import MagicMock

# Ensure repo root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def create_isolated_test_db():
    """Create a temporary SQLite database initialized with the full CapsStream schema."""
    from backend.db.schema import init_db
    from backend.db import connection

    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()

    # Save original DB_PATH
    orig_db_path = connection.DB_PATH
    connection.DB_PATH = tmp_path

    # Initialize schema
    init_db()

    def cleanup():
        connection.DB_PATH = orig_db_path
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return tmp_path, cleanup
