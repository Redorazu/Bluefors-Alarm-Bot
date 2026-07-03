from datetime import UTC, datetime

from alarm_bot.bluefors.models import MetricReading, SystemSnapshot
from alarm_bot.config import AppYamlConfig, MetricConfig
from alarm_bot.slack.messages import (
    build_status_text,
    build_status_blocks,
    build_help_blocks,
    build_metrics_list_blocks,
    build_alerts_list_blocks,
    build_metric_id_reference_text,
    format_metric_status_line,
    format_sample_status_suffix,
    format_snapshot_timestamp,
    build_warmup_status_text,
    build_warmup_label_blocks,
)
from alarm_bot.time_utils import format_local_timestamp
from alarm_bot.state.store import AlertRecord


def _metric(**kwargs) -> MetricConfig:
    defaults = {
        "id": "test",
        "name": "測試",
        "value_path": "mapper.bf.test",
        "category": "temperature",
    }
    defaults.update(kwargs)
    return MetricConfig(**defaults)


def _reading(**kwargs) -> MetricReading:
    defaults = {
        "metric_id": "test",
        "name": "測試",
        "value_path": "mapper.bf.test",
        "unit": "K",
        "value_type": "float",
        "raw_value": "1.0",
        "numeric_value": 1.0,
        "sample_status": "SYNCHRONIZED",
        "outdated": False,
        "timestamp_ms": None,
        "valid": True,
    }
    defaults.update(kwargs)
    return MetricReading(**defaults)


def test_status_suffix_hidden_for_normal_numeric():
    metric = _metric(category="temperature")
    reading = _reading(sample_status="SYNCHRONIZED")
    assert format_sample_status_suffix(metric, reading) == ""


def test_sensor_enabled_int_hides_sample_status_suffix():
    metric = _metric(
        id="mxc_enabled",
        category="sensor_connection",
        value_type="int",
    )
    reading = _reading(sample_status="SYNCHRONIZED", value_type="int", raw_value="1")
    assert format_sample_status_suffix(metric, reading) == ""


def test_status_suffix_shown_for_legacy_sensor_connection_float():
    metric = _metric(category="sensor_connection", value_type="float")
    reading = _reading(sample_status="SYNCHRONIZED", value_type="float")
    assert format_sample_status_suffix(metric, reading) == " (SYNCHRONIZED)"


def test_status_suffix_shown_for_abnormal_status():
    metric = _metric(category="temperature")
    reading = _reading(sample_status="DISCONNECTED")
    assert format_sample_status_suffix(metric, reading) == " (DISCONNECTED)"


def test_format_k_to_mk_below_one():
    metric = _metric(category="temperature", unit="K")
    reading = _reading(raw_value="0.0264", numeric_value=0.0264, unit="K")
    line = format_metric_status_line(metric, reading)
    assert "`26.400` mK" in line


def test_format_k_three_decimals():
    metric = _metric(category="temperature", unit="K")
    reading = _reading(raw_value="4.123456", numeric_value=4.123456, unit="K")
    line = format_metric_status_line(metric, reading)
    assert "`4.123` K" in line


def test_format_celsius_two_decimals():
    metric = _metric(category="temperature", unit="°C")
    reading = _reading(raw_value="14.87944507598877", numeric_value=14.87944507598877, unit="°C")
    line = format_metric_status_line(metric, reading)
    assert "`14.88` °C" in line


def test_format_pressure_to_mbar_scientific():
    metric = _metric(category="pressure", unit="")
    reading = _reading(raw_value="5.89e-9", numeric_value=5.89e-9, unit="")
    line = format_metric_status_line(metric, reading)
    assert "`5.890e-06` mbar" in line


def test_format_flow_two_decimals():
    metric = _metric(category="flow", unit="")
    reading = _reading(raw_value="1.0086742992612074", numeric_value=1.0086742992612074, unit="")
    line = format_metric_status_line(metric, reading)
    assert "`1.01`" in line


def test_compressor_error_zero_shows_no_error():
    metric = _metric(id="compressor_1_error", category="compressor", value_type="int", unit="")
    reading = _reading(
        metric_id="compressor_1_error",
        value_type="int",
        raw_value="0",
        numeric_value=0.0,
        unit="",
    )
    line = format_metric_status_line(metric, reading)
    assert "`no error`" in line


def test_turbo_enum_shows_label_instead_of_number():
    metric = _metric(
        id="turbo_1_status",
        category="turbo",
        value_type="enum",
        enum_values={"error": ["2"], "running": ["1"], "off": ["0"]},
        unit="",
    )
    reading = _reading(
        metric_id="turbo_1_status",
        value_type="enum",
        raw_value="1",
        numeric_value=None,
        unit="",
    )
    line = format_metric_status_line(metric, reading)
    assert "`running`" in line


