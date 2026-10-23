"""Unit tests for src/hashing.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import hashing


class TestHashing(unittest.TestCase):
    def test_sha256_known_vector_empty(self):
        # SHA-256 of an empty input is a well-known constant.
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name
        try:
            self.assertEqual(
                hashing.sha256_file(path),
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )
        finally:
            os.remove(path)

    def test_sha256_known_vector_abc(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"abc")
            path = tmp.name
        try:
            self.assertEqual(
                hashing.sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
        finally:
            os.remove(path)

    def test_hash_file_fields(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"hello world")
            path = tmp.name
        try:
            result = hashing.hash_file(path)
            self.assertEqual(result.size_bytes, 11)
            self.assertEqual(len(result.sha256), 64)
            self.assertEqual(len(result.md5), 32)
            self.assertIn("B", result.size_human)
        finally:
            os.remove(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            hashing.hash_file("this_path_does_not_exist_12345.bin")

    def test_human_size(self):
        self.assertEqual(hashing.human_size(0), "0 B")
        self.assertEqual(hashing.human_size(1024), "1.00 KB")
        self.assertTrue(hashing.human_size(148036187).endswith("MB"))


if __name__ == "__main__":
    unittest.main()
