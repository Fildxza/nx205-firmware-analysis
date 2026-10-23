"""
file_detection.py
-----------------
Detect a file's format from its *signature* (magic bytes), not its extension.

The project rule is explicit: renaming a file to ``.bin`` does not make it valid
firmware. So detection here always reads the first bytes of the real file and
compares them against a small, well-documented signature table. Extension is
only used as a secondary hint and is reported separately so a mismatch is
visible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Signature table.
# Each entry: (offset, magic_bytes, short_id, human_description)
# Offsets are where the magic is expected within the file.
# ---------------------------------------------------------------------------
_SIGNATURES: List[Tuple[int, bytes, str, str]] = [
    (0, b"\x1f\x8b\x08", "gzip", "gzip compressed data"),
    (0, b"\xfd7zXZ\x00", "xz", "xz compressed data"),
    (0, b"\x28\xb5\x2f\xfd", "zstd", "zstandard compressed data"),
    (0, b"BZh", "bzip2", "bzip2 compressed data"),
    (0, b"%PDF", "pdf", "PDF document"),
    (0, b"PK\x03\x04", "zip", "ZIP archive"),
    (0, b"hsqs", "squashfs", "SquashFS filesystem (little-endian)"),
    (0, b"sqsh", "squashfs", "SquashFS filesystem (big-endian)"),
    (0, b"\x27\x05\x19\x56", "uimage", "U-Boot legacy uImage"),
    (0, b"\x45\x3d\xcd\x28", "cramfs", "cramfs filesystem"),
    (0, b"UBI#", "ubi", "UBI image"),
    (0, b"\x7fELF", "elf", "ELF executable / object"),
    (0, b"HDR0", "trx", "TRX firmware container"),
    (0, b"\xd0\x0d\xfe\xed", "dtb", "Flattened Device Tree blob"),
    (0, b"ANDROID!", "androidboot", "Android boot image"),
]

# TP-Link vendor upgrade images (the NX205 .bin) begin with this 4-byte marker
# followed by a proprietary, high-entropy header. This is NOT a generic format;
# it is TP-Link's own wrapper around a uImage/SquashFS payload.
_TPLINK_VENDOR_MAGIC = b"\x03\x00\x00\x03"


@dataclass
class DetectionResult:
    """Outcome of inspecting one file's signature."""

    path: str
    extension: str
    header_hex: str
    format_id: str                 # machine id, e.g. "tplink_vendor", "pdf"
    format_name: str               # human description
    is_supported: bool             # True if we positively recognised it
    confidence: str                # "high" | "medium" | "unknown"
    notes: List[str] = field(default_factory=list)

    @property
    def extension_matches_format(self) -> bool:
        """Rough sanity check: does the extension fit the detected format?"""
        ext = self.extension.lower().lstrip(".")
        mapping = {
            "pdf": {"pdf"},
            "zip": {"zip"},
            "gzip": {"gz", "tgz"},
            "xz": {"xz"},
        }
        expected = mapping.get(self.format_id)
        if expected is None:
            return True  # no strong expectation (e.g. .bin can hold anything)
        return ext in expected


def _read_header(path: str, length: int = 64) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(length)


def detect_file(path: str) -> DetectionResult:
    """
    Identify ``path`` by signature.

    Raises FileNotFoundError if the file is missing. Never executes the file;
    it only reads the first bytes.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    header = _read_header(path)
    header_hex = header[:16].hex(" ")
    ext = os.path.splitext(path)[1]
    notes: List[str] = []

    # 1) TP-Link vendor wrapper gets a dedicated, explicit classification.
    if header.startswith(_TPLINK_VENDOR_MAGIC):
        notes.append(
            "Proprietary TP-Link vendor header (not a generic archive). "
            "The real payload is wrapped and signed by the vendor."
        )
        return DetectionResult(
            path=path,
            extension=ext,
            header_hex=header_hex,
            format_id="tplink_vendor",
            format_name="TP-Link vendor firmware image (UP_ALL upgrade wrapper)",
            is_supported=True,
            confidence="high",
            notes=notes,
        )

    # 2) Generic signature table.
    for offset, magic, fmt_id, fmt_name in _SIGNATURES:
        if header[offset:offset + len(magic)] == magic:
            return DetectionResult(
                path=path,
                extension=ext,
                header_hex=header_hex,
                format_id=fmt_id,
                format_name=fmt_name,
                is_supported=True,
                confidence="high",
                notes=notes,
            )

    # 3) Nothing matched -> unknown. Report honestly instead of guessing.
    notes.append(
        "No known signature at offset 0. The extension alone does not prove "
        "the format; treat this file as unidentified."
    )
    return DetectionResult(
        path=path,
        extension=ext,
        header_hex=header_hex,
        format_id="unknown",
        format_name="Unknown / unrecognised",
        is_supported=False,
        confidence="unknown",
        notes=notes,
    )


def supported_formats() -> List[str]:
    """Human list of what the detector positively recognises."""
    names = {name for _, _, _, name in _SIGNATURES}
    names.add("TP-Link vendor firmware image (UP_ALL upgrade wrapper)")
    return sorted(names)
