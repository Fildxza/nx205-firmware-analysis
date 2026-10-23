"""Unit tests for src/evidence_log.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import evidence_log as ev


class TestEvidenceLog(unittest.TestCase):
    def _tmp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)
        return path

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            ev.EvidenceEvent("t", "diagnostics", "x", "y", "BOGUS")

    def test_record_roundtrip_and_summary(self):
        path = self._tmp()
        try:
            log = ev.EvidenceLog(path)
            log.record("diagnostics", "192.168.1.1", "Router ICMP",
                       ev.STATUS_REAL, "0% loss", "live-measurement")
            log.record("diagnostics", "8.8.8.8", "Internet ICMP",
                       ev.STATUS_UNAVAILABLE, "100% loss", "live-measurement")
            log.save()
            reloaded = ev.EvidenceLog(path)
            self.assertEqual(len(reloaded.events), 2)
            s = reloaded.summary()
            self.assertEqual(s["total"], 2)
            self.assertEqual(s[ev.STATUS_REAL], 1)
            self.assertEqual(s[ev.STATUS_UNAVAILABLE], 1)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_csv_export_has_header_and_rows(self):
        path = self._tmp()
        try:
            log = ev.EvidenceLog(path)
            log.record("diagnostics", "1.1.1.1", "DNS", ev.STATUS_REAL, "ok")
            csv_text = log.to_csv()
            lines = [l for l in csv_text.splitlines() if l.strip()]
            self.assertEqual(lines[0], ",".join(ev.FIELDS))
            self.assertIn("1.1.1.1", csv_text)
            self.assertIn("REAL", csv_text)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_json_export_is_sorted_newest_first(self):
        path = self._tmp()
        try:
            log = ev.EvidenceLog(path)
            log.record("diagnostics", "a", "t1", ev.STATUS_REAL,
                       timestamp="2026-01-01T00:00:00+00:00")
            log.record("diagnostics", "b", "t2", ev.STATUS_REAL,
                       timestamp="2026-02-01T00:00:00+00:00")
            rows = log.rows(newest_first=True)
            self.assertEqual(rows[0]["target"], "b")
            self.assertEqual(rows[1]["target"], "a")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_corrupt_file_does_not_crash(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write("not json {[}")
        try:
            log = ev.EvidenceLog(path)
            self.assertEqual(log.events, [])
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
