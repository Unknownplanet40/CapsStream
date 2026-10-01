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

    def test_silent_startupinfo_and_kwargs(self):
        """Verify silent_startupinfo and silent_kwargs configure SW_HIDE correctly on Windows."""
        si = proc_utils.silent_startupinfo()
        kwargs = proc_utils.silent_kwargs()

        if os.name == "nt":
            self.assertIsNotNone(si)
            import subprocess
            self.assertEqual(si.dwFlags & subprocess.STARTF_USESHOWWINDOW, subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(si.wShowWindow, 0)
            self.assertEqual(kwargs.get("creationflags"), proc_utils.CREATE_NO_WINDOW)
            self.assertIsNotNone(kwargs.get("startupinfo"))
            self.assertEqual(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW, subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)
            # Test extra flags combination
            extra_kwargs = proc_utils.silent_kwargs(extra_flags=proc_utils.BELOW_NORMAL_PRIORITY)
            self.assertEqual(
                extra_kwargs.get("creationflags"),
                proc_utils.CREATE_NO_WINDOW | proc_utils.BELOW_NORMAL_PRIORITY,
            )
        else:
            self.assertIsNone(si)
            self.assertEqual(kwargs, {})


if __name__ == "__main__":
    unittest.main()

