from alarm_bot.config import MetricConfig, RuleConfig


def test_should_suppress_uses_explicit_metric_setting():
    metric = MetricConfig(
        id="flow_rate",
        name="流量",
        value_path="mapper.bf.flow",
        category="flow",
        suppress_during_warmup=False,
    )
    assert metric.should_suppress_during_warmup() is False


def test_should_suppress_falls_back_to_category_default():
    metric = MetricConfig(
        id="mxc_temperature",
        name="MXC 溫度",
        value_path="mapper.bf.temperatures.tmixing",
        category="temperature",
    )
    assert metric.should_suppress_during_warmup() is True

    compressor = MetricConfig(
        id="compressor_1_error",
        name="壓縮機 1 錯誤碼",
        value_path="mapper.bflegacy.double.cpaerr",
        category="compressor",
    )
    assert compressor.should_suppress_during_warmup() is False


def test_should_suppress_explicit_true_overrides_compressor_category():
    metric = MetricConfig(
        id="compressor_1_error",
        name="壓縮機 1 錯誤碼",
        value_path="mapper.bflegacy.double.cpaerr",
        category="compressor",
        suppress_during_warmup=True,
        rules=[
            RuleConfig(severity="critical", condition="above", threshold=0, sustain_polls=1),
        ],
    )
    assert metric.should_suppress_during_warmup() is True
