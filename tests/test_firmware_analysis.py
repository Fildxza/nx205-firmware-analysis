"""Unit tests for src/firmware_analysis.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import firmware_analysis


class TestFilenameParsing(unittest.TestCase):
    def test_parse_full_name(self):
        name = ("Archer_NX205_1.0.0_3.1.0_Build_250731_Rel.58442n_"
                "UP_ALL_A03_2025-07-31_16.30.09.bin")
        meta = firmware_analysis.parse_filename(name)
        self.assertIn("NX205", meta.device or "")
        self.assertEqual(meta.build, "250731")
        self.assertEqual(meta.release, "58442n")
        self.assertIsNotNone(meta.fw_version)

    def test_parse_region(self):
        meta = firmware_analysis.parse_filename(
            "Archer_NX205(EU)_1.0_1.0.0_3.1.0_Build_250731")
        self.assertEqual(meta.region, "EU")
        self.assertEqual(meta.build, "250731")


class TestEntropyAndEmbedded(unittest.TestCase):
    def test_entropy_zeros_is_low(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as h:
            h.write(b"\x00" * (1 << 20))
        try:
            self.assertLess(firmware_analysis.sample_entropy(path), 1.0)
        finally:
            os.remove(path)

    def test_entropy_random_is_high(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as h:
            h.write(os.urandom(1 << 20))
        try:
            self.assertGreater(firmware_analysis.sample_entropy(path), 7.5)
        finally:
            os.remove(path)

    def test_scan_embedded_finds_uimage(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as h:
            h.write(b"\x00" * 100 + b"\x27\x05\x19\x56" + b"\x00" * 100)
        try:
            hits = firmware_analysis.scan_embedded(path)
            names = {hit.name for hit in hits}
            self.assertIn("U-Boot uImage", names)
        finally:
            os.remove(path)

    def test_find_kernel_version(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as h:
            h.write(b"xxxx Linux-4.4.140 yyyy")
        try:
            self.assertEqual(
                firmware_analysis.find_kernel_version(path), "Linux-4.4.140")
        finally:
            os.remove(path)


class TestWarningsAndReference(unittest.TestCase):
    def test_downgrade_warning(self):
        meta = firmware_analysis.parse_filename("Archer_NX205(EU)_Build_250731")
        warnings = firmware_analysis.build_warnings(
            meta, device_region="EU", installed_build="251223")
        self.assertTrue(any("DOWNGRADE" in w for w in warnings))

    def test_region_mismatch_warning(self):
        meta = firmware_analysis.parse_filename("Archer_NX205(US)_Build_250731")
        warnings = firmware_analysis.build_warnings(meta, device_region="EU")
        self.assertTrue(any("Region mismatch" in w for w in warnings))

    def test_reference_no_file(self):
        status, _ = firmware_analysis.check_reference("abc", "x.bin", None)
        self.assertEqual(status, "no-reference")

    def test_reference_match_and_mismatch(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write('{"x.bin": "AABB"}')
        try:
            s1, _ = firmware_analysis.check_reference("aabb", "x.bin", path)
            self.assertEqual(s1, "verified")
            s2, _ = firmware_analysis.check_reference("ffff", "x.bin", path)
            self.assertEqual(s2, "mismatch")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
