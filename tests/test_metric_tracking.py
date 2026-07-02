from alarm_bot.bluefors.models import MetricReading
from alarm_bot.config import MetricConfig
from alarm_bot.monitoring.metric_tracking import is_reading_present, should_track_metric


def _reading(
    metric_id: str,
    *,
    error: str | None = None,
    raw: str | None = "1.0",
    num: float | None = 1.0,
) -> MetricReading:
    return MetricReading(
        metric_id=metric_id,
        name=metric_id,
        value_path="mapper.bf.test",
        unit="K",
        value_type="float",
        raw_value=raw,
        numeric_value=num,
        sample_status="SYNCHRONIZED",
        outdated=False,
        timestamp_ms=0,
        valid=error is None,
        error=error,
    )


def test_optional_missing_skips_tracking():
    metric = MetricConfig(
        id="magnet_temperature",
        name="Magnet",
        value_path="mapper.bf.temperatures.tmagnet",
        optional=True,
    )
    reading = _reading("magnet_temperature", error="value path not found", raw=None, num=None)
    assert should_track_metric(metric, reading, {metric.id: reading}) is False


def test_magnet_temp_tracks_only_when_enabled():
    enabled = MetricConfig(
        id="magnet_enabled",
        name="Magnet enabled",
        value_path="mapper.bf.temperatures.tmagnet_enabled",
        value_type="int",
        optional=True,
    )
    temp = MetricConfig(
        id="magnet_temperature",
        name="Magnet temp",
        value_path="mapper.bf.temperatures.tmagnet",
        optional=True,
        enabled_by_metric="magnet_enabled",
        enabled_by_value="1",
    )
    en_on = _reading("magnet_enabled", raw="1", num=1.0)
    en_off = _reading("magnet_enabled", raw="0", num=0.0)
    temp_reading = _reading("magnet_temperature", raw="5.2", num=5.2)
    by_id_on = {"magnet_enabled": en_on, "magnet_temperature": temp_reading}
    by_id_off = {"magnet_enabled": en_off, "magnet_temperature": temp_reading}

    assert should_track_metric(temp, temp_reading, by_id_on) is True
    assert should_track_metric(temp, temp_reading, by_id_off) is False


def test_is_reading_present():
    assert is_reading_present(_reading("x", error="value path not found", raw=None, num=None)) is False
    assert is_reading_present(_reading("x")) is True
