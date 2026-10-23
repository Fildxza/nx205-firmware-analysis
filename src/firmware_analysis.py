"""
firmware_analysis.py
--------------------
Higher-level, still strictly read-only analysis of a firmware file:

  * parse the vendor filename for device / version / build / region metadata,
  * scan the image for embedded component signatures (uImage, SquashFS, ...),
  * extract the Linux kernel version string if present,
  * sample Shannon entropy to tell "compressed/encrypted" from "structured",
  * check the computed SHA-256 against an optional local reference list,
  * raise compatibility warnings (region, downgrade/anti-rollback).

Nothing here decrypts, unpacks, flashes, or executes anything. It reads bytes.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import file_detection, hashing

# ---------------------------------------------------------------------------
# Embedded signatures worth reporting. We deliberately skip very short (2-byte)
# magics such as raw JFFS2 markers because they produce large numbers of false
# positives in compressed data and would mislead the reader.
# ---------------------------------------------------------------------------
_EMBEDDED_MAGICS: List[Tuple[bytes, str]] = [
    (b"\x27\x05\x19\x56", "U-Boot uImage"),
    (b"hsqs", "SquashFS filesystem"),
    (b"\xfd7zXZ\x00", "xz payload"),
    (b"\x1f\x8b\x08", "gzip payload"),
    (b"\x45\x3d\xcd\x28", "cramfs filesystem"),
    (b"UBI#", "UBI volume"),
    (b"\xd0\x0d\xfe\xed", "Device Tree blob (FDT)"),
    (b"ANDROID!", "Android boot image"),
]

_KERNEL_RE = re.compile(rb"Linux-\d+\.\d+\.\d+")


@dataclass
class FilenameMeta:
    """Fields parsed out of a TP-Link firmware filename."""

    device: Optional[str] = None
    hw_version: Optional[str] = None
    fw_version: Optional[str] = None
    build: Optional[str] = None
    release: Optional[str] = None
    region: Optional[str] = None
    raw: str = ""


@dataclass
class EmbeddedHit:
    name: str
    count: int
    first_offset: int


@dataclass
class FirmwareReport:
    path: str
    filename: str
    detection: file_detection.DetectionResult
    hashes: hashing.HashResult
    filename_meta: FilenameMeta
    kernel_version: Optional[str]
    embedded: List[EmbeddedHit]
    entropy_bits: float
    entropy_label: str
    integrity_status: str          # "verified" | "mismatch" | "no-reference"
    integrity_detail: str
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------
def parse_filename(filename: str) -> FilenameMeta:
    """
    Pull metadata out of names such as:
        Archer_NX205_1.0.0_3.1.0_Build_250731_Rel.58442n_UP_ALL_A03_...bin
        Archer_NX205(EU)_1.0_1.0.0_3.1.0_Build_250731
    Missing fields simply stay None.
    """
    meta = FilenameMeta(raw=filename)
    base = os.path.basename(filename)

    device = re.search(r"(Archer[_ ]?[A-Z]+\d+)", base, re.IGNORECASE)
    if device:
        meta.device = device.group(1).replace("_", " ")

    region = re.search(r"\(([A-Z]{2})\)", base)
    if region:
        meta.region = region.group(1)

    build = re.search(r"Build[_ ]?(\d{6})", base, re.IGNORECASE)
    if build:
        meta.build = build.group(1)

    release = re.search(r"Rel\.?([0-9a-zA-Z]+)", base)
    if release:
        meta.release = release.group(1)

    # Version tokens (e.g. 1.0.0, 3.1.0) appear before the "Build" keyword.
    # NOTE: underscores are word characters, so \b does not sit between "_" and
    # a digit; using \b here would miss "_1.0.0_". Instead we scan only the
    # segment before "Build" (no \b), which also avoids catching timestamp
    # fragments such as "16.30.09".
    pre_build = re.split(r"[Bb]uild", base, maxsplit=1)[0]
    versions = re.findall(r"\d+\.\d+(?:\.\d+)?", pre_build)
    # Prefer full x.y.z tokens; fall back to whatever was found otherwise.
    full = [v for v in versions if v.count(".") >= 2]
    versions = full or versions
    if versions:
        meta.fw_version = " / ".join(versions[:3])

    hw = re.search(r"_(\d\.\d)_\d", base)
    if hw:
        meta.hw_version = hw.group(1)

    return meta


# ---------------------------------------------------------------------------
# Embedded component scan
# ---------------------------------------------------------------------------
def scan_embedded(path: str, chunk_size: int = 8 << 20) -> List[EmbeddedHit]:
    """Count occurrences and first offset of each embedded magic."""
    counts: Dict[str, int] = {}
    first: Dict[str, int] = {}
    max_len = max(len(m) for m, _ in _EMBEDDED_MAGICS)

    with open(path, "rb") as handle:
        offset = 0
        carry = b""
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            buffer = carry + chunk
            for magic, name in _EMBEDDED_MAGICS:
                start = buffer.find(magic)
                while start != -1:
                    absolute = offset - len(carry) + start
                    counts[name] = counts.get(name, 0) + 1
                    first.setdefault(name, absolute)
                    start = buffer.find(magic, start + 1)
            # keep a tail so a magic split across chunk boundary is not missed
            carry = chunk[-(max_len - 1):]
            offset += len(chunk)

    hits = [EmbeddedHit(name=n, count=counts[n], first_offset=first[n]) for n in counts]
    hits.sort(key=lambda h: h.first_offset)
    return hits


def find_kernel_version(path: str, window: int = 1 << 16) -> Optional[str]:
    """Look for a 'Linux-x.y.z' string in the first ``window`` bytes."""
    with open(path, "rb") as handle:
        head = handle.read(window)
    match = _KERNEL_RE.search(head)
    return match.group().decode("ascii", "replace") if match else None


# ---------------------------------------------------------------------------
# Entropy sampling
# ---------------------------------------------------------------------------
def sample_entropy(path: str, samples: int = 4, window: int = 1 << 20) -> float:
    """
    Average Shannon entropy (bits/byte) over a few evenly spaced windows.
    ~8.0 means random (encrypted or already compressed); lower means more
    structured/plaintext content.
    """
    size = os.path.getsize(path)
    if size == 0:
        return 0.0
    positions = []
    if size <= window:
        positions = [0]
    else:
        step = max(1, (size - window) // max(1, samples - 1))
        positions = [min(size - window, i * step) for i in range(samples)]

    total = 0.0
    used = 0
    with open(path, "rb") as handle:
        for pos in positions:
            handle.seek(pos)
            block = handle.read(window)
            if not block:
                continue
            counter = Counter(block)
            length = len(block)
            entropy = -sum((c / length) * math.log2(c / length) for c in counter.values())
            total += entropy
            used += 1
    return round(total / used, 3) if used else 0.0


def _entropy_label(bits: float) -> str:
    if bits >= 7.9:
        return "very high (random - encrypted or fully compressed)"
    if bits >= 7.0:
        return "high (compressed payloads present)"
    if bits >= 5.0:
        return "mixed (headers/metadata plus compressed data)"
    return "low (mostly structured / plaintext)"


# ---------------------------------------------------------------------------
# Integrity reference check
# ---------------------------------------------------------------------------
def check_reference(
    sha256: str, filename: str, reference_path: Optional[str]
) -> Tuple[str, str]:
    """
    Compare the computed SHA-256 against a local JSON of known-good hashes.

    The JSON maps filename -> expected sha256. We never ship a fabricated
    "official" hash; if the user has not supplied one, we say so plainly.
    """
    if not reference_path or not os.path.isfile(reference_path):
        return (
            "no-reference",
            "No local reference hash on file. Obtain the official SHA-256 from "
            "TP-Link's download page and add it to data/reference_hashes.json "
            "to verify authenticity.",
        )
    try:
        with open(reference_path, "r", encoding="utf-8") as handle:
            table = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        return ("no-reference", f"Could not read reference file: {exc}")

    expected = table.get(os.path.basename(filename))
    if not expected:
        return (
            "no-reference",
            "Filename not present in the reference list; cannot verify.",
        )
    if expected.lower() == sha256.lower():
        return ("verified", "SHA-256 matches the stored reference hash.")
    return (
        "mismatch",
        "SHA-256 does NOT match the stored reference. Do not trust or flash "
        "this file until the discrepancy is explained.",
    )


# ---------------------------------------------------------------------------
# Compatibility / safety warnings
# ---------------------------------------------------------------------------
def build_warnings(
    meta: FilenameMeta,
    device_region: str = "EU",
    installed_build: Optional[str] = None,
) -> List[str]:
    """Produce honest compatibility notes. This NEVER authorises a flash."""
    warnings: List[str] = []

    if meta.region and device_region and meta.region != device_region:
        warnings.append(
            f"Region mismatch: image region '{meta.region}' vs device region "
            f"'{device_region}'. Cross-region images are not compatible."
        )

    if installed_build and meta.build:
        try:
            if int(meta.build) < int(installed_build):
                warnings.append(
                    f"This package (Build {meta.build}) is OLDER than the "
                    f"reported installed firmware (Build {installed_build}). "
                    "Installing it would be a DOWNGRADE; modern TP-Link devices "
                    "enforce anti-rollback and may reject or be harmed by it. "
                    "Do not downgrade."
                )
            elif int(meta.build) > int(installed_build):
                warnings.append(
                    f"This package (Build {meta.build}) is newer than the "
                    f"reported installed firmware (Build {installed_build})."
                )
        except ValueError:
            pass

    warnings.append(
        "This tool does not flash, modify, or verify device compatibility for "
        "installation. Confirmed hardware compatibility and a vendor-supported "
        "recovery procedure are required before any legitimate firmware install."
    )
    return warnings


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------
def analyze(
    path: str,
    reference_path: Optional[str] = None,
    device_region: str = "EU",
    installed_build: Optional[str] = None,
    deep: bool = True,
) -> FirmwareReport:
    """
    Full read-only analysis of one file. ``deep=False`` skips the whole-file
    embedded scan (useful for quick runs or non-firmware files like PDFs).
    """
    detection = file_detection.detect_file(path)
    hashes = hashing.hash_file(path)
    meta = parse_filename(path)

    kernel = None
    embedded: List[EmbeddedHit] = []
    entropy = 0.0

    # Only do the heavy scan for things that could actually be firmware images.
    firmware_like = detection.format_id in {
        "tplink_vendor", "uimage", "squashfs", "trx", "ubi", "unknown",
    }
    if deep and firmware_like:
        kernel = find_kernel_version(path)
        embedded = scan_embedded(path)
        entropy = sample_entropy(path)

    integrity_status, integrity_detail = check_reference(
        hashes.sha256, path, reference_path
    )

    return FirmwareReport(
        path=path,
        filename=os.path.basename(path),
        detection=detection,
        hashes=hashes,
        filename_meta=meta,
        kernel_version=kernel,
        embedded=embedded,
        entropy_bits=entropy,
        entropy_label=_entropy_label(entropy) if entropy else "not sampled",
        integrity_status=integrity_status,
        integrity_detail=integrity_detail,
        warnings=build_warnings(meta, device_region, installed_build),
    )
