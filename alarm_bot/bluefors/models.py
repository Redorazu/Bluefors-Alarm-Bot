from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


VALID_SAMPLE_STATUSES = frozenset(
    {"SYNCHRONIZED", "CHANGED", "INDEPENDENT", "QUEUED"}
)


@dataclass
class MetricReading:
    metric_id: str
    name: str
    value_path: str
    unit: str
    value_type: str
    raw_value: str | None
    numeric_value: float | None
    sample_status: str | None
    outdated: bool
    timestamp_ms: int | None
    valid: bool
    error: str | None = None

    @property
    def display_value(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if self.value_type == "sample_status":
            return self.sample_status or "unknown"
        if self.numeric_value is not None:
            return f"{self.numeric_value}"
        return self.raw_value or "n/a"


@dataclass
class SystemSnapshot:
    fetched_at: datetime
    nodes: dict[str, Any]
    node_count: int
    system_info: dict[str, Any] = field(default_factory=dict)
