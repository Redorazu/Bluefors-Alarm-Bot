from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from alarm_bot.bluefors.client import BlueforsApiClient
from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import AppYamlConfig, EnvSettings
from alarm_bot.logging.audit import AuditLogger
from alarm_bot.monitoring.alert_manager import AlertManager
from alarm_bot.monitoring.poller import MonitorPoller
from alarm_bot.state.store import StateStore

if TYPE_CHECKING:
    from alarm_bot.slack.notifier import SlackNotifier


@dataclass
class AppContext:
    env: EnvSettings
    yaml_config: AppYamlConfig
    audit: AuditLogger
    state: StateStore
    bluefors_client: BlueforsApiClient
    alert_manager: AlertManager
    poller: MonitorPoller | None = None
    slack_notifier: SlackNotifier | None = None
    last_snapshot: SystemSnapshot | None = None
    bolt_app: object | None = field(default=None, repr=False)
