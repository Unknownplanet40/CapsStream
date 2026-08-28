# -*- coding: utf-8 -*-
"""
Tests for Process Utilities Module (backend/proc_utils.py)
Covers Windows console suppression and below-normal priority flags.
"""
import os
import unittest

from backend import proc_utils


class TestProcUtils(unittest.TestCase):
    def test_creation_flags_types_and_values(self):
        """Verify CREATE_NO_WINDOW and BELOW_NORMAL_PRIORITY are integers matching OS conventions."""
        self.assertTrue(isinstance(proc_utils.CREATE_NO_WINDOW, int))
        self.assertTrue(isinstance(proc_utils.BELOW_NORMAL_PRIORITY, int))

        if os.name == "nt":
            self.assertEqual(proc_utils.CREATE_NO_WINDOW, 0x08000000)
            self.assertEqual(proc_utils.BELOW_NORMAL_PRIORITY, 0x00004000)
        else:
            self.assertEqual(proc_utils.CREATE_NO_WINDOW, 0)
            self.assertEqual(proc_utils.BELOW_NORMAL_PRIORITY, 0)


if __name__ == "__main__":
    unittest.main()
