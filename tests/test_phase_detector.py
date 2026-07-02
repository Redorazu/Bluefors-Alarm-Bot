from datetime import UTC, datetime

from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import OperatingPhasesConfig
from alarm_bot.monitoring.phase_detector import PhaseDetector, TemperatureReading
from alarm_bot.state.store import StateStore


def _node(value: str, status: str = "SYNCHRONIZED") -> dict:
    return {
        "content": {
            "latest_valid_value": {
                "value": value,
                "status": status,
                "outdated": False,
                "date": 0,
            }
        }
    }


def test_auto_warmup_when_t50k_above_threshold():
    cfg = OperatingPhasesConfig()
    detector = PhaseDetector(cfg)
    t50k = TemperatureReading(value_k=120.0, over_range=False, valid=True)
    eligible, counter = detector.check_auto_warmup(
        t50k, warmup_active=False, sustain_counter=0
    )
    assert eligible is True
    assert counter == 1


def test_cryo_normal_when_tmixing_below_100mk():
    cfg = OperatingPhasesConfig()
    detector = PhaseDetector(cfg)
    tmixing = TemperatureReading(value_k=0.05, over_range=False, valid=True)
    assert detector.check_cryo_normal(tmixing) is True


def test_over_range_is_invalid():
    cfg = OperatingPhasesConfig()
    detector = PhaseDetector(cfg)
    snap = SystemSnapshot(
        fetched_at=datetime.now(UTC),
        nodes={
            "mapper.bf.temperatures.t4k": _node("OVER RANGE", "OVER_RANGE"),
        },
        node_count=1,
    )
    reading = detector.read_temperatures(snap)["t4k"]
    assert reading.over_range is True
    assert reading.value_k is None
    assert reading.valid is False


def test_heater_4k_edge_triggers_auto_warmup():
    cfg = OperatingPhasesConfig()
    detector = PhaseDetector(cfg)
    state = StateStore(path=__import__("pathlib").Path("unused.json"))
    state.heater_4k_last_value = "0"

    snap_on = SystemSnapshot(
        fetched_at=datetime.now(UTC),
        nodes={
            "mapper.bf.heaters.heater": {
                "content": {
                    "latest_valid_value": {
                        "value": "1",
                        "status": "SYNCHRONIZED",
                        "outdated": False,
                    }
                }
            }
        },
        node_count=1,
    )
    eligible, value = detector.check_heater_4k_auto_warmup(
        snap_on, state, warmup_active=False
    )
    assert eligible is True
    assert value == "1"
    assert state.heater_4k_last_value == "1"

    eligible_again, _ = detector.check_heater_4k_auto_warmup(
        snap_on, state, warmup_active=False
    )
    assert eligible_again is False
