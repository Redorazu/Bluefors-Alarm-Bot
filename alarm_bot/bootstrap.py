from __future__ import annotations

import logging

from dotenv import load_dotenv

from alarm_bot.app_context import AppContext
from alarm_bot.bluefors.client import BlueforsApiClient
from alarm_bot.bluefors.system_info import display_system_name, display_system_version
from alarm_bot.config import EnvSettings, load_yaml_config, resolve_settings
from alarm_bot.logging.audit import AuditLogger, setup_app_logging
from alarm_bot.monitoring.alert_manager import AlertManager
from alarm_bot.monitoring.poller import MonitorPoller
from alarm_bot.paths import BASE_DIR, CONFIG_PATH, ENV_PATH, LOG_DIR, STATE_DIR
from alarm_bot.slack.notifier import SlackNotifier
from alarm_bot.state.store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_ENV_TEMPLATE = """# Fill in values (or run: alarm-bot setup)

BLUEFORS_BASE_URL=https://192.168.1.10:49098
BLUEFORS_API_KEY=
BLUEFORS_VERIFY_SSL=false
BLUEFORS_SNAPSHOT_BRANCH=

SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_ALERT_CHANNEL_ID=

POLL_INTERVAL_SECONDS=30
CONFIG_PATH=config.yaml

LOG_LEVEL=INFO
AUDIT_LOG_PATH=logs/audit.jsonl
APP_LOG_PATH=logs/app.log
"""

DEFAULT_CONFIG_TEMPLATE = """bluefors:
  base_url: ""
  snapshot_branch: ""
  snapshot_fields: "name;type;content.latest_valid_value;content.latest_value"
  verify_ssl: false

operating_phases:
  temperature_paths:
    t50k: mapper.bf.temperatures.t50k
    t4k: mapper.bf.temperatures.t4k
    tstill: mapper.bf.temperatures.tstill
    tmixing: mapper.bf.temperatures.tmixing
  warmup:
    auto_start_enabled: true
    auto_start_t50k_k: 100.0
    auto_start_sustain_polls: 1
  cryo_normal:
    tmixing_max_k: 0.1
    sustain_polls: 3

logging:
  level: INFO
  app_log_path: logs/app.log
  audit_log_path: logs/audit.jsonl
  audit_rotate_mb: 10
  audit_rotate_backups: 30
  log_metric_evaluations: false

slack:
  mention_channel_on_critical: false
  default_reminder_interval_seconds: 900
  status_fields_per_section: 10
  default_system_name: "Bluefors XLD1000"

metrics:
  # suppress_during_warmup: 升溫標籤期間是否抑制此 metric 的示警（可逐項設定）
  # 若省略，依 category 預設：temperature / pressure / flow / sensor_connection 為 true；compressor / turbo 為 false
  - id: mxc_enabled
    name: "MXC 感測器啟用"
    value_path: "mapper.bf.temperatures.tmixing_enabled"
    category: sensor_connection
    suppress_during_warmup: true
    value_type: int
    playbook: "檢查 MXC 感測器是否已啟用"
    rules:
      - severity: critical
        condition: equals
        threshold: "0"
        sustain_polls: 2
    cooldown_seconds: 300

  - id: mxc_temperature
    name: "MXC 溫度"
    value_path: "mapper.bf.temperatures.tmixing"
    category: temperature
    suppress_during_warmup: true
    unit: "K"
    value_type: float
    enabled_by_metric: mxc_enabled
    enabled_by_value: "1"
    playbook: "檢查 MXC 加熱器與 dilution 狀態"
    rules:
      - severity: warning
        condition: above
        threshold: 0.1
        sustain_polls: 3
      - severity: critical
        condition: above
        threshold: 1.0
        sustain_polls: 1
    recovery:
      hysteresis: 0.05
    cooldown_seconds: 300

  - id: compressor_1_inlet_water
    name: "壓縮機 1 冷卻水入水溫"
    value_path: "mapper.bflegacy.double.cpatempwi"
    category: compressor
    suppress_during_warmup: false
    unit: "°C"
    value_type: float
    playbook: "檢查冷卻水循環與熱交換器"
    rules:
      - severity: warning
        condition: above
        threshold: 35.0
        sustain_polls: 2
      - severity: critical
        condition: above
        threshold: 40.0
        sustain_polls: 1
    recovery:
      hysteresis: 2.0
    cooldown_seconds: 300

  - id: compressor_1_error
    name: "壓縮機 1 錯誤碼"
    value_path: "mapper.bflegacy.double.cpaerr"
    category: compressor
    suppress_during_warmup: false
    value_type: int
    playbook: "查閱壓縮機手冊錯誤碼表"
    rules:
      - severity: critical
        condition: above
        threshold: 0
        sustain_polls: 1
    cooldown_seconds: 600

  - id: flow_rate
    name: "流量"
    value_path: "mapper.bf.flow"
    category: flow
    suppress_during_warmup: true
    unit: ""
    value_type: float
    playbook: "檢查 flowmeter 與管路"
    rules:
      - severity: warning
        condition: below
        threshold: 0.5
        sustain_polls: 3
    cooldown_seconds: 300

  # Legacy sample_status（已由 *_enabled 取代）
  # - id: sensor_connection_mxc
  #   name: "MXC 感測器連線狀態"
  #   value_path: "mapper.bf.temperatures.tmixing"
  #   category: sensor_connection
  #   value_type: sample_status
  #   playbook: "檢查 BFTC 連線與感測器線路"
  #   rules:
  #     - severity: critical
  #       condition: status_not_in
  #       threshold: ["SYNCHRONIZED", "CHANGED", "INDEPENDENT", "QUEUED"]
  #       sustain_polls: 2
  #   cooldown_seconds: 300
"""


