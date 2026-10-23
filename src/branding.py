"""
branding.py
-----------
Single source of truth for product identity, so the name is consistent across
the CLI, the static dashboard, the workstation web UI, and the docs.
"""

PRODUCT_NAME = "FILDZA MOD ROUTER"
PRODUCT_SUBTITLE = "NX205 Firmware Analysis & Network Diagnostics Workstation"
DEVELOPER = "Fildza"
VERSION = "2.0.0"

TARGET_DEVICE = "TP-Link Archer NX205(EU) V1"
TARGET_REGION = "EU"
TARGET_HW = "EU / 1.0 (V1)"
# Build reported on the physical device label (newer than the downloaded
# package). Used only for an informational downgrade warning; never acted on.
REPORTED_INSTALLED_BUILD = "251223"

# One-line safety banner reused wherever the UI needs it.
SAFETY_BANNER = (
    "Local analysis tool. It runs on this PC, is not installed on the router, "
    "and does not replace the stock TP-Link admin interface. Router checks are "
    "read-only and unauthenticated; it never flashes, modifies, downgrades, or "
    "reconfigures the device and never stores credentials."
)
