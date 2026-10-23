"""
main.py
-------
Entry point for FILDZA MOD ROUTER - a read-only NX205 firmware inspector.

Usage (Windows, from the project folder):
    python main.py                 # inspect the bundled firmware folder
    python main.py --path FILE     # inspect one specific file
    python main.py --dir FOLDER    # inspect a specific folder
    python main.py --no-color      # plain text (no ANSI colours)

This program never flashes, modifies, downgrades, decrypts, or executes any
firmware. It only reads files and prints what it finds. It does not touch the
router or any device identifier.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import firmware_inspector
from src import connectivity_tests, file_detection, ui
from src.firmware_analysis import FirmwareReport

# ---- Fixed facts about the target device (for compatibility checks) -------
DEVICE_NAME = "TP-Link Archer NX205(EU) V1"
DEVICE_REGION = "EU"
REPORTED_INSTALLED_BUILD = "251223"   # from device label (newer than package)

# Default locations inside the workspace.
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FIRMWARE_DIR = os.path.join(
    _HERE, "Archer_NX205(EU)_1.0_1.0.0_3.1.0_Build_250731"
)
REFERENCE_HASHES = os.path.join(_HERE, "data", "reference_hashes.json")
CONNECTIVITY_LOG = os.path.join(_HERE, "data", "connectivity_log.json")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_header() -> None:
    print(ui.banner())
    print(ui.kv("Target device", DEVICE_NAME))
    print(ui.kv("Device region", DEVICE_REGION))
    print(ui.kv("Reported installed", f"Build {REPORTED_INSTALLED_BUILD}"))


def render_file_report(report: FirmwareReport) -> None:
    det = report.detection
    print(ui.section(f"FILE: {report.filename}"))
    print(ui.kv("Size", report.hashes.size_human))
    print(ui.kv("Detected format", det.format_name, ok=det.is_supported))
    print(ui.kv("Confidence", det.confidence))
    print(ui.kv("Header (hex)", det.header_hex))
    print(ui.kv("Extension OK", "yes" if det.extension_matches_format else "mismatch",
                ok=det.extension_matches_format))
    print(ui.kv("SHA-256", report.hashes.sha256))
    print(ui.kv("MD5", report.hashes.md5))

    # Filename metadata
    meta = report.filename_meta
    if any([meta.device, meta.build, meta.region, meta.fw_version]):
        print(ui.kv("Parsed device", meta.device or "-"))
        print(ui.kv("Parsed region", meta.region or "-"))
        print(ui.kv("Parsed versions", meta.fw_version or "-"))
        print(ui.kv("Parsed build", meta.build or "-"))
        if meta.release:
            print(ui.kv("Parsed release", meta.release))

    # Deep firmware details
    if report.kernel_version:
        print(ui.kv("Kernel string", report.kernel_version))
    if report.embedded:
        print(ui.kv("Entropy", f"{report.entropy_bits} bits/byte"))
        print(ui.kv("Entropy reading", report.entropy_label))
        print(ui.note("Embedded components detected:", "info"))
        for hit in report.embedded:
            print("      "
                  + ui.amber(f"{hit.name}")
                  + f"  x{hit.count}  first@offset {hit.first_offset}")

    # Integrity
    status_kind = {
        "verified": "good",
        "mismatch": "bad",
        "no-reference": "warn",
    }.get(report.integrity_status, "info")
    print(ui.note(f"Integrity: {report.integrity_status.upper()} - "
                  f"{report.integrity_detail}", status_kind))

    # Detection notes
    for n in det.notes:
        print(ui.note(n, "info"))

    # Warnings
    for w in report.warnings:
        print(ui.note(w, "warn"))


def render_connectivity(log: connectivity_tests.ConnectivityLog) -> None:
    print(ui.section("CONNECTIVITY OBSERVATIONS (recorded, not live)"))
    summary = log.summary()
    tiles = "   ".join([
        ui.tile("total", str(summary["total"])),
        ui.tile("pass", str(summary["pass"]), "good"),
        ui.tile("fail", str(summary["fail"]), "bad"),
        ui.tile("partial", str(summary["partial"]), "warn"),
        ui.tile("not-tested", str(summary["not-tested"]), "info"),
    ])
    print("  " + tiles)
    if not log.observations:
        print(ui.note("No observations recorded yet.", "info"))
        return
    for obs in log.observations:
        kind = {"pass": "good", "fail": "bad",
                "partial": "warn", "not-tested": "info"}.get(obs.result, "info")
        print(ui.note(
            f"[{obs.result:<9}] {obs.test_name}  ({obs.interface})"
            + (f" - {obs.detail}" if obs.detail else ""), kind))


def render_feasibility() -> None:
    print(ui.section("CUSTOM FIRMWARE FEASIBILITY (vendor-supported build)"))
    lines = [
        ("bad", "NOT feasible to produce a flashable custom image from the "
                "materials in this package."),
        ("info", "The package contains: one signed TP-Link vendor upgrade "
                 "image (.bin), GPL license terms (PDF), and an upgrade guide "
                 "(PDF). It does NOT contain buildable source or a signing key."),
        ("info", "Technical blockers:"),
    ]
    for kind, text in lines:
        print(ui.note(text, kind))
    blockers = [
        "The .bin is a proprietary, vendor-signed wrapper (header magic "
        "03 00 00 03), not an open build artifact.",
        "TP-Link GPL releases cover only GPL components (kernel, BusyBox, "
        "etc.) - not the full build system, proprietary drivers, or packaging "
        "tool needed to assemble a complete image.",
        "The device verifies vendor signatures at boot/upgrade. Without "
        "TP-Link's private signing key (not public), a rebuilt image would be "
        "rejected.",
        "Modern Archer models enforce anti-rollback, so even the official "
        "older Build 250731 cannot be assumed installable over Build 251223.",
    ]
    for b in blockers:
        print(ui.note(b, "warn"))
    print(ui.note(
        "Legitimate paths: use TP-Link's official firmware + official upgrade "
        "procedure only, or request/download the GPL source to study and "
        "rebuild GPL components for research (not a flashable whole image).",
        "good"))


def render_safety_summary(results: List[firmware_inspector.InspectionResult]) -> None:
    print(ui.section("SUMMARY"))
    total = len(results)
    ok = sum(1 for r in results if not r.error)
    bins = sum(1 for r in results if not r.error
               and r.report.detection.format_id == "tplink_vendor")
    print("  " + "   ".join([
        ui.tile("files", str(total)),
        ui.tile("inspected", str(ok), "good"),
        ui.tile("firmware img", str(bins), "warn"),
    ]))
    print(ui.note(
        "Original files are preserved and unmodified. No flashing, no "
        "downgrade, no configuration change performed.", "good"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="FILDZA MOD ROUTER - read-only NX205 firmware inspector.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--path", help="Inspect a single file.")
    group.add_argument("--dir", help="Inspect a specific directory (recursive).")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colours (plain text output).")
    parser.add_argument("--only-firmware", action="store_true",
                        help="Only inspect .bin images.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    ui.enable_windows_vt()
    if args.no_color:
        ui.set_color(False)

    reference = REFERENCE_HASHES if os.path.isfile(REFERENCE_HASHES) else None

    render_header()

    # Gather inspection results.
    results: List[firmware_inspector.InspectionResult] = []
    if args.path:
        results.append(firmware_inspector.inspect_path(
            args.path, reference, DEVICE_REGION, REPORTED_INSTALLED_BUILD))
    else:
        target_dir = args.dir or DEFAULT_FIRMWARE_DIR
        if not os.path.isdir(target_dir):
            print(ui.note(f"Firmware folder not found: {target_dir}", "bad"))
            print(ui.note("Use --path FILE or --dir FOLDER to point at your "
                          "extracted firmware.", "info"))
            return 2
        results = firmware_inspector.inspect_directory(
            target_dir, reference, DEVICE_REGION, REPORTED_INSTALLED_BUILD,
            only_firmware=args.only_firmware)

    if not results:
        print(ui.note("No inspectable files found.", "warn"))

    for result in results:
        if result.error:
            print(ui.section(f"FILE: {result.report.filename}"))
            print(ui.note(result.error, "bad"))
        else:
            render_file_report(result.report)

    # Connectivity observations (recorded only).
    log = connectivity_tests.seed_example_log(CONNECTIVITY_LOG)
    render_connectivity(log)

    # Feasibility verdict + summary + footer.
    render_feasibility()
    render_safety_summary(results)
    print(ui.footer())
    return 0


if __name__ == "__main__":
    sys.exit(main())
