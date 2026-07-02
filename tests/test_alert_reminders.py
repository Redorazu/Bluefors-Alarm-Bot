import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import AppYamlConfig, MetricConfig, RuleConfig, SlackYamlConfig
from alarm_bot.logging.audit import AuditLogger
from alarm_bot.monitoring.alert_manager import AlertManager
from alarm_bot.state.store import AlertRecord, StateStore


def _node(value: str) -> dict:
    return {
        "content": {
            "latest_valid_value": {
                "value": value,
                "status": "SYNCHRONIZED",
                "outdated": False,
                "date": 0,
            }
        }
    }


def _snapshot(value: str = "1.5") -> SystemSnapshot:
    return SystemSnapshot(
        fetched_at=datetime.now(UTC),
        nodes={"mapper.bf.temperatures.tmixing": _node(value)},
        node_count=1,
    )


def _manager(
    tmp_path: Path,
    *,
    default_reminder_interval_seconds: int = 900,
    reminder_interval_seconds: int | None = None,
    unit: str = "",
) -> tuple[AlertManager, AuditLogger]:
    yaml = AppYamlConfig(
        slack=SlackYamlConfig(default_reminder_interval_seconds=default_reminder_interval_seconds),
        metrics=[
            MetricConfig(
                id="mxc_temperature",
                name="MXC",
                value_path="mapper.bf.temperatures.tmixing",
                category="temperature",
                unit=unit,
                reminder_interval_seconds=reminder_interval_seconds,
                rules=[
                    RuleConfig(
                        severity="critical",
                        condition="above",
                        threshold=0.01,
                        sustain_polls=1,
                    )
                ],
            )
        ],
    )
    state = StateStore(path=tmp_path / "alerts.json")
    audit = AuditLogger(tmp_path / "audit.jsonl")
    return AlertManager(yaml, state, audit), audit


def _seed_active_alert(manager: AlertManager, *, reminded_at: datetime) -> AlertRecord:
    reminded_iso = reminded_at.isoformat()
    alert = AlertRecord(
        alert_id="abc12345",
        metric_id="mxc_temperature",
        severity="critical",
        status="ACTIVE",
        value="1.5",
        threshold="0.01",
        condition="above",
        playbook="test",
        triggered_at=reminded_iso,
        updated_at=reminded_iso,
        incident_key="mxc_temperature:critical:above:0.01",
        last_reminded_at=reminded_iso,
        slack_channel="C123",
        slack_ts="111.222",
        thread_ts="111.222",
    )
    manager.state.alerts[alert.alert_id] = alert
    manager.state.save()
    return alert


def test_active_alert_sends_reminder_after_interval():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp), default_reminder_interval_seconds=60)
        notified: list[str] = []
        manager.on_notify = lambda alert, kind: notified.append(kind)
        try:
            _seed_active_alert(
                manager,
                reminded_at=datetime.now(UTC) - timedelta(seconds=120),
            )

            events = manager.process_snapshot(_snapshot("1.6"))

            assert len(events) == 1
            assert events[0].kind == "reminder"
            assert notified == ["reminder"]
            assert events[0].alert is not None
            assert events[0].alert.value == "1.6"
        finally:
            audit.close()


def test_active_alert_does_not_remind_before_interval():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp), default_reminder_interval_seconds=900)
        notified: list[str] = []
        manager.on_notify = lambda alert, kind: notified.append(kind)
        try:
            _seed_active_alert(
                manager,
                reminded_at=datetime.now(UTC) - timedelta(seconds=30),
            )

            events = manager.process_snapshot(_snapshot("1.6"))

            assert events == []
            assert notified == []
        finally:
            audit.close()


def test_acknowledged_alert_does_not_send_reminder():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp), default_reminder_interval_seconds=60)
        notified: list[str] = []
        manager.on_notify = lambda alert, kind: notified.append(kind)
        try:
            alert = _seed_active_alert(
                manager,
                reminded_at=datetime.now(UTC) - timedelta(seconds=120),
            )
            alert.status = "ACKNOWLEDGED"

            events = manager.process_snapshot(_snapshot("1.6"))

            assert events == []
            assert notified == []
        finally:
            audit.close()


def test_metric_reminder_interval_zero_disables_reminders():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(
            Path(tmp),
            default_reminder_interval_seconds=60,
            reminder_interval_seconds=0,
        )
        notified: list[str] = []
        manager.on_notify = lambda alert, kind: notified.append(kind)
        try:
            _seed_active_alert(
                manager,
                reminded_at=datetime.now(UTC) - timedelta(seconds=120),
            )

            events = manager.process_snapshot(_snapshot("1.6"))

            assert events == []
            assert notified == []
        finally:
            audit.close()


def test_snoozed_metric_suppresses_reminder():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp), default_reminder_interval_seconds=60)
        notified: list[str] = []
        manager.on_notify = lambda alert, kind: notified.append(kind)
        try:
            _seed_active_alert(
                manager,
                reminded_at=datetime.now(UTC) - timedelta(seconds=120),
            )
            manager.state.set_snooze("mxc_temperature", 30)

            events = manager.process_snapshot(_snapshot("1.6"))

            assert events == []
            assert notified == []
        finally:
            audit.close()


def test_alert_value_uses_shared_formatter():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp), unit="K")
        try:
            events = manager.process_snapshot(_snapshot("0.0264"))
            assert len(events) == 1
            assert events[0].kind == "alert"
            assert events[0].alert is not None
            assert events[0].alert.value == "26.400 mK"
        finally:
            audit.close()
