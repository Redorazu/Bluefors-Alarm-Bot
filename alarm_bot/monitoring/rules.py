from __future__ import annotations

from dataclasses import dataclass

from alarm_bot.bluefors.models import MetricReading, VALID_SAMPLE_STATUSES
from alarm_bot.config import MetricConfig, RuleConfig


@dataclass
class RuleMatch:
    matched: bool
    severity: str | None = None
    condition: str | None = None
    threshold: str | None = None
    reason: str | None = None


def _threshold_str(threshold: float | str | list[float | str]) -> str:
    if isinstance(threshold, list):
        return ",".join(str(t) for t in threshold)
    return str(threshold)


def evaluate_rule(reading: MetricReading, rule: RuleConfig, metric: MetricConfig | None = None) -> RuleMatch:
    cond = rule.condition
    threshold = rule.threshold

    if cond == "status_not_in":
        allowed = {str(t) for t in threshold} if isinstance(threshold, list) else {str(threshold)}
        status = reading.sample_status or "UNKNOWN"
        matched = status not in allowed
        return RuleMatch(
            matched=matched,
            severity=rule.severity if matched else None,
            condition=cond,
            threshold=_threshold_str(threshold),
            reason=f"status={status}",
        )

    if reading.value_type == "sample_status":
        status = reading.sample_status or ""
        matched = cond == "equals" and status == str(threshold)
        matched = matched or (cond == "not_equals" and status != str(threshold))
        return RuleMatch(
            matched=matched,
            severity=rule.severity if matched else None,
            condition=cond,
            threshold=str(threshold),
            reason=f"status={status}",
        )

    if reading.numeric_value is None and reading.raw_value is not None:
        try:
            num = float(reading.raw_value)
        except ValueError:
            num = None
    else:
        num = reading.numeric_value

    if cond in ("equals", "not_equals"):
        actual = reading.raw_value if reading.raw_value is not None else ""
        target = str(threshold)
        targets: set[str] | None = None
        if metric and metric.enum_values and isinstance(threshold, str) and threshold in metric.enum_values:
            targets = {str(v) for v in metric.enum_values[threshold]}
        if targets is not None:
            matched = (cond == "equals" and actual in targets) or (
                cond == "not_equals" and actual not in targets
            )
            target = ",".join(sorted(targets))
        else:
            matched = (cond == "equals" and actual == target) or (
                cond == "not_equals" and actual != target
            )
        return RuleMatch(
            matched=matched,
            severity=rule.severity if matched else None,
            condition=cond,
            threshold=target,
            reason=f"value={actual}",
        )

    if num is None:
        return RuleMatch(matched=False, reason="no numeric value")

    if cond == "above":
        matched = num > float(threshold)  # type: ignore[arg-type]
    elif cond == "below":
        matched = num < float(threshold)  # type: ignore[arg-type]
    elif cond == "outside_range":
        if not isinstance(threshold, list) or len(threshold) != 2:
            return RuleMatch(matched=False, reason="outside_range needs [low, high]")
        low, high = float(threshold[0]), float(threshold[1])
        matched = num < low or num > high
    else:
        return RuleMatch(matched=False, reason=f"unknown condition {cond}")

    return RuleMatch(
        matched=matched,
        severity=rule.severity if matched else None,
        condition=cond,
        threshold=_threshold_str(threshold),
        reason=f"value={num}",
    )


def evaluate_metric(
    reading: MetricReading,
    metric: MetricConfig,
) -> RuleMatch:
    if not reading.valid and reading.value_type != "sample_status":
        if reading.sample_status and reading.sample_status not in VALID_SAMPLE_STATUSES:
            for rule in metric.rules:
                if rule.condition == "status_not_in":
                    return evaluate_rule(reading, rule, metric)
        return RuleMatch(matched=False, reason=reading.error or "invalid reading")

    best: RuleMatch | None = None
    severity_rank = {"critical": 3, "warning": 2, "info": 1}

    for rule in metric.rules:
        result = evaluate_rule(reading, rule, metric)
        if not result.matched:
            continue
        if best is None or severity_rank.get(result.severity or "", 0) > severity_rank.get(
            best.severity or "", 0
        ):
            best = result

    return best or RuleMatch(matched=False)


def check_recovery(
    reading: MetricReading,
    metric: MetricConfig,
    active_threshold: str,
    active_condition: str,
) -> bool:
    if reading.numeric_value is None:
        if reading.value_type in ("str", "enum", "sample_status"):
            return not any(
                evaluate_rule(reading, r, metric).matched for r in metric.rules
            )
        return False

    hysteresis = metric.recovery.hysteresis
    val = reading.numeric_value

    if active_condition == "above":
        try:
            return val < float(active_threshold) - hysteresis
        except ValueError:
            return False
    if active_condition == "below":
        try:
            return val > float(active_threshold) + hysteresis
        except ValueError:
            return False
    return not any(evaluate_rule(reading, r, metric).matched for r in metric.rules)
