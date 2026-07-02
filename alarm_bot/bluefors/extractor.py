from __future__ import annotations

from typing import Any

from alarm_bot.bluefors.models import (
    VALID_SAMPLE_STATUSES,
    MetricReading,
    SystemSnapshot,
)
from alarm_bot.config import MetricConfig


VALUE_PATH_ALIASES: dict[str, tuple[str, ...]] = {
    "mapper.bf.tmixing": (
        "mapper.bf.temperatures.tmixing",
        "mapper.bflegacy.double.tmixing",
    ),
    "mapper.bf.cpatempwi": (
        "mapper.bflegacy.double.cpatempwi",
    ),
    "mapper.bf.cpaerr": (
        "mapper.bflegacy.double.cpaerr",
    ),
    "mapper.bflegacy.double.cpatempwi_2": (
        "mapper.bflegacy.double.cpatempwi_2",
    ),
    "mapper.bflegacy.double.cpaerr_2": (
        "mapper.bflegacy.double.cpaerr_2",
    ),
    "mapper.bf.heaters.heater": (
        "mapper.bflegacy.boolean.heater",
    ),
    "mapper.bf.temperatures.tmagnet": (
        "mapper.bflegacy.double.tmagnet",
    ),
}


def _path_candidates(value_path: str) -> list[str]:
    path = value_path.strip().strip("/")
    if not path:
        return []

    normalized = path.replace("/", ".")
    candidates: list[str] = [normalized]

    aliases = VALUE_PATH_ALIASES.get(normalized, ())
    candidates.extend(aliases)

    for prefix in ("mapper.bf.", "mapper.bflegacy.", "driver."):
        if normalized.startswith(prefix):
            candidates.append(normalized[len(prefix) :])
            for alias in aliases:
                if alias.startswith(prefix):
                    candidates.append(alias[len(prefix) :])

    # Keep order while deduplicating
    return list(dict.fromkeys(candidates))


def _get_node(nodes: dict[str, Any], value_path: str) -> dict[str, Any] | None:
    for candidate in _path_candidates(value_path):
        node = nodes.get(candidate)
        if isinstance(node, dict):
            return node
    return None


def _parse_sample(content: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    latest_valid = content.get("latest_valid_value")
    latest = content.get("latest_value")
    lv = latest_valid if isinstance(latest_valid, dict) else None
    lv2 = latest if isinstance(latest, dict) else None
    return lv, lv2


def extract_metric(
    snapshot: SystemSnapshot,
    metric: MetricConfig,
) -> MetricReading:
    node = _get_node(snapshot.nodes, metric.value_path)
    if node is None:
        return MetricReading(
            metric_id=metric.id,
            name=metric.name,
            value_path=metric.value_path,
            unit=metric.unit,
            value_type=metric.value_type,
            raw_value=None,
            numeric_value=None,
            sample_status=None,
            outdated=False,
            timestamp_ms=None,
            valid=False,
            error="value path not found",
        )

    content = node.get("content", {})
    if not isinstance(content, dict):
        content = {}

    latest_valid, latest = _parse_sample(content)
    sample = latest_valid or latest
    if sample is None:
        return MetricReading(
            metric_id=metric.id,
            name=metric.name,
            value_path=metric.value_path,
            unit=metric.unit,
            value_type=metric.value_type,
            raw_value=None,
            numeric_value=None,
            sample_status=None,
            outdated=False,
            timestamp_ms=None,
            valid=False,
            error="no sample data",
        )

    raw_value = sample.get("value")
    status = sample.get("status")
    outdated = bool(sample.get("outdated", False))
    timestamp_ms = sample.get("date")
    raw_str = str(raw_value) if raw_value is not None else None

    numeric: float | None = None
    if metric.value_type in ("float", "int") and raw_str is not None:
        try:
            numeric = float(raw_str)
            if metric.value_type == "int":
                numeric = float(int(numeric))
        except ValueError:
            return MetricReading(
                metric_id=metric.id,
                name=metric.name,
                value_path=metric.value_path,
                unit=metric.unit,
                value_type=metric.value_type,
                raw_value=raw_str,
                numeric_value=None,
                sample_status=status,
                outdated=outdated,
                timestamp_ms=timestamp_ms,
                valid=False,
                error=f"cannot parse numeric value: {raw_str}",
            )

    valid = not outdated and (
        metric.value_type == "sample_status"
        or status in VALID_SAMPLE_STATUSES
        or status is None
    )

    return MetricReading(
        metric_id=metric.id,
        name=metric.name,
        value_path=metric.value_path,
        unit=metric.unit,
        value_type=metric.value_type,
        raw_value=raw_str,
        numeric_value=numeric,
        sample_status=status,
        outdated=outdated,
        timestamp_ms=timestamp_ms,
        valid=valid,
    )


def extract_all(
    snapshot: SystemSnapshot,
    metrics: list[MetricConfig],
) -> list[MetricReading]:
    return [extract_metric(snapshot, m) for m in metrics]
