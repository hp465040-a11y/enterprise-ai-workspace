"""Offline parent deadline checks: fake clock/process; no child or service calls."""

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import investigation_api_c03_once as runner


class DeadlineTests(unittest.TestCase):
    def exercise(self, actions, *, initial_exit=None):
        clock = SimpleNamespace(now=0.0)
        process = MagicMock(pid=12345, returncode=initial_exit)
        process.poll.side_effect = lambda: process.returncode
        actions = iter(actions)

        def wait(*, timeout):
            advance, exit_code = next(actions)
            clock.now += advance
            if exit_code is None:
                raise subprocess.TimeoutExpired("controlled-child", timeout)
            process.returncode = exit_code
            return exit_code

        process.wait.side_effect = wait
        with (patch.object(runner.time, "monotonic", side_effect=lambda: clock.now),
              patch.object(runner, "stop_child_tree") as stop):
            result = runner.wait_for_child_deadline(process, timeout=690)
        return result, process, stop

    def test_normal_exit_before_deadline(self):
        result, process, stop = self.exercise([(1, None), (0.25, 0)])
        self.assertFalse(result["outer_timeout"])
        self.assertEqual(result["child_wait_elapsed_seconds"], 1.25)
        self.assertTrue(all(c.kwargs["timeout"] <= 1 for c in process.wait.call_args_list))
        stop.assert_not_called()

    def test_normal_nonzero_exit_is_not_outer_timeout(self):
        result, _, stop = self.exercise([(0.5, 1)])
        self.assertFalse(result["outer_timeout"])
        stop.assert_not_called()

    def test_running_child_at_deadline_stops_owned_tree(self):
        result, process, stop = self.exercise([(689.5, None), (0.5, None)])
        self.assertTrue(result["outer_timeout"])
        self.assertEqual(process.wait.call_args_list[-1].kwargs["timeout"], 0.5)
        stop.assert_called_once_with(process)
        self.assertEqual(result["child_timeout_seconds"], 690)

    def test_native_wait_returns_late_exit_without_timeout_exception(self):
        # Old code would leave timed_out=False because wait returned normally.
        result, _, stop = self.exercise([(51855, 1)])
        self.assertTrue(result["outer_timeout"])
        self.assertEqual(result["child_wait_elapsed_seconds"], 51855)
        self.assertFalse(result["child_tree_stop_requested"])
        stop.assert_not_called()

    def test_clock_jump_with_child_still_running_stops_on_resume(self):
        result, process, stop = self.exercise([(51855, None)])
        self.assertTrue(result["outer_timeout"])
        self.assertTrue(result["child_tree_stop_requested"])
        self.assertEqual(process.wait.call_count, 1)
        stop.assert_called_once_with(process)

    def test_exit_exactly_at_deadline_is_late_without_kill(self):
        result, _, stop = self.exercise([(690, 0)])
        self.assertTrue(result["outer_timeout"])
        stop.assert_not_called()
