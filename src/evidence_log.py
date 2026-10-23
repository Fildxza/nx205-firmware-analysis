"""
evidence_log.py
---------------
A unified, append-only evidence log for the workstation.

It records real diagnostic events (one row per check executed) alongside the
manual connectivity observations kept by ``connectivity_tests``. Every row
carries a status drawn from the project's fixed vocabulary so the UI can never
blur real measurements with sample data:

    REAL         - measured/computed during an identified diagnostic session
    UNAVAILABLE  - the value could not be obtained (target did not respond)
    ERROR        - the diagnostic operation could not execute
    PLACEHOLDER  - sample data, not verified against the real device

The log persists to JSON and can be exported to CSV or JSON. It never trims or
rewrites existing rows, and it stores no credentials or secrets.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

STATUS_REAL = "REAL"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ERROR = "ERROR"
STATUS_PLACEHOLDER = "PLACEHOLDER"
_VALID_STATUS = {STATUS_REAL, STATUS_UNAVAILABLE, STATUS_ERROR, STATUS_PLACEHOLDER}

# Column order used for both the table and CSV export.
FIELDS = ["timestamp", "event_type", "target", "test_name",
          "status", "result", "source", "detail"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class EvidenceEvent:
    timestamp: str
    event_type: str          # diagnostics | observation | firmware | session
    target: str
    test_name: str
    status: str              # one of _VALID_STATUS
    result: str = ""         # short observed value, e.g. "0% loss, 3 ms"
    source: str = ""         # live-measurement | manual | file-analysis
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUS:
            raise ValueError(
                f"status must be one of {sorted(_VALID_STATUS)}, got {self.status!r}")

    def as_row(self) -> dict:
        return {k: getattr(self, k) for k in FIELDS}


class EvidenceLog:
    """Load/append/save evidence events, with CSV and JSON export."""

    def __init__(self, store_path: str) -> None:
        self.store_path = store_path
        self.events: List[EvidenceEvent] = []
        self.load()

    def load(self) -> None:
        self.events = []
        if not os.path.isfile(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return  # corrupt/empty log must not crash the app
        for item in raw:
            try:
                self.events.append(EvidenceEvent(**item))
            except (TypeError, ValueError):
                continue  # skip malformed rows, keep good ones

    def add(self, event: EvidenceEvent) -> None:
        self.events.append(event)

    def record(self, event_type: str, target: str, test_name: str, status: str,
               result: str = "", source: str = "", detail: str = "",
               timestamp: Optional[str] = None) -> EvidenceEvent:
        event = EvidenceEvent(
            timestamp=timestamp or _now(), event_type=event_type, target=target,
            test_name=test_name, status=status, result=result, source=source,
            detail=detail)
        self.add(event)
        return event

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as fh:
            json.dump([asdict(e) for e in self.events], fh, indent=2)

    def rows(self, newest_first: bool = True) -> List[dict]:
        rows = [e.as_row() for e in self.events]
        rows.sort(key=lambda r: r["timestamp"], reverse=newest_first)
        return rows

    def to_json(self, newest_first: bool = True) -> str:
        return json.dumps(self.rows(newest_first), indent=2)

    def to_csv(self, newest_first: bool = True) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS)
        writer.writeheader()
        for row in self.rows(newest_first):
            writer.writerow(row)
        return buffer.getvalue()

    def summary(self) -> dict:
        counts = {s: 0 for s in _VALID_STATUS}
        for e in self.events:
            counts[e.status] = counts.get(e.status, 0) + 1
        counts["total"] = len(self.events)
        return counts
