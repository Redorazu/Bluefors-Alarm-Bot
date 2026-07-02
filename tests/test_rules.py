from alarm_bot.bluefors.models import MetricReading
from alarm_bot.config import MetricConfig, RecoveryConfig, RuleConfig
from alarm_bot.monitoring.rules import check_recovery, evaluate_metric


def _reading(value: str, num: float | None = None) -> MetricReading:
    return MetricReading(
        metric_id="test",
        name="Test",
        value_path="mapper.bf.test",
        unit="K",
        value_type="float",
        raw_value=value,
        numeric_value=num,
        sample_status="SYNCHRONIZED",
        outdated=False,
        timestamp_ms=0,
        valid=True,
    )


def test_above_rule_triggers_after_sustain():
    metric = MetricConfig(
        id="test",
        name="Test",
        value_path="mapper.bf.test",
        rules=[RuleConfig(severity="warning", condition="above", threshold=1.0, sustain_polls=2)],
    )
    reading = _reading("1.5", 1.5)
    assert not evaluate_metric(reading, metric, 0).matched
    assert evaluate_metric(reading, metric, 1).matched


def test_recovery_with_hysteresis():
    metric = MetricConfig(
        id="test",
        name="Test",
        value_path="mapper.bf.test",
        rules=[RuleConfig(severity="warning", condition="above", threshold=1.0, sustain_polls=1)],
        recovery=RecoveryConfig(hysteresis=0.1),
    )
    reading = _reading("0.85", 0.85)
    assert check_recovery(reading, metric, "1.0", "above")