def test_magnet_enabled_shows_human_readable_label():
    metric = _metric(
        id="magnet_enabled",
        name="磁鐵感測器啟用",
        category="sensor_connection",
        value_type="int",
        unit="",
    )
    reading_on = _reading(
        metric_id="magnet_enabled",
        name="磁鐵感測器啟用",
        value_type="int",
        raw_value="1",
        numeric_value=1.0,
        unit="",
    )
    reading_off = _reading(
        metric_id="magnet_enabled",
        name="磁鐵感測器啟用",
        value_type="int",
        raw_value="0",
        numeric_value=0.0,
        unit="",
    )

    line_on = format_metric_status_line(metric, reading_on)
    line_off = format_metric_status_line(metric, reading_off)

    assert "`enabled`" in line_on
    assert "`disabled`" in line_off
    assert "(SYNCHRONIZED)" not in line_on
    assert "(SYNCHRONIZED)" not in line_off


def test_build_status_text_groups_by_category():
    yaml = AppYamlConfig(
        metrics=[
            _metric(id="flow_rate", name="流量", category="flow", unit=""),
            _metric(id="mxc", name="MXC 溫度", category="temperature"),
        ]
    )
    snap = SystemSnapshot(
        fetched_at=datetime(2026, 7, 1, 4, 30, tzinfo=UTC),
        nodes={
            "mapper.bf.test": {
                "content": {
                    "latest_valid_value": {
                        "value": "0.05",
                        "status": "SYNCHRONIZED",
                        "outdated": False,
                    }
                }
            }
        },
        node_count=1,
    )
    text = build_status_text(
        snap,
        yaml,
        {"system_name": "Lab", "sw_version": "10.0"},
        warmup_status={"active": True},
        active_alert_count=2,
    )
    assert "運行: *升溫模式* | 進行中示警: *2*" in text
    assert "*溫度*" in text
    assert "*流量*" in text
    assert text.index("*溫度*") < text.index("*流量*")
    assert "(SYNCHRONIZED)" not in text
    assert "_快照時間:" in text
    assert "T04:30" not in text  # local format, no ISO micros


def test_build_status_text_system_version_fallback():
    yaml = AppYamlConfig(metrics=[_metric(id="mxc", name="MXC 溫度", category="temperature")])
    snap = SystemSnapshot(
        fetched_at=datetime(2026, 7, 1, 4, 30, tzinfo=UTC),
        nodes={
            "mapper.bf.test": {
                "content": {
                    "latest_valid_value": {"value": "0.05", "status": "SYNCHRONIZED", "outdated": False}
                }
            }
        },
        node_count=1,
    )
    text = build_status_text(
        snap,
        yaml,
        {"system_name": "", "system_version": "v2.2", "api_version": "v2.2"},
        active_alert_count=0,
    )
    assert "系統: Bluefors XLD1000 | 版本: v2.2" in text


def test_build_status_text_uses_config_default_system_name():
    yaml = AppYamlConfig.model_validate(
        {
            "slack": {"default_system_name": "My Custom System"},
            "metrics": [{"id": "mxc", "name": "MXC 溫度", "value_path": "mapper.bf.test", "category": "temperature"}],
        }
    )
    snap = SystemSnapshot(
        fetched_at=datetime(2026, 7, 1, 4, 30, tzinfo=UTC),
        nodes={
            "mapper.bf.test": {
                "content": {
                    "latest_valid_value": {"value": "0.05", "status": "SYNCHRONIZED", "outdated": False}
                }
            }
        },
        node_count=1,
    )
    text = build_status_text(
        snap,
        yaml,
        {"system_name": "", "system_version": "v2.2"},
        active_alert_count=0,
    )
    assert "系統: My Custom System | 版本: v2.2" in text


def test_build_status_blocks_has_sections():
    yaml = AppYamlConfig(
        metrics=[_metric(id="mxc", name="MXC 溫度", category="temperature")]
    )
    snap = SystemSnapshot(
        fetched_at=datetime(2026, 7, 1, 4, 30, tzinfo=UTC),
        nodes={
            "mapper.bf.test": {
                "content": {
                    "latest_valid_value": {
                        "value": "0.05",
                        "status": "SYNCHRONIZED",
                        "outdated": False,
                    }
                }
            }
        },
        node_count=1,
    )
    resp = build_status_blocks(
        snap,
        yaml,
        {"system_name": "Lab", "sw_version": "10.0"},
        active_alert_count=0,
    )
    assert resp.blocks is not None
    assert resp.blocks[0]["type"] == "header"
    assert any(b.get("type") == "section" for b in resp.blocks)
    assert any("fields" in b for b in resp.blocks if b.get("type") == "section")


