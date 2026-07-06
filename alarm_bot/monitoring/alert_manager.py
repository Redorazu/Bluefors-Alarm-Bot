from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from alarm_bot.bluefors.extractor import extract_all
from alarm_bot.bluefors.models import MetricReading, SystemSnapshot
from alarm_bot.config import AppYamlConfig, MetricConfig
from alarm_bot.logging.audit import AuditLogger
from alarm_bot.monitoring.metric_tracking import should_track_metric
from alarm_bot.monitoring.phase_detector import PhaseDetector, PhaseSnapshot
from alarm_bot.monitoring.rules import RuleMatch, check_recovery, evaluate_metric
from alarm_bot.state.store import AlertRecord, AlertStatus, StateStore, WarmupSource
from alarm_bot.value_formatter import format_metric_value_text

logger = logging.getLogger(__name__)

NotifyCallback = Callable[[AlertRecord, str], None]  # alert, kind: alert|recovery|reminder|info
WarmupNotifyCallback = Callable[[str, dict[str, Any]], None]  # kind: started|base_temp_entered, payload


@dataclass
class AlertEvent:
    kind: str  # alert, recovery, reminder, suppressed, none
    alert: AlertRecord | None = None
    reason: str | None = None


class AlertManager:
    def __init__(
        self,
        yaml_config: AppYamlConfig,
        state: StateStore,
        audit: AuditLogger,
        on_notify: NotifyCallback | None = None,
        on_warmup_notify: WarmupNotifyCallback | None = None,
    ) -> None:
        self.yaml_config = yaml_config
        self.state = state
        self.audit = audit
        self.on_notify = on_notify
        self.on_warmup_notify = on_warmup_notify
        self._last_notify: dict[str, datetime] = {}
        self._warmup_suppress_logged: set[str] = set()
        self._phase_detector = PhaseDetector(yaml_config.operating_phases)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _incident_key(self, metric_id: str, severity: str, condition: str, threshold: str) -> str:
        return f"{metric_id}:{severity}:{condition}:{threshold}"

    def _should_suppress_notify(self, metric_id: str, cooldown: int) -> bool:
        if self._should_suppress_remind(metric_id):
            return True
        last = self._last_notify.get(metric_id)
        if last and (datetime.now(UTC) - last).total_seconds() < cooldown:
            return True
        return False

    def _should_suppress_remind(self, metric_id: str) -> bool:
        if self.state.is_metric_muted(metric_id):
            return True
        if self.state.is_metric_snoozed(metric_id):
            return True
        return False

    def _reminder_interval(self, metric: MetricConfig) -> int:
        if metric.reminder_interval_seconds is not None:
            return metric.reminder_interval_seconds
        return self.yaml_config.slack.default_reminder_interval_seconds

    def _should_send_reminder(self, active: AlertRecord, interval: int) -> bool:
        ref = active.last_reminded_at or active.triggered_at
        try:
            last = datetime.fromisoformat(ref)
        except ValueError:
            return True
        return (datetime.now(UTC) - last).total_seconds() >= interval

    def process_snapshot(self, snapshot: SystemSnapshot) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        phase_snapshot = self._phase_detector.build_phase_snapshot(self.state, snapshot)
        self._handle_phase_and_warmup(phase_snapshot)

        readings = extract_all(snapshot, self.yaml_config.metrics)
        reading_by_id = {r.metric_id: r for r in readings}

        for metric in self.yaml_config.metrics:
            reading = reading_by_id.get(metric.id)
            if reading is None:
                continue

            if not should_track_metric(metric, reading, reading_by_id):
                self.state.sustain_counters[metric.id] = 0
                continue

            if self.yaml_config.logging.log_metric_evaluations:
                self.audit.log(
                    "metric.evaluated",
                    metric_id=metric.id,
                    payload={"value": format_metric_value_text(metric, reading), "valid": reading.valid},
                )

            event = self._process_metric(metric, reading)
            if event.kind != "none":
                events.append(event)

        self.state.save()
        return events

    def _handle_phase_and_warmup(self, phase_snapshot: PhaseSnapshot) -> None:
        if not self.state.warmup_mode.active:
            t50k = phase_snapshot.temperatures.get("t50k")
            eligible, counter = self._phase_detector.check_auto_warmup(
                t50k,
                warmup_active=False,
                sustain_counter=self.state.warmup_auto_start_counter,
            )
            self.state.warmup_auto_start_counter = counter
            if eligible:
                t50k_val = t50k.value_k if t50k else None
                note = (
                    f"t50k={t50k_val} K 超過閾值 "
                    f"{self.yaml_config.operating_phases.warmup.auto_start_t50k_k} K，自動啟動升溫標籤"
                )
                self.start_warmup_mode(
                    source="auto_t50k",
                    started_by="system",
                    note=note,
                    t50k_k=t50k_val,
                )
            elif phase_snapshot.heater_4k_auto_warmup:
                heater_val = phase_snapshot.heater_4k_value or "on"
                note = f"4K heater 已啟動（讀值={heater_val}），自動啟動升溫標籤"
                self.start_warmup_mode(
                    source="auto_4k_heater",
                    started_by="system",
                    note=note,
                )
        else:
            self.state.warmup_auto_start_counter = 0
            if phase_snapshot.cryo_normal:
                self.state.cryo_normal_sustain_counter += 1
                needed = self.yaml_config.operating_phases.cryo_normal.sustain_polls
                if self.state.cryo_normal_sustain_counter >= needed:
                    self.enter_base_temp_mode(
                        reason="auto_tmixing",
                        tmixing_k=phase_snapshot.tmixing_k,
                    )
            else:
                self.state.cryo_normal_sustain_counter = 0

    def start_warmup_mode(
        self,
        *,
        source: WarmupSource,
        started_by: str,
        note: str = "",
        t50k_k: float | None = None,
    ) -> None:
        if self.state.warmup_mode.active:
            return

        self.state.warmup_mode.active = True
        self.state.warmup_mode.source = source
        self.state.warmup_mode.started_at = self._now()
        self.state.warmup_mode.started_by = started_by
        self.state.warmup_mode.note = note
        self.state.warmup_auto_start_counter = 0
        self.state.cryo_normal_sustain_counter = 0
        self._warmup_suppress_logged.clear()
        self.state.save()

        payload = {
            "source": source,
            "started_by": started_by,
            "note": note,
            "t50k_k": t50k_k,
        }
        self.audit.log("warmup.started", payload=payload)
        if self.on_warmup_notify:
            self.on_warmup_notify("started", payload)

    def enter_base_temp_mode(
        self,
        *,
        reason: str,
        actor: str = "system",
        tmixing_k: float | None = None,
    ) -> None:
        if not self.state.warmup_mode.active:
            return

        previous_source = self.state.warmup_mode.source
        slack_channel = self.state.warmup_mode.slack_channel
        slack_ts = self.state.warmup_mode.slack_ts

        self.state.warmup_mode.active = False
        self.state.warmup_mode.source = None
        self.state.warmup_mode.started_at = None
        self.state.warmup_mode.started_by = None
        self.state.warmup_mode.note = ""
        self.state.warmup_mode.slack_channel = None
        self.state.warmup_mode.slack_ts = None
        self.state.cryo_normal_sustain_counter = 0
        self.state.warmup_auto_start_counter = 0
        self._warmup_suppress_logged.clear()
        self.state.save()

        payload = {
            "reason": reason,
            "actor": actor,
            "tmixing_k": tmixing_k,
            "previous_source": previous_source,
            "slack_channel": slack_channel,
            "slack_ts": slack_ts,
        }
        self.audit.log(
            "warmup.base_temp_entered",
            user_id=actor if actor != "system" else None,
            payload=payload,
        )
        if self.on_warmup_notify:
            self.on_warmup_notify("base_temp_entered", payload)

    def attach_warmup_slack_message(self, channel: str, ts: str) -> None:
        self.state.warmup_mode.slack_channel = channel
        self.state.warmup_mode.slack_ts = ts
        self.state.save()

    def get_warmup_status(self) -> dict[str, Any]:
        wm = self.state.warmup_mode
        return {
            "active": wm.active,
            "mode": "warmup" if wm.active else "cryo_normal",
            "source": wm.source,
            "started_at": wm.started_at,
            "started_by": wm.started_by,
            "note": wm.note,
        }

    def _process_metric(self, metric: MetricConfig, reading: MetricReading) -> AlertEvent:
        if self.state.warmup_mode.active and metric.should_suppress_during_warmup():
            if metric.id not in self._warmup_suppress_logged:
                self._warmup_suppress_logged.add(metric.id)
                self.audit.log(
                    "metric.suppressed",
                    metric_id=metric.id,
                    payload={"reason": "warmup_mode", "category": metric.category},
                )
            return AlertEvent(kind="suppressed", reason="warmup_mode")

        counter_key = metric.id
        active = self._find_active_alert(metric.id)

        if active and active.status in ("IGNORED", "ACKNOWLEDGED"):
            active.value = format_metric_value_text(metric, reading)
            active.updated_at = self._now()
            if check_recovery(reading, metric, active.threshold, active.condition):
                return self._recover(active, reading, metric)
            return AlertEvent(kind="none")

        if active and active.status == "ACTIVE":
            active.value = format_metric_value_text(metric, reading)
            active.updated_at = self._now()
            if check_recovery(reading, metric, active.threshold, active.condition):
                return self._recover(active, reading, metric)
            interval = self._reminder_interval(metric)
            if (
                interval > 0
                and not self._should_suppress_remind(metric.id)
                and self._should_send_reminder(active, interval)
            ):
                return self._remind(active, reading, metric)
            return AlertEvent(kind="none")

        match = evaluate_metric(reading, metric)

        if not match.matched:
            self.state.sustain_counters[counter_key] = 0
            return AlertEvent(kind="none")

        self.state.sustain_counters[counter_key] = (
            self.state.sustain_counters.get(counter_key, 0) + 1
        )

        if self.state.sustain_counters[counter_key] < _min_sustain(metric, match):
            return AlertEvent(kind="none")

        alert_id = str(uuid.uuid4())[:8]
        incident_key = self._incident_key(
            metric.id, match.severity or "warning", match.condition or "", match.threshold or ""
        )

        for existing in self.state.alerts.values():
            if (
                existing.metric_id == metric.id
                and existing.status in ("ACTIVE", "ACKNOWLEDGED", "IGNORED")
                and existing.incident_key == incident_key
            ):
                return AlertEvent(kind="none")

        now = self._now()
        record = AlertRecord(
            alert_id=alert_id,
            metric_id=metric.id,
            severity=match.severity or "warning",
            status="ACTIVE",
            value=format_metric_value_text(metric, reading),
            threshold=match.threshold or "",
            condition=match.condition or "",
            playbook=metric.playbook,
            triggered_at=now,
            updated_at=now,
            sustain_count=self.state.sustain_counters[counter_key],
            incident_key=incident_key,
            last_reminded_at=now,
        )
        self.state.alerts[alert_id] = record

        if self._should_suppress_notify(metric.id, metric.cooldown_seconds):
            reason = "muted/snoozed/cooldown"
            self.audit.log(
                "alert.suppressed",
                alert_id=alert_id,
                metric_id=metric.id,
                payload={"reason": reason},
            )
            return AlertEvent(kind="suppressed", alert=record, reason=reason)

        self.audit.log(
            "alert.triggered",
            alert_id=alert_id,
            metric_id=metric.id,
            payload={
                "severity": record.severity,
                "value": record.value,
                "threshold": record.threshold,
                "playbook": record.playbook,
            },
        )
        self._last_notify[metric.id] = datetime.now(UTC)
        if self.on_notify:
            self.on_notify(record, "alert")
        return AlertEvent(kind="alert", alert=record)

    def _remind(self, active: AlertRecord, reading: MetricReading, metric: MetricConfig) -> AlertEvent:
        now = self._now()
        active.value = format_metric_value_text(metric, reading)
        active.updated_at = now
        active.last_reminded_at = now
        self.audit.log(
            "alert.reminded",
            alert_id=active.alert_id,
            metric_id=active.metric_id,
            payload={
                "severity": active.severity,
                "value": active.value,
                "threshold": active.threshold,
            },
        )
        if self.on_notify:
            self.on_notify(active, "reminder")
        return AlertEvent(kind="reminder", alert=active)

    def _recover(self, active: AlertRecord, reading: MetricReading, metric: MetricConfig) -> AlertEvent:
        active.status = "RECOVERED"
        active.updated_at = self._now()
        active.value = format_metric_value_text(metric, reading)
        self.state.sustain_counters[active.metric_id] = 0
        self.audit.log(
            "alert.recovered",
            alert_id=active.alert_id,
            metric_id=active.metric_id,
            payload={"value": format_metric_value_text(metric, reading)},
        )
        if self.on_notify:
            self.on_notify(active, "recovery")
        return AlertEvent(kind="recovery", alert=active)

    def _find_active_alert(self, metric_id: str) -> AlertRecord | None:
        for alert in self.state.alerts.values():
            if alert.metric_id == metric_id and alert.status in (
                "ACTIVE",
                "ACKNOWLEDGED",
                "IGNORED",
            ):
                return alert
        return None

    def get_alert(self, alert_id: str) -> AlertRecord | None:
        return self.state.alerts.get(alert_id)

    def list_active_alerts(self) -> list[AlertRecord]:
        return [
            a
            for a in self.state.alerts.values()
            if a.status in ("ACTIVE", "ACKNOWLEDGED", "IGNORED", "SNOOZED")
        ]

    def change_status(
        self,
        alert_id: str,
        new_status: AlertStatus,
        actor: str,
        *,
        slack_channel: str | None = None,
        slack_ts: str | None = None,
    ) -> AlertRecord | None:
        alert = self.state.alerts.get(alert_id)
        if not alert:
            return None
        old = alert.status
        alert.status = new_status
        alert.updated_at = self._now()
        alert.acted_by = actor
        if slack_channel:
            alert.slack_channel = slack_channel
        if slack_ts:
            alert.slack_ts = slack_ts
            alert.thread_ts = slack_ts
        self.state.save()
        self.audit.log(
            "alert.state_changed",
            alert_id=alert_id,
            metric_id=alert.metric_id,
            user_id=actor if actor != "system" else None,
            payload={"from_status": old, "to_status": new_status, "actor": actor},
        )
        return alert

    def snooze_metric(self, metric_id: str, minutes: int, actor: str) -> datetime:
        dt = self.state.set_snooze(metric_id, minutes)
        self.audit.log(
            "alert.state_changed",
            metric_id=metric_id,
            user_id=actor,
            payload={"action": "snooze", "minutes": minutes, "until": dt.isoformat()},
        )
        return dt

    def mute_metric(self, metric_id: str, actor: str, muted: bool = True) -> None:
        self.state.set_mute(metric_id, muted)
        self.audit.log(
            "alert.state_changed",
            metric_id=metric_id,
            user_id=actor,
            payload={"action": "mute" if muted else "unmute"},
        )

    def clear_all_state(self, actor: str) -> dict[str, int]:
        summary = {
            "alerts": len(self.state.alerts),
            "muted": sum(1 for v in self.state.metric_muted.values() if v),
            "snoozed": sum(
                1
                for metric_id in self.state.metric_snooze_until
                if self.state.is_metric_snoozed(metric_id)
            ),
        }
        self.state.reset_all()
        self._last_notify.clear()
        self._warmup_suppress_logged.clear()
        self.audit.log(
            "alert.state_changed",
            user_id=actor if actor != "system" else None,
            payload={"action": "clear_all_state", "summary": summary},
        )
        return summary

    def attach_slack_message(self, alert_id: str, channel: str, ts: str) -> None:
        alert = self.state.alerts.get(alert_id)
        if not alert:
            return
        alert.slack_channel = channel
        alert.slack_ts = ts
        alert.thread_ts = ts
        alert.updated_at = self._now()
        self.state.save()


def _min_sustain(metric: MetricConfig, match: RuleMatch) -> int:
    for rule in metric.rules:
        if rule.severity == match.severity and rule.condition == match.condition:
            return rule.sustain_polls
    return 1
