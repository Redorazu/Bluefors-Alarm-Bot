import tempfile
from datetime import UTC, datetime
from pathlib import Path

from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import AppYamlConfig, MetricConfig, RuleConfig
from alarm_bot.logging.audit import AuditLogger
from alarm_bot.monitoring.alert_manager import AlertManager
from alarm_bot.state.store import StateStore


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


def _snapshot(t50k: str = "37", tmixing: str = "0.05") -> SystemSnapshot:
    return SystemSnapshot(
        fetched_at=datetime.now(UTC),
        nodes={
            "mapper.bf.temperatures.t50k": _node(t50k),
            "mapper.bf.temperatures.t4k": _node("30"),
            "mapper.bf.temperatures.tstill": _node("28"),
            "mapper.bf.temperatures.tmixing": _node(tmixing),
            "mapper.bf.flow": _node("1.0"),
            "mapper.bflegacy.double.cpaerr": _node("0"),
        },
        node_count=6,
    )


def _manager(tmp_path: Path) -> tuple[AlertManager, AuditLogger]:
    yaml = AppYamlConfig(
        metrics=[
            MetricConfig(
                id="mxc_temperature",
                name="MXC",
                value_path="mapper.bf.temperatures.tmixing",
                category="temperature",
                rules=[
                    RuleConfig(
                        severity="critical",
                        condition="above",
                        threshold=0.01,
                        sustain_polls=1,
                    )
                ],
            ),
            MetricConfig(
                id="compressor_1_error",
                name="CPA1",
                value_path="mapper.bflegacy.double.cpaerr",
                category="compressor",
                value_type="int",
                rules=[
                    RuleConfig(
                        severity="critical",
                        condition="above",
                        threshold=0,
                        sustain_polls=1,
                    )
                ],
            ),
        ]
    )
    state = StateStore(path=tmp_path / "alerts.json")
    audit = AuditLogger(tmp_path / "audit.jsonl")
    return AlertManager(yaml, state, audit), audit


def test_warmup_suppresses_temperature_but_not_compressor():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp))
        try:
            manager.start_warmup_mode(source="manual", started_by="U1", note="test")

            snap = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={
                    "mapper.bf.temperatures.t50k": _node("37"),
                    "mapper.bf.temperatures.t4k": _node("30"),
                    "mapper.bf.temperatures.tstill": _node("28"),
                    "mapper.bf.temperatures.tmixing": _node("1.5"),
                    "mapper.bflegacy.double.cpaerr": _node("3"),
                },
                node_count=5,
            )
            events = manager.process_snapshot(snap)
            kinds = [e.kind for e in events]
            assert "suppressed" in kinds
            assert not any(
                e.alert and e.alert.metric_id == "mxc_temperature" for e in events
            )
            assert any(
                e.alert and e.alert.metric_id == "compressor_1_error" for e in events
            )
        finally:
            audit.close()


def test_warmup_metric_override_allows_alert_when_suppress_false():
    with tempfile.TemporaryDirectory() as tmp:
        yaml = AppYamlConfig(
            metrics=[
                MetricConfig(
                    id="flow_rate",
                    name="流量",
                    value_path="mapper.bf.flow",
                    category="flow",
                    suppress_during_warmup=False,
                    rules=[
                        RuleConfig(
                            severity="warning",
                            condition="below",
                            threshold=0.5,
                            sustain_polls=1,
                        )
                    ],
                ),
            ]
        )
        state = StateStore(path=Path(tmp) / "alerts.json")
        audit = AuditLogger(Path(tmp) / "audit.jsonl")
        manager = AlertManager(yaml, state, audit)
        try:
            manager.start_warmup_mode(source="manual", started_by="U1", note="test")
            snap = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={"mapper.bf.flow": _node("0.1")},
                node_count=1,
            )
            events = manager.process_snapshot(snap)
            assert any(e.kind == "alert" and e.alert and e.alert.metric_id == "flow_rate" for e in events)
        finally:
            audit.close()


def test_auto_warmup_start_on_high_t50k():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp))
        try:
            started: list[str] = []
            manager.on_warmup_notify = lambda kind, payload: started.append(kind)

            snap = _snapshot(t50k="150", tmixing="5")
            manager.process_snapshot(snap)
            assert manager.state.warmup_mode.active is True
            assert manager.state.warmup_mode.source == "auto_t50k"
            assert started == ["started"]
        finally:
            audit.close()


def test_auto_warmup_start_on_4k_heater():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp))
        try:
            started: list[str] = []
            manager.on_warmup_notify = lambda kind, payload: started.append(kind)

            snap_off = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={
                    "mapper.bf.temperatures.t50k": _node("37"),
                    "mapper.bf.temperatures.t4k": _node("30"),
                    "mapper.bf.temperatures.tstill": _node("28"),
                    "mapper.bf.temperatures.tmixing": _node("5"),
                    "mapper.bf.heaters.heater": _node("0"),
                },
                node_count=5,
            )
            manager.process_snapshot(snap_off)

            snap_on = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={
                    "mapper.bf.temperatures.t50k": _node("37"),
                    "mapper.bf.temperatures.t4k": _node("30"),
                    "mapper.bf.temperatures.tstill": _node("28"),
                    "mapper.bf.temperatures.tmixing": _node("5"),
                    "mapper.bf.heaters.heater": _node("1"),
                },
                node_count=5,
            )
            manager.process_snapshot(snap_on)

            assert manager.state.warmup_mode.active is True
            assert manager.state.warmup_mode.source == "auto_4k_heater"
            assert started == ["started"]
        finally:
            audit.close()


