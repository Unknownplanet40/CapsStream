#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/utorrent_hook.py — Shortcut runner for backend/utorrent_hook.py.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.utorrent_hook import main

if __name__ == "__main__":
    main()
