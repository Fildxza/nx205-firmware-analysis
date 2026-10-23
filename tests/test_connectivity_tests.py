"""Unit tests for src/connectivity_tests.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import connectivity_tests


class TestConnectivity(unittest.TestCase):
    def _tmp_store(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)  # start with no file
        return path

    def test_invalid_result_rejected(self):
        with self.assertRaises(ValueError):
            connectivity_tests.ConnectivityObservation("t", "banana")

    def test_record_and_roundtrip(self):
        path = self._tmp_store()
        try:
            log = connectivity_tests.ConnectivityLog(path)
            log.record("LAN reachable", "pass", interface="LAN",
                       detail="opened web UI", approved_by="tester")
            log.record("WAN 5G link", "partial", interface="WAN/5G")
            log.save()

            reloaded = connectivity_tests.ConnectivityLog(path)
            self.assertEqual(len(reloaded.observations), 2)
            summary = reloaded.summary()
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["pass"], 1)
            self.assertEqual(summary["partial"], 1)
        finally:
            if os.path.isfile(path):
                os.remove(path)

    def test_corrupt_file_does_not_crash(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write("{ this is not valid json ]")
        try:
            log = connectivity_tests.ConnectivityLog(path)
            self.assertEqual(log.observations, [])
        finally:
            os.remove(path)

    def test_seed_example_log(self):
        path = self._tmp_store()
        try:
            log = connectivity_tests.seed_example_log(path)
            self.assertGreater(len(log.observations), 0)
            # All seeded rows are clearly "not-tested" placeholders.
            self.assertTrue(all(o.result == "not-tested" for o in log.observations))
        finally:
            if os.path.isfile(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