def test_enter_base_temp_mode_on_tmixing_sustain():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp))
        try:
            notified: list[str] = []
            manager.on_warmup_notify = lambda kind, payload: notified.append(kind)
            manager.start_warmup_mode(source="manual", started_by="U1")

            for _ in range(3):
                manager.process_snapshot(_snapshot(t50k="37", tmixing="0.05"))

            assert manager.state.warmup_mode.active is False
            assert "base_temp_entered" in notified
        finally:
            audit.close()


def test_warning_triggers_after_sustain_polls():
    with tempfile.TemporaryDirectory() as tmp:
        yaml = AppYamlConfig(
            metrics=[
                MetricConfig(
                    id="mxc_temperature",
                    name="MXC",
                    value_path="mapper.bf.temperatures.tmixing",
                    category="temperature",
                    rules=[
                        RuleConfig(
                            severity="warning",
                            condition="above",
                            threshold=0.1,
                            sustain_polls=3,
                        ),
                    ],
                ),
            ]
        )
        state = StateStore(path=Path(tmp) / "alerts.json")
        audit = AuditLogger(Path(tmp) / "audit.jsonl")
        manager = AlertManager(yaml, state, audit)
        try:
            snap = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={"mapper.bf.temperatures.tmixing": _node("0.15")},
                node_count=1,
            )

            events1 = manager.process_snapshot(snap)
            assert all(e.kind != "alert" for e in events1)
            assert manager.state.sustain_counters["mxc_temperature"] == 1

            events2 = manager.process_snapshot(snap)
            assert all(e.kind != "alert" for e in events2)
            assert manager.state.sustain_counters["mxc_temperature"] == 2

            events3 = manager.process_snapshot(snap)
            assert any(
                e.kind == "alert" and e.alert and e.alert.severity == "warning"
                for e in events3
            )
        finally:
            audit.close()


def test_sustain_counter_resets_when_condition_clears():
    with tempfile.TemporaryDirectory() as tmp:
        yaml = AppYamlConfig(
            metrics=[
                MetricConfig(
                    id="mxc_temperature",
                    name="MXC",
                    value_path="mapper.bf.temperatures.tmixing",
                    category="temperature",
                    rules=[
                        RuleConfig(
                            severity="warning",
                            condition="above",
                            threshold=0.1,
                            sustain_polls=3,
                        ),
                    ],
                ),
            ]
        )
        state = StateStore(path=Path(tmp) / "alerts.json")
        audit = AuditLogger(Path(tmp) / "audit.jsonl")
        manager = AlertManager(yaml, state, audit)
        try:
            high = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={"mapper.bf.temperatures.tmixing": _node("0.15")},
                node_count=1,
            )
            low = SystemSnapshot(
                fetched_at=datetime.now(UTC),
                nodes={"mapper.bf.temperatures.tmixing": _node("0.05")},
                node_count=1,
            )

            manager.process_snapshot(high)
            manager.process_snapshot(high)
            assert manager.state.sustain_counters["mxc_temperature"] == 2

            manager.process_snapshot(low)
            assert manager.state.sustain_counters["mxc_temperature"] == 0
        finally:
            audit.close()


def test_clear_all_state_resets_persisted_fields():
    with tempfile.TemporaryDirectory() as tmp:
        manager, audit = _manager(Path(tmp))
        try:
            manager.start_warmup_mode(source="manual", started_by="U1")
            manager.state.set_mute("mxc_temperature", True)
            manager.state.set_snooze("mxc_temperature", 30)
            manager.process_snapshot(
                SystemSnapshot(
                    fetched_at=datetime.now(UTC),
                    nodes={
                        "mapper.bf.temperatures.t50k": _node("37"),
                        "mapper.bf.temperatures.t4k": _node("30"),
                        "mapper.bf.temperatures.tstill": _node("28"),
                        "mapper.bf.temperatures.tmixing": _node("1.5"),
                        "mapper.bflegacy.double.cpaerr": _node("0"),
                    },
                    node_count=5,
                )
            )

            summary = manager.clear_all_state("U1")

            assert summary["alerts"] >= 0
            assert manager.state.alerts == {}
            assert manager.state.metric_muted == {}
            assert manager.state.metric_snooze_until == {}
            assert manager.state.sustain_counters == {}
            assert manager.state.warmup_mode.active is False
            assert manager.state.warmup_mode.started_at is None
            assert manager.state.warmup_auto_start_counter == 0
            assert manager.state.cryo_normal_sustain_counter == 0
        finally:
            audit.close()
