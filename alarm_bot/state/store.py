from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

AlertStatus = Literal[
    "OK",
    "ACTIVE",
    "ACKNOWLEDGED",
    "IGNORED",
    "SNOOZED",
    "MUTED",
    "RECOVERED",
]

WarmupSource = Literal["manual", "auto_t50k", "auto_4k_heater"]


@dataclass
class WarmupModeState:
    active: bool = False
    source: WarmupSource | None = None
    started_at: str | None = None
    started_by: str | None = None
    note: str = ""
    slack_channel: str | None = None
    slack_ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> WarmupModeState:
        if not raw:
            return cls()
        return cls(
            active=bool(raw.get("active", False)),
            source=raw.get("source"),
            started_at=raw.get("started_at"),
            started_by=raw.get("started_by"),
            note=raw.get("note", ""),
            slack_channel=raw.get("slack_channel"),
            slack_ts=raw.get("slack_ts"),
        )


@dataclass
class AlertRecord:
    alert_id: str
    metric_id: str
    severity: str
    status: AlertStatus
    value: str
    threshold: str
    condition: str
    playbook: str
    triggered_at: str
    updated_at: str
    sustain_count: int = 0
    slack_channel: str | None = None
    slack_ts: str | None = None
    thread_ts: str | None = None
    acted_by: str | None = None
    snooze_until: str | None = None
    incident_key: str = ""
    last_reminded_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StateStore:
    path: Path
    alerts: dict[str, AlertRecord] = field(default_factory=dict)
    metric_muted: dict[str, bool] = field(default_factory=dict)
    metric_snooze_until: dict[str, str] = field(default_factory=dict)
    sustain_counters: dict[str, int] = field(default_factory=dict)
    initialized_at: str | None = None
    warmup_mode: WarmupModeState = field(default_factory=WarmupModeState)
    warmup_auto_start_counter: int = 0
    cryo_normal_sustain_counter: int = 0
    heater_4k_last_value: str | None = None

    def load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        self.metric_muted = raw.get("metric_muted", {})
        self.metric_snooze_until = raw.get("metric_snooze_until", {})
        self.sustain_counters = raw.get("sustain_counters", {})
        self.initialized_at = raw.get("initialized_at")
        self.warmup_mode = WarmupModeState.from_dict(raw.get("warmup_mode"))
        self.warmup_auto_start_counter = int(raw.get("warmup_auto_start_counter", 0))
        self.cryo_normal_sustain_counter = int(raw.get("cryo_normal_sustain_counter", 0))
        self.heater_4k_last_value = raw.get("heater_4k_last_value")
        alerts_raw = raw.get("alerts", {})
        self.alerts = {
            k: AlertRecord(**v) for k, v in alerts_raw.items() if isinstance(v, dict)
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "initialized_at": self.initialized_at,
            "metric_muted": self.metric_muted,
            "metric_snooze_until": self.metric_snooze_until,
            "sustain_counters": self.sustain_counters,
            "warmup_mode": self.warmup_mode.to_dict(),
            "warmup_auto_start_counter": self.warmup_auto_start_counter,
            "cryo_normal_sustain_counter": self.cryo_normal_sustain_counter,
            "heater_4k_last_value": self.heater_4k_last_value,
            "alerts": {k: v.to_dict() for k, v in self.alerts.items()},
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def is_metric_muted(self, metric_id: str) -> bool:
        return self.metric_muted.get(metric_id, False)

    def is_metric_snoozed(self, metric_id: str) -> bool:
        until = self.metric_snooze_until.get(metric_id)
        if not until:
            return False
        try:
            return datetime.fromisoformat(until) > datetime.now(UTC)
        except ValueError:
            return False

    def set_snooze(self, metric_id: str, minutes: int) -> datetime:
        until = datetime.now(UTC).timestamp() + minutes * 60
        dt = datetime.fromtimestamp(until, UTC)
        self.metric_snooze_until[metric_id] = dt.isoformat()
        self.save()
        return dt

    def set_mute(self, metric_id: str, muted: bool = True) -> None:
        self.metric_muted[metric_id] = muted
        self.save()

    def mark_initialized(self) -> None:
        self.initialized_at = datetime.now(UTC).isoformat()
        self.save()

    def reset_all(self) -> None:
        self.alerts.clear()
        self.metric_muted.clear()
        self.metric_snooze_until.clear()
        self.sustain_counters.clear()
        self.warmup_mode = WarmupModeState()
        self.warmup_auto_start_counter = 0
        self.cryo_normal_sustain_counter = 0
        self.heater_4k_last_value = None
        self.initialized_at = None
        self.save()
