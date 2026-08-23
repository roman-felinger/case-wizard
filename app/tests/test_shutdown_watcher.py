"""Unit tests for shutdown_watcher.py.

Scope: `start_once()`'s idempotency guard is the one thing here that's both
cheap and reliable to test without real threading/timing flakiness --
`threading.Thread` is mocked (never actually started), and the test asserts
it's only *constructed* once across two calls.

The watcher's actual grace-period/disconnect-detection loop (`_watch`,
defined as a closure inside `start_once`) is deliberately NOT unit-tested
here: it isn't exposed as a standalone function, it runs `time.sleep(2)` in
a real `while True` loop, and reaching it requires either running the real
background thread (racy/slow -- real sleeps, real thread timing) or
reimplementing the closure's logic against the source rather than the
source itself. Extracting the decision logic into a testable helper would
require a source change, which is out of scope here (see the task's own
allowance to keep this file's coverage light rather than write something
racy). The grace-period math is simple enough to be low-risk on inspection:
`disconnected_since` starts unset the first time zero sessions is observed
right after having seen >0, and `os._exit(0)` only fires once
`GRACE_PERIOD_S` has elapsed since then.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import shutdown_watcher


class StartOnceTests(unittest.TestCase):
    def setUp(self):
        # start_once's idempotency flag is module-global state; reload so
        # each test starts from a clean, unstarted watcher regardless of
        # what earlier tests (or an accidental real start) did to it.
        importlib.reload(shutdown_watcher)
        self.addCleanup(lambda: importlib.reload(shutdown_watcher))

    def test_first_call_constructs_and_starts_a_daemon_thread(self):
        with mock.patch.object(shutdown_watcher.threading, "Thread") as thread_cls:
            shutdown_watcher.start_once()
        thread_cls.assert_called_once()
        _, kwargs = thread_cls.call_args
        self.assertTrue(kwargs.get("daemon"))
        thread_cls.return_value.start.assert_called_once()

    def test_second_call_does_not_construct_a_second_thread(self):
        with mock.patch.object(shutdown_watcher.threading, "Thread") as thread_cls:
            shutdown_watcher.start_once()
            shutdown_watcher.start_once()
        thread_cls.assert_called_once()

    def test_sets_the_started_flag_after_the_first_call(self):
        self.assertFalse(shutdown_watcher._watcher_started)
        with mock.patch.object(shutdown_watcher.threading, "Thread"):
            shutdown_watcher.start_once()
        self.assertTrue(shutdown_watcher._watcher_started)


if __name__ == "__main__":
    unittest.main()
