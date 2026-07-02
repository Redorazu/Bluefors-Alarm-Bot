from __future__ import annotations

from alarm_bot.bluefors.models import MetricReading
from alarm_bot.config import MetricConfig


def reading_numeric_value(reading: MetricReading) -> float | None:
    if reading.numeric_value is not None:
        return reading.numeric_value
    if reading.raw_value is None:
        return None
    try:
        return float(reading.raw_value)
    except ValueError:
        return None


def format_enum_label(metric: MetricConfig, reading: MetricReading) -> str | None:
    raw = reading.raw_value
    if not raw or not metric.enum_values:
        return None
    for label, values in metric.enum_values.items():
        if raw in {str(v) for v in values}:
            return label
    return None


def format_metric_value(metric: MetricConfig, reading: MetricReading) -> tuple[str, str]:
    if reading.error:
        return f"ERROR: {reading.error}", ""
    if reading.value_type == "sample_status":
        return reading.sample_status or "unknown", ""

    num = reading_numeric_value(reading)
    unit = metric.unit or reading.unit or ""

    if metric.category == "turbo" and metric.value_type == "enum":
        label = format_enum_label(metric, reading)
        if label is not None:
            return label, ""

    if metric.category == "compressor" and metric.id.endswith("_error"):
        if num is not None and abs(num) < 1e-12:
            return "no error", ""

    if metric.id == "magnet_enabled":
        raw = (reading.raw_value or "").strip()
        if raw == "1":
            return "enabled", ""
        if raw == "0":
            return "disabled", ""
        if num is not None and abs(num - 1.0) < 1e-12:
            return "enabled", ""
        if num is not None and abs(num) < 1e-12:
            return "disabled", ""
        return "unknown", ""

    if metric.category == "pressure" and num is not None:
        return f"{num * 1000:.3e}", "mbar"

    if unit == "K" and num is not None:
        if abs(num) < 1:
            return f"{num * 1000:.3f}", "mK"
        return f"{num:.3f}", "K"

    if unit == "°C" and num is not None:
        return f"{num:.2f}", "°C"

    if metric.category == "flow" and num is not None:
        return f"{num:.2f}", unit

    if num is not None:
        return f"{num}", unit
    return reading.raw_value or "n/a", unit


def format_metric_value_text(metric: MetricConfig, reading: MetricReading) -> str:
    value, unit = format_metric_value(metric, reading)
    return f"{value} {unit}".strip()
