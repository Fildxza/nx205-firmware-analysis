"""
hashing.py
----------
Compute file hashes. SHA-256 is the primary integrity value required by the
project; MD5 is offered too because TP-Link's older tooling and some mirrors
still publish MD5 sums for cross-checking.

The file is read in fixed-size chunks so that a very large image (the NX205
image is ~148 MB) is hashed without loading it all into memory.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

# 1 MiB read window keeps memory flat even for multi-hundred-MB images.
_CHUNK_SIZE = 1024 * 1024


@dataclass
class HashResult:
    """Hashes and basic size info for one file."""

    path: str
    size_bytes: int
    sha256: str
    md5: str

    @property
    def size_human(self) -> str:
        return human_size(self.size_bytes)


def human_size(num_bytes: int) -> str:
    """Return a human-friendly size string, e.g. 148036187 -> '141.18 MB'."""
    step = 1024.0
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= step
    return f"{num_bytes} B"  # pragma: no cover - unreachable


def sha256_file(path: str, chunk_size: int = _CHUNK_SIZE) -> str:
    """Return the lowercase hex SHA-256 digest of the file at ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_file(path: str, chunk_size: int = _CHUNK_SIZE) -> HashResult:
    """
    Compute SHA-256 and MD5 in a single pass over the file.

    Raises FileNotFoundError if the path does not exist, so callers can catch
    it and report the problem gracefully.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            sha.update(block)
            md5.update(block)
            size += len(block)

    return HashResult(
        path=path,
        size_bytes=size,
        sha256=sha.hexdigest(),
        md5=md5.hexdigest(),
    )