def test_build_help_blocks_vertical_layout():
    metrics = [
        _metric(id="mxc_temperature", name="MXC 溫度", category="temperature"),
        _metric(id="flow_rate", name="流量", category="flow"),
    ]
    resp = build_help_blocks(metrics)
    assert resp.blocks is not None
    assert resp.text == "Bluefors Bot 指令說明"
    assert any(b.get("type") == "divider" for b in resp.blocks)
    sections = [b for b in resp.blocks if b.get("type") == "section"]
    assert sections
    assert all("fields" not in b for b in sections)
    body = "\n".join(b["text"]["text"] for b in sections)
    assert "/bluefors metrics" in body
    assert "`mxc_temperature`" in body
    assert "`flow_rate`" in body


def test_build_metric_id_reference_text_groups_by_category():
    metrics = [
        _metric(id="flow_rate", name="流量", category="flow"),
        _metric(id="mxc_temperature", name="MXC 溫度", category="temperature"),
    ]
    text = build_metric_id_reference_text(metrics)
    assert text.index("*溫度*") < text.index("*流量*")
    assert "`mxc_temperature`" in text


def test_build_metrics_list_blocks_shows_tracking_status():
    metrics = [
        _metric(id="mxc_temperature", name="MXC 溫度", category="temperature"),
        _metric(
            id="magnet_temperature",
            name="磁鐵溫度",
            category="temperature",
            optional=True,
            enabled_by_metric="magnet_enabled",
        ),
    ]
    readings = {
        "mxc_temperature": MetricReading(
            metric_id="mxc_temperature",
            name="MXC 溫度",
            value_path="mapper.bf.temperatures.tmixing",
            unit="K",
            value_type="float",
            raw_value="0.05",
            numeric_value=0.05,
            sample_status="SYNCHRONIZED",
            outdated=False,
            timestamp_ms=0,
            valid=True,
            error=None,
        ),
        "magnet_temperature": MetricReading(
            metric_id="magnet_temperature",
            name="磁鐵溫度",
            value_path="mapper.bf.temperatures.tmagnet",
            unit="K",
            value_type="float",
            raw_value=None,
            numeric_value=None,
            sample_status=None,
            outdated=False,
            timestamp_ms=0,
            valid=False,
            error="value path not found",
        ),
    }
    resp = build_metrics_list_blocks(metrics, readings)
    body = "\n".join(
        b.get("text", {}).get("text", "")
        for b in resp.blocks or []
        if b.get("type") == "section" and "text" in b
    )
    assert "追蹤中" in body
    assert "未安裝" in body


def test_build_help_blocks():
    resp = build_help_blocks([])
    assert resp.blocks is not None
    assert len(resp.blocks) >= 3
    assert resp.text == "Bluefors Bot 指令說明"


def test_build_alerts_list_blocks_empty():
    resp = build_alerts_list_blocks([])
    assert resp.blocks is not None
    assert "沒有進行中的示警" in resp.blocks[1]["text"]["text"]


def test_build_alerts_list_blocks_with_alerts():
    alerts = [
        AlertRecord(
            alert_id="a1",
            metric_id="mxc_temperature",
            severity="warning",
            status="ACTIVE",
            value="1.5",
            threshold="0.1",
            condition="above",
            playbook="",
            triggered_at="t",
            updated_at="t",
        )
    ]
    resp = build_alerts_list_blocks(alerts)
    assert resp.blocks is not None
    assert "進行中的示警 (1)" in resp.blocks[0]["text"]["text"]


def test_format_local_timestamp_matches_snapshot_style():
    dt = datetime(2026, 7, 2, 8, 0, tzinfo=UTC)
    text = format_local_timestamp(dt)
    assert "T" not in text
    assert len(text) == 16


def test_warmup_status_text_formats_started_at_human_readable():
    text = build_warmup_status_text(
        {
            "active": True,
            "source": "manual",
            "started_by": "U1",
            "started_at": "2026-07-02T08:10:12+00:00",
            "note": "",
        }
    )
    assert "T08:10:12" not in text
    assert "2026-07-02" in text
    assert "<@U1>" in text


def test_warmup_label_blocks_formats_started_at_human_readable():
    blocks = build_warmup_label_blocks(
        source="manual",
        started_by="U1",
        note="",
        started_at="2026-07-02T08:10:12+00:00",
    )
    text = blocks[1]["text"]["text"]
    assert "T08:10:12" not in text
    assert "2026-07-02" in text
    assert "<@U1>" in text

