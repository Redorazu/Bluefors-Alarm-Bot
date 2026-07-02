from alarm_bot.bluefors.extractor import extract_metric
from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import MetricConfig
from datetime import UTC, datetime


def test_extract_metric_from_flat_snapshot():
    metric = MetricConfig(
        id="flow",
        name="Flow",
        value_path="mapper.bf.flow",
        value_type="float",
    )
    snapshot = SystemSnapshot(
        fetched_at=datetime.now(UTC),
        node_count=1,
        nodes={
            "mapper.bf.flow": {
                "name": "mapper.bf.flow",
                "type": "Value.Number.Float",
                "content": {
                    "latest_valid_value": {
                        "value": "2.5",
                        "status": "SYNCHRONIZED",
                        "date": 0,
                        "outdated": False,
                    }
                },
            }
        },
    )
    reading = extract_metric(snapshot, metric)
    assert reading.numeric_value == 2.5
    assert reading.valid is True


def test_extract_metric_with_mapper_bf_alias_path():
    metric = MetricConfig(
        id="mxc_temperature",
        name="MXC",
        value_path="mapper.bf.tmixing",
        value_type="float",
    )
    snapshot = SystemSnapshot(
        fetched_at=datetime.now(UTC),
        node_count=1,
        nodes={
            "mapper.bf.temperatures.tmixing": {
                "name": "mapper.bf.temperatures.tmixing",
                "type": "Value.Number.Float",
                "content": {
                    "latest_valid_value": {
                        "value": "0.021",
                        "status": "SYNCHRONIZED",
                        "date": 0,
                        "outdated": False,
                    }
                },
            }
        },
    )
    reading = extract_metric(snapshot, metric)
    assert reading.numeric_value == 0.021
    assert reading.valid is True


def test_extract_metric_from_branch_relative_path():
    metric = MetricConfig(
        id="flow",
        name="Flow",
        value_path="mapper.bf.flow",
        value_type="float",
    )
    snapshot = SystemSnapshot(
        fetched_at=datetime.now(UTC),
        node_count=1,
        nodes={
            "flow": {
                "name": "flow",
                "type": "Value.Number.Float",
                "content": {
                    "latest_valid_value": {
                        "value": "1.25",
                        "status": "SYNCHRONIZED",
                        "date": 0,
                        "outdated": False,
                    }
                },
            }
        },
    )
    reading = extract_metric(snapshot, metric)
    assert reading.numeric_value == 1.25
    assert reading.valid is True
