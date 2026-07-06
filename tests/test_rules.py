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


def test_above_rule_matches_when_threshold_exceeded():
    metric = MetricConfig(
        id="test",
        name="Test",
        value_path="mapper.bf.test",
        rules=[RuleConfig(severity="warning", condition="above", threshold=1.0, sustain_polls=2)],
    )
    reading = _reading("1.5", 1.5)
    result = evaluate_metric(reading, metric)
    assert result.matched
    assert result.severity == "warning"


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
