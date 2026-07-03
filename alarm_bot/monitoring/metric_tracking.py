from __future__ import annotations

from alarm_bot.bluefors.models import MetricReading
from alarm_bot.config import MetricConfig

UNAVAILABLE_ERRORS = frozenset({"value path not found", "no sample data"})


def is_reading_present(reading: MetricReading) -> bool:
    if reading.error in UNAVAILABLE_ERRORS:
        return False
    return True


def should_track_metric(
    metric: MetricConfig,
    reading: MetricReading,
    readings_by_id: dict[str, MetricReading],
) -> bool:
    if metric.optional and not is_reading_present(reading):
        return False
    if metric.enabled_by_metric:
        enabler = readings_by_id.get(metric.enabled_by_metric)
        if enabler is None or not is_reading_present(enabler):
            return False
        expected = metric.enabled_by_value if metric.enabled_by_value is not None else "1"
        if (enabler.raw_value or "") != expected:
            return False
    return True


def should_show_in_status(
    metric: MetricConfig,
    reading: MetricReading,
    readings_by_id: dict[str, MetricReading],
) -> bool:
    if metric.optional and not is_reading_present(reading):
        return False
    if metric.enabled_by_metric and not should_track_metric(metric, reading, readings_by_id):
        return False
    return True


def describe_tracking_status(
    metric: MetricConfig,
    reading: MetricReading | None,
    readings_by_id: dict[str, MetricReading],
) -> str:
    if reading is None:
        return "無讀值"
    if should_track_metric(metric, reading, readings_by_id):
        return "追蹤中"
    if metric.optional and not is_reading_present(reading):
        return "未追蹤（未安裝）"
    if metric.enabled_by_metric:
        return "未追蹤（條件未啟用）"
    return "未追蹤"
