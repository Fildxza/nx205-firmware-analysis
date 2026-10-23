"""
firmware_inspector.py
---------------------
Discover firmware-relevant files in a folder and run the read-only analysis
pipeline over each one. This is the orchestration layer sitting between the
low-level modules in ``src/`` and the console front-end in ``main.py``.

Safe by construction: it only walks directories and reads bytes. It never
writes to, deletes, renames, or executes any inspected file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from src import firmware_analysis

# Extensions we consider worth inspecting. ".bin" is the firmware image; PDFs
# are the bundled vendor documents. Anything else in the folder is listed but
# only lightly inspected.
_INSPECT_EXTENSIONS = {".bin", ".pdf", ".img", ".trx", ".w", ".zip"}


@dataclass
class InspectionResult:
    report: firmware_analysis.FirmwareReport
    error: Optional[str] = None


def find_files(root: str) -> List[str]:
    """Return absolute paths of files under ``root`` (recursive), sorted."""
    paths: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            paths.append(os.path.join(dirpath, name))
    return sorted(paths)


def _should_deep_inspect(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".bin"


def inspect_path(
    path: str,
    reference_path: Optional[str] = None,
    device_region: str = "EU",
    installed_build: Optional[str] = None,
) -> InspectionResult:
    """Analyse a single file, capturing errors instead of raising."""
    try:
        report = firmware_analysis.analyze(
            path,
            reference_path=reference_path,
            device_region=device_region,
            installed_build=installed_build,
            deep=_should_deep_inspect(path),
        )
        return InspectionResult(report=report)
    except FileNotFoundError:
        return _error_result(path, "File not found.")
    except PermissionError:
        return _error_result(path, "Permission denied while reading file.")
    except OSError as exc:
        return _error_result(path, f"OS error: {exc}")


def inspect_directory(
    root: str,
    reference_path: Optional[str] = None,
    device_region: str = "EU",
    installed_build: Optional[str] = None,
    only_firmware: bool = False,
) -> List[InspectionResult]:
    """
    Inspect every relevant file under ``root``.

    ``only_firmware=True`` restricts the scan to .bin images.
    """
    results: List[InspectionResult] = []
    for path in find_files(root):
        ext = os.path.splitext(path)[1].lower()
        if only_firmware and ext != ".bin":
            continue
        if ext not in _INSPECT_EXTENSIONS:
            continue
        results.append(
            inspect_path(path, reference_path, device_region, installed_build)
        )
    return results


def _error_result(path: str, message: str) -> InspectionResult:
    """Build a minimal result carrying only an error message."""
    # We cannot build a full report, so wrap a lightweight placeholder.
    class _Stub:
        pass

    stub = _Stub()
    stub.path = path  # type: ignore[attr-defined]
    stub.filename = os.path.basename(path)  # type: ignore[attr-defined]
    return InspectionResult(report=stub, error=message)  # type: ignore[arg-type]
