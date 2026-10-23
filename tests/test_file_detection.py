"""Unit tests for src/file_detection.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import file_detection


def _write(data: bytes, suffix: str = ".bin") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return path


class TestFileDetection(unittest.TestCase):
    def test_tplink_vendor_header(self):
        path = _write(b"\x03\x00\x00\x03\x62\x00" + b"\x00" * 60)
        try:
            result = file_detection.detect_file(path)
            self.assertEqual(result.format_id, "tplink_vendor")
            self.assertTrue(result.is_supported)
            self.assertEqual(result.confidence, "high")
        finally:
            os.remove(path)

    def test_pdf_signature(self):
        path = _write(b"%PDF-1.7\n...", suffix=".pdf")
        try:
            result = file_detection.detect_file(path)
            self.assertEqual(result.format_id, "pdf")
            self.assertTrue(result.extension_matches_format)
        finally:
            os.remove(path)

    def test_gzip_signature(self):
        path = _write(b"\x1f\x8b\x08\x00\x00\x00")
        try:
            result = file_detection.detect_file(path)
            self.assertEqual(result.format_id, "gzip")
        finally:
            os.remove(path)

    def test_squashfs_signature(self):
        path = _write(b"hsqs" + b"\x00" * 60)
        try:
            self.assertEqual(file_detection.detect_file(path).format_id, "squashfs")
        finally:
            os.remove(path)

    def test_unknown_is_not_supported(self):
        path = _write(b"\xab\xcd\xef\x01random")
        try:
            result = file_detection.detect_file(path)
            self.assertEqual(result.format_id, "unknown")
            self.assertFalse(result.is_supported)
        finally:
            os.remove(path)

    def test_extension_mismatch_detected(self):
        # gzip bytes but a .pdf extension -> extension should flag as mismatch
        path = _write(b"\x1f\x8b\x08\x00", suffix=".pdf")
        try:
            result = file_detection.detect_file(path)
            self.assertEqual(result.format_id, "gzip")
            self.assertFalse(result.extension_matches_format)
        finally:
            os.remove(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            file_detection.detect_file("nope_missing_file.bin")


if __name__ == "__main__":
    unittest.main()
