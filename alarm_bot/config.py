from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from alarm_bot.paths import CONFIG_PATH, ENV_PATH

MetricCategory = Literal[
    "temperature",
    "pressure",
    "flow",
    "compressor",
    "turbo",
    "sensor_connection",
]

WARMUP_SUPPRESS_CATEGORIES: frozenset[str] = frozenset(
    {"temperature", "pressure", "flow", "sensor_connection"}
)


class RuleConfig(BaseModel):
    severity: Literal["info", "warning", "critical"]
    condition: Literal[
        "above",
        "below",
        "equals",
        "not_equals",
        "outside_range",
        "status_not_in",
    ]
    threshold: float | str | list[float | str]
    sustain_polls: int = 1


class RecoveryConfig(BaseModel):
    hysteresis: float = 0.0


class MetricConfig(BaseModel):
    id: str
    name: str
    value_path: str
    category: MetricCategory | None = None
    suppress_during_warmup: bool | None = None
    unit: str = ""
    value_type: Literal["float", "int", "str", "enum", "sample_status"] = "float"
    enum_values: dict[str, list[str]] | None = None
    playbook: str = ""
    rules: list[RuleConfig] = Field(default_factory=list)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    cooldown_seconds: int = 300
    reminder_interval_seconds: int | None = None
    optional: bool = False
    enabled_by_metric: str | None = None
    enabled_by_value: str = "1"

    def should_suppress_during_warmup(self) -> bool:
        if self.suppress_during_warmup is not None:
            return self.suppress_during_warmup
        if self.category:
            return self.category in WARMUP_SUPPRESS_CATEGORIES
        return False


class TemperaturePathsConfig(BaseModel):
    t50k: str = "mapper.bf.temperatures.t50k"
    t4k: str = "mapper.bf.temperatures.t4k"
    tstill: str = "mapper.bf.temperatures.tstill"
    tmixing: str = "mapper.bf.temperatures.tmixing"


class Heater4kWarmupConfig(BaseModel):
    enabled: bool = True
    value_path: str = "mapper.bf.heaters.heater"
    on_values: list[str] = Field(default_factory=lambda: ["1"])


class WarmupPhaseConfig(BaseModel):
    auto_start_enabled: bool = True
    auto_start_t50k_k: float = 100.0
    auto_start_sustain_polls: int = 1
    heater_4k: Heater4kWarmupConfig = Field(default_factory=Heater4kWarmupConfig)


class CryoNormalConfig(BaseModel):
    tmixing_max_k: float = 0.1
    sustain_polls: int = 3


class OperatingPhasesConfig(BaseModel):
    temperature_paths: TemperaturePathsConfig = Field(default_factory=TemperaturePathsConfig)
    warmup: WarmupPhaseConfig = Field(default_factory=WarmupPhaseConfig)
    cryo_normal: CryoNormalConfig = Field(default_factory=CryoNormalConfig)


class BlueforsYamlConfig(BaseModel):
    base_url: str = ""
    snapshot_branch: str = ""
    snapshot_fields: str = "name;type;content.latest_valid_value;content.latest_value"
    verify_ssl: bool = False


class LoggingYamlConfig(BaseModel):
    level: str = "INFO"
    app_log_path: str = "logs/app.log"
    audit_log_path: str = "logs/audit.jsonl"
    audit_rotate_mb: int = 10
    audit_rotate_backups: int = 30
    log_metric_evaluations: bool = False


class SlackYamlConfig(BaseModel):
    mention_channel_on_critical: bool = False
    default_reminder_interval_seconds: int = 900
    status_fields_per_section: int = 10
    default_system_name: str = "Bluefors XLD1000"


class AppYamlConfig(BaseModel):
    bluefors: BlueforsYamlConfig = Field(default_factory=BlueforsYamlConfig)
    operating_phases: OperatingPhasesConfig = Field(default_factory=OperatingPhasesConfig)
    metrics: list[MetricConfig] = Field(default_factory=list)
    logging: LoggingYamlConfig = Field(default_factory=LoggingYamlConfig)
    slack: SlackYamlConfig = Field(default_factory=SlackYamlConfig)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bluefors_base_url: str = ""
    bluefors_api_key: str = ""
    bluefors_verify_ssl: bool = False
    bluefors_snapshot_branch: str = ""

    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_alert_channel_id: str = ""

    poll_interval_seconds: int = 30
    config_path: str = str(CONFIG_PATH)

    log_level: str = "INFO"
    audit_log_path: str = "logs/audit.jsonl"
    app_log_path: str = "logs/app.log"


def load_yaml_config(path: Path | None = None) -> AppYamlConfig:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        return AppYamlConfig()
    with config_path.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return AppYamlConfig.model_validate(raw)


def resolve_settings() -> tuple[EnvSettings, AppYamlConfig]:
    env = EnvSettings()
    yaml_cfg = load_yaml_config(Path(env.config_path))
    return env, yaml_cfg
