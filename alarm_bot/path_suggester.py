from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alarm_bot.config import MetricConfig


METRIC_PATH_CANDIDATES: dict[str, tuple[str, ...]] = {
    "mxc_temperature": (
        "mapper.bf.temperatures.tmixing",
        "mapper.bflegacy.double.tmixing",
    ),
    "t50k_temperature": ("mapper.bf.temperatures.t50k",),
    "t4k_temperature": ("mapper.bf.temperatures.t4k",),
    "tstill_temperature": ("mapper.bf.temperatures.tstill",),
    "magnet_enabled": ("mapper.bf.temperatures.tmagnet_enabled",),
    "magnet_temperature": (
        "mapper.bf.temperatures.tmagnet",
        "mapper.bflegacy.double.tmagnet",
    ),
    "compressor_1_inlet_water": (
        "mapper.bflegacy.double.cpatempwi",
        "mapper.bf.cpatempwi",
    ),
    "compressor_1_error": (
        "mapper.bflegacy.double.cpaerr",
        "mapper.bf.cpaerr",
    ),
    "compressor_2_inlet_water": (
        "mapper.bflegacy.double.cpatempwi_2",
    ),
    "compressor_2_error": (
        "mapper.bflegacy.double.cpaerr_2",
    ),
    "turbo_1_status": ("mapper.bf.pumps.turbo1",),
    "turbo_2_status": ("mapper.bf.pumps.turbo2",),
    "pressure_p1": ("mapper.bf.pressures.p1",),
    "pressure_p2": ("mapper.bf.pressures.p2",),
    "pressure_p3": ("mapper.bf.pressures.p3",),
    "pressure_p4": ("mapper.bf.pressures.p4",),
    "pressure_p5": ("mapper.bf.pressures.p5",),
    "pressure_p6": ("mapper.bf.pressures.p6",),
    "flow_rate": ("mapper.bf.flow",),
    "sensor_connection_mxc": (
        "mapper.bf.temperatures.tmixing",
        "mapper.bflegacy.double.tmixing",
    ),
    "sensor_connection_t4k": ("mapper.bf.temperatures.t4k",),
    "sensor_connection_tstill": ("mapper.bf.temperatures.tstill",),
}


def load_snapshot_nodes(snapshot_path: Path) -> dict[str, Any]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("Snapshot JSON 'data' must be an object")
    return data


def suggest_metric_paths(
    metrics: list[MetricConfig],
    nodes: dict[str, Any],
) -> dict[str, str]:
    node_keys = set(nodes.keys())
    suggestions: dict[str, str] = {}
    for metric in metrics:
        if metric.value_path in node_keys:
            suggestions[metric.id] = metric.value_path
            continue

        for candidate in METRIC_PATH_CANDIDATES.get(metric.id, ()):
            if candidate in node_keys:
                suggestions[metric.id] = candidate
                break
        else:
            suggestions[metric.id] = metric.value_path
    return suggestions


def render_yaml_patch(metrics: list[MetricConfig], suggestions: dict[str, str]) -> str:
    lines = ["# Suggested config.yaml value_path updates"]
    for metric in metrics:
        old_path = metric.value_path
        new_path = suggestions.get(metric.id, old_path)
        changed = " # updated" if new_path != old_path else " # unchanged"
        lines.append(f"- id: {metric.id}")
        lines.append(f'  value_path: "{new_path}"{changed}')
    return "\n".join(lines)
