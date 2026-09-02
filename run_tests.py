#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CapsStream Unified Test Runner
Discovers and executes all test suites under backend/tests/.
Usage:
    python run_tests.py
    python run_tests.py scanner
    python run_tests.py db
"""
import os
import sys
import time
import unittest

# Ensure project root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def run_all_tests(pattern="test_*.py"):
    print("=" * 70)
    print("CapsStream Test Suite Discovery & Runner")
    print(f"Directory: {os.path.join(BASE_DIR, 'backend', 'tests')}")
    print(f"Filter Pattern: {pattern}")
    print("=" * 70)

    loader = unittest.TestLoader()
    tests_dir = os.path.join(BASE_DIR, "backend", "tests")
    suite = loader.discover(start_dir=tests_dir, pattern=pattern, top_level_dir=BASE_DIR)

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("-" * 70)
    print(f"Ran {result.testsRun} tests in {elapsed:.3f}s")
    if result.wasSuccessful():
        print("ALL TESTS PASSED (100% OK)")
        return 0
    else:
        print(f"FAILED (failures={len(result.failures)}, errors={len(result.errors)})")
        return 1


if __name__ == "__main__":
    filter_arg = "test_*.py"
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if not arg.startswith("test_"):
            filter_arg = f"test_*{arg}*.py"
        else:
            filter_arg = f"{arg}*.py"

    exit_code = run_all_tests(filter_arg)
    sys.exit(exit_code)
