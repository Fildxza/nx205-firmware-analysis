"""
connectivity_tests.py
---------------------
Record *observations* from approved connectivity / hotspot tests.

Important scope: this module is a logbook, not a network actor. It does NOT
connect to the router, change any router or hotspot setting, probe carrier
APNs, or alter device identity. A human performs an approved test manually and
then records what they observed here. Observations persist to a local JSON
file so they can be reviewed later.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

_VALID_RESULTS = {"pass", "fail", "partial", "not-tested"}


@dataclass
class ConnectivityObservation:
    """One recorded, human-observed connectivity test result."""

    test_name: str
    result: str                      # one of _VALID_RESULTS
    interface: str = "unspecified"   # e.g. "2.4GHz Wi-Fi", "5GHz", "WAN/5G"
    detail: str = ""
    approved_by: str = "unspecified"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if self.result not in _VALID_RESULTS:
            raise ValueError(
                f"result must be one of {sorted(_VALID_RESULTS)}, got {self.result!r}"
            )


class ConnectivityLog:
    """Load, add to, and save a list of connectivity observations (JSON)."""

    def __init__(self, store_path: str) -> None:
        self.store_path = store_path
        self.observations: List[ConnectivityObservation] = []
        self.load()

    def load(self) -> None:
        self.observations = []
        if not os.path.isfile(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, OSError):
            # Corrupt/empty log should not crash the app; start fresh in memory.
            return
        for item in raw:
            try:
                self.observations.append(ConnectivityObservation(**item))
            except (TypeError, ValueError):
                continue  # skip malformed rows, keep the good ones

    def add(self, observation: ConnectivityObservation) -> None:
        self.observations.append(observation)

    def record(
        self,
        test_name: str,
        result: str,
        interface: str = "unspecified",
        detail: str = "",
        approved_by: str = "unspecified",
    ) -> ConnectivityObservation:
        obs = ConnectivityObservation(
            test_name=test_name,
            result=result,
            interface=interface,
            detail=detail,
            approved_by=approved_by,
        )
        self.add(obs)
        return obs

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as handle:
            json.dump([asdict(o) for o in self.observations], handle, indent=2)

    def summary(self) -> dict:
        """Count observations by result for a quick dashboard tile."""
        counts = {key: 0 for key in _VALID_RESULTS}
        for obs in self.observations:
            counts[obs.result] = counts.get(obs.result, 0) + 1
        counts["total"] = len(self.observations)
        return counts


def seed_example_log(store_path: str) -> ConnectivityLog:
    """
    Create a small, clearly-labelled example log on first run so the dashboard
    has something to show. These are placeholder observations, not live tests.
    """
    log = ConnectivityLog(store_path)
    if log.observations:
        return log
    log.record(
        "LAN web UI reachable (http://192.168.1.1)",
        "not-tested",
        interface="LAN",
        detail="Placeholder - record a real observation after an approved test.",
        approved_by="example",
    )
    log.record(
        "2.4GHz SSID visible to client",
        "not-tested",
        interface="2.4GHz Wi-Fi",
        detail="Placeholder example row.",
        approved_by="example",
    )
    log.save()
    return log
