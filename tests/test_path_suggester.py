from alarm_bot.config import MetricConfig
from alarm_bot.path_suggester import render_yaml_patch, suggest_metric_paths


def test_suggest_metric_paths_uses_known_aliases():
    metrics = [
        MetricConfig(id="mxc_temperature", name="MXC", value_path="mapper.bf.tmixing"),
        MetricConfig(
            id="compressor_1_error",
            name="CPA err",
            value_path="mapper.bf.cpaerr",
            value_type="int",
        ),
        MetricConfig(id="flow_rate", name="Flow", value_path="mapper.bf.flow"),
    ]
    nodes = {
        "mapper.bf.temperatures.tmixing": {},
        "mapper.bflegacy.double.cpaerr": {},
        "mapper.bf.flow": {},
    }

    suggestions = suggest_metric_paths(metrics, nodes)

    assert suggestions["mxc_temperature"] == "mapper.bf.temperatures.tmixing"
    assert suggestions["compressor_1_error"] == "mapper.bflegacy.double.cpaerr"
    assert suggestions["flow_rate"] == "mapper.bf.flow"


def test_render_yaml_patch_marks_changes():
    metrics = [
        MetricConfig(id="mxc_temperature", name="MXC", value_path="mapper.bf.tmixing"),
        MetricConfig(id="flow_rate", name="Flow", value_path="mapper.bf.flow"),
    ]
    suggestions = {
        "mxc_temperature": "mapper.bf.temperatures.tmixing",
        "flow_rate": "mapper.bf.flow",
    }

    text = render_yaml_patch(metrics, suggestions)

    assert 'value_path: "mapper.bf.temperatures.tmixing" # updated' in text
    assert 'value_path: "mapper.bf.flow" # unchanged' in text
