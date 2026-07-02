from __future__ import annotations

from typing import Literal

EventType = Literal[
    "poll.start",
    "poll.success",
    "poll.failure",
    "metric.evaluated",
    "metric.suppressed",
    "alert.triggered",
    "alert.reminded",
    "alert.recovered",
    "alert.suppressed",
    "warmup.started",
    "warmup.base_temp_entered",
    "slack.message_sent",
    "slack.message_updated",
    "slack.user_action",
    "slack.thread_command",
    "slack.slash_command",
    "slack.bot_response",
    "alert.state_changed",
]