def create_app_context() -> AppContext:
    load_dotenv(ENV_PATH)
    env, yaml_config = resolve_settings()

    # env overrides yaml for bluefors connection
    base_url = env.bluefors_base_url or yaml_config.bluefors.base_url
    verify_ssl = env.bluefors_verify_ssl
    snapshot_branch = env.bluefors_snapshot_branch or yaml_config.bluefors.snapshot_branch

    log_cfg = yaml_config.logging
    setup_app_logging(
        env.log_level or log_cfg.level,
        BASE_DIR / (env.app_log_path or log_cfg.app_log_path),
    )

    audit_path = BASE_DIR / (env.audit_log_path or log_cfg.audit_log_path)
    audit = AuditLogger(
        audit_path,
        rotate_mb=log_cfg.audit_rotate_mb,
        backups=log_cfg.audit_rotate_backups,
    )

    state_path = STATE_DIR / "alerts.json"
    state = StateStore(path=state_path)
    state.load()

    client = BlueforsApiClient(
        base_url=base_url,
        api_key=env.bluefors_api_key,
        verify_ssl=verify_ssl,
        snapshot_branch=snapshot_branch,
        snapshot_fields=yaml_config.bluefors.snapshot_fields,
    )

    ctx = AppContext(
        env=env,
        yaml_config=yaml_config,
        audit=audit,
        state=state,
        bluefors_client=client,
        alert_manager=AlertManager(yaml_config, state, audit),
    )

    if env.slack_bot_token and env.slack_alert_channel_id:
        notifier = SlackNotifier(ctx)
        ctx.slack_notifier = notifier
        ctx.alert_manager.on_notify = notifier.on_alert_notify
        ctx.alert_manager.on_warmup_notify = notifier.on_warmup_notify

    ctx.poller = MonitorPoller(ctx)
    return ctx


def validate_runtime_config(ctx: AppContext) -> list[str]:
    errors: list[str] = []
    if not ctx.env.bluefors_base_url and not ctx.yaml_config.bluefors.base_url:
        errors.append("BLUEFORS_BASE_URL is not set")
    if not ctx.env.bluefors_api_key:
        errors.append("BLUEFORS_API_KEY is not set")
    if not ctx.env.slack_bot_token:
        errors.append("SLACK_BOT_TOKEN is not set")
    if not ctx.env.slack_app_token:
        errors.append("SLACK_APP_TOKEN is not set (required for Socket Mode)")
    if not ctx.env.slack_alert_channel_id:
        errors.append("SLACK_ALERT_CHANNEL_ID is not set")
    if not CONFIG_PATH.exists():
        errors.append(f"config.yaml not found at {CONFIG_PATH}")
    return errors


def run_health_checks(ctx: AppContext) -> tuple[bool, list[str]]:
    messages: list[str] = []
    ok = True

    if ctx.bluefors_client.health_check():
        info = ctx.bluefors_client.fetch_system_info()
        default_name = ctx.yaml_config.slack.default_system_name
        messages.append(
            f"Bluefors OK: {display_system_name(info, default_name)} "
            f"version: {display_system_version(info)}"
        )
    else:
        ok = False
        messages.append("Bluefors API: connection failed")

    if ctx.env.slack_bot_token:
        try:
            from slack_sdk import WebClient

            resp = WebClient(token=ctx.env.slack_bot_token).auth_test()
            messages.append(f"Slack OK: team={resp.get('team')}")
        except Exception as exc:
            ok = False
            messages.append(f"Slack: {exc}")

    return ok, messages


def ensure_runtime_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_local_config_files() -> list[str]:
    created_files: list[str] = []

    if not ENV_PATH.exists():
        ENV_PATH.write_text(DEFAULT_ENV_TEMPLATE, encoding="utf-8")
        created_files.append(str(ENV_PATH))

    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        created_files.append(str(CONFIG_PATH))

    return created_files
