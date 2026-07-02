from __future__ import annotations

from dataclasses import dataclass

from alarm_bot.bluefors.extractor import _get_node, _parse_sample
from alarm_bot.bluefors.models import VALID_SAMPLE_STATUSES, SystemSnapshot
from alarm_bot.config import OperatingPhasesConfig
from alarm_bot.state.store import StateStore


@dataclass
class TemperatureReading:
    value_k: float | None
    over_range: bool
    valid: bool
    raw: str | None = None
    status: str | None = None


@dataclass
class PhaseSnapshot:
    temperatures: dict[str, TemperatureReading]
    cryo_normal: bool
    auto_warmup_eligible: bool
    heater_4k_auto_warmup: bool
    tmixing_k: float | None
    heater_4k_value: str | None = None


def _is_over_range(raw: str | None, status: str | None) -> bool:
    if raw:
        lowered = raw.lower()
        if "over" in lowered and "range" in lowered:
            return True
    if status and status not in VALID_SAMPLE_STATUSES:
        upper = status.upper()
        if "OVER" in upper and "RANGE" in upper:
            return True
    return False


def _read_temperature(snapshot: SystemSnapshot, path: str) -> TemperatureReading:
    node = _get_node(snapshot.nodes, path)
    if node is None:
        return TemperatureReading(value_k=None, over_range=False, valid=False)

    content = node.get("content", {})
    if not isinstance(content, dict):
        content = {}

    latest_valid, latest = _parse_sample(content)
    sample = latest_valid or latest
    if sample is None:
        return TemperatureReading(value_k=None, over_range=False, valid=False)

    raw_value = sample.get("value")
    status = sample.get("status")
    raw_str = str(raw_value) if raw_value is not None else None
    over_range = _is_over_range(raw_str, status)

    if over_range:
        return TemperatureReading(
            value_k=None,
            over_range=True,
            valid=False,
            raw=raw_str,
            status=status,
        )

    numeric: float | None = None
    if raw_str is not None:
        try:
            numeric = float(raw_str)
        except ValueError:
            return TemperatureReading(
                value_k=None,
                over_range=over_range,
                valid=False,
                raw=raw_str,
                status=status,
            )

    valid = status in VALID_SAMPLE_STATUSES or status is None
    return TemperatureReading(
        value_k=numeric,
        over_range=over_range,
        valid=valid,
        raw=raw_str,
        status=status,
    )


def _read_raw_value(snapshot: SystemSnapshot, path: str) -> str | None:
    node = _get_node(snapshot.nodes, path)
    if node is None:
        return None
    content = node.get("content", {})
    if not isinstance(content, dict):
        return None
    latest_valid, latest = _parse_sample(content)
    sample = latest_valid or latest
    if sample is None:
        return None
    raw_value = sample.get("value")
    return str(raw_value) if raw_value is not None else None


class PhaseDetector:
    def __init__(self, config: OperatingPhasesConfig) -> None:
        self.config = config

    def read_temperatures(self, snapshot: SystemSnapshot) -> dict[str, TemperatureReading]:
        paths = self.config.temperature_paths
        return {
            key: _read_temperature(snapshot, path)
            for key, path in paths.model_dump().items()
            if path
        }

    def check_cryo_normal(self, tmixing: TemperatureReading | None) -> bool:
        if tmixing is None or tmixing.value_k is None or tmixing.over_range:
            return False
        return tmixing.value_k < self.config.cryo_normal.tmixing_max_k

    def check_auto_warmup(
        self,
        t50k: TemperatureReading | None,
        *,
        warmup_active: bool,
        sustain_counter: int,
    ) -> tuple[bool, int]:
        cfg = self.config.warmup
        if warmup_active or not cfg.auto_start_enabled:
            return False, 0
        if t50k is None or t50k.value_k is None or t50k.over_range:
            return False, 0
        if t50k.value_k <= cfg.auto_start_t50k_k:
            return False, 0

        next_counter = sustain_counter + 1
        if next_counter < cfg.auto_start_sustain_polls:
            return False, next_counter
        return True, next_counter

    def check_heater_4k_auto_warmup(
        self,
        snapshot: SystemSnapshot,
        state: StateStore,
        *,
        warmup_active: bool,
    ) -> tuple[bool, str | None]:
        cfg = self.config.warmup.heater_4k
        if warmup_active or not cfg.enabled:
            return False, _read_raw_value(snapshot, cfg.value_path)

        current = _read_raw_value(snapshot, cfg.value_path)
        previous = state.heater_4k_last_value
        state.heater_4k_last_value = current

        if current is None:
            return False, current

        on_values = set(cfg.on_values)
        if current in on_values and (previous is None or previous not in on_values):
            return True, current
        return False, current

    def build_phase_snapshot(
        self,
        state: StateStore,
        snapshot: SystemSnapshot,
    ) -> PhaseSnapshot:
        temps = self.read_temperatures(snapshot)
        tmixing = temps.get("tmixing")
        tmixing_k = tmixing.value_k if tmixing else None
        eligible, _ = self.check_auto_warmup(
            temps.get("t50k"),
            warmup_active=state.warmup_mode.active,
            sustain_counter=state.warmup_auto_start_counter,
        )
        heater_eligible, heater_value = self.check_heater_4k_auto_warmup(
            snapshot,
            state,
            warmup_active=state.warmup_mode.active,
        )
        return PhaseSnapshot(
            temperatures=temps,
            cryo_normal=self.check_cryo_normal(tmixing),
            auto_warmup_eligible=eligible,
            heater_4k_auto_warmup=heater_eligible,
            tmixing_k=tmixing_k,
            heater_4k_value=heater_value,
        )
