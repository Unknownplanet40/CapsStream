# -*- coding: utf-8 -*-
"""
Backward compatibility bridge for achievements integrity testing.
Delegates directly to backend/tests/test_achievements.py.
"""
import unittest
from backend.tests.test_achievements import TestAchievementsIntegrity

if __name__ == "__main__":
    unittest.main()
