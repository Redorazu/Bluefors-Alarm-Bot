from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from alarm_bot.slack.messages import (
    build_alert_blocks,
    build_base_temp_mode_announcement_blocks,
    build_base_temp_mode_label_blocks,
    build_recovery_blocks,
    build_status_text,
    build_warmup_label_blocks,
)
from alarm_bot.state.store import AlertRecord

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.client = WebClient(token=ctx.env.slack_bot_token)
        self.channel = ctx.env.slack_alert_channel_id

    def on_alert_notify(self, alert: AlertRecord, kind: str) -> None:
        if kind == "alert":
            self.send_alert(alert)
        elif kind == "recovery":
            self.send_recovery(alert)
        elif kind == "reminder":
            self.send_reminder(alert)

    def on_warmup_notify(self, kind: str, payload: dict) -> None:
        if kind == "started":
            self.send_warmup_started(payload)
        elif kind == "base_temp_entered":
            self.send_base_temp_mode_entered(payload)

    def send_warmup_started(self, payload: dict) -> None:
        blocks = build_warmup_label_blocks(
            source=str(payload.get("source", "manual")),
            started_by=str(payload.get("started_by", "system")),
            note=str(payload.get("note", "")),
            started_at=self.ctx.alert_manager.state.warmup_mode.started_at,
        )
        text = ":fire: 升溫模式已啟動"
        try:
            resp = self.client.chat_postMessage(channel=self.channel, text=text, blocks=blocks)
            ts = resp.get("ts")
            if ts:
                self.ctx.alert_manager.attach_warmup_slack_message(self.channel, ts)
            self.ctx.audit.log(
                "slack.message_sent",
                channel_id=self.channel,
                payload={"message_kind": "warmup_started", "message_ts": ts},
            )
        except SlackApiError as exc:
            logger.error("Failed to send warmup label: %s", exc.response["error"])

    def send_base_temp_mode_entered(self, payload: dict) -> None:
        channel = payload.get("slack_channel") or self.channel
        ts = payload.get("slack_ts")
        reason = str(payload.get("reason", "manual"))
        tmixing_k = payload.get("tmixing_k")
        blocks = build_base_temp_mode_label_blocks(reason=reason, tmixing_k=tmixing_k)
        text = ":snowflake: 已進入低溫模式"
        try:
            if channel and ts:
                self.client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
                self.ctx.audit.log(
                    "slack.message_updated",
                    channel_id=channel,
                    payload={"message_kind": "base_temp_mode_entered", "message_ts": ts},
                )
            else:
                self.client.chat_postMessage(channel=self.channel, text=text, blocks=blocks)
                self.ctx.audit.log(
                    "slack.message_sent",
                    channel_id=self.channel,
                    payload={"message_kind": "base_temp_mode_entered"},
                )

            if reason == "auto_tmixing":
                announcement_blocks = build_base_temp_mode_announcement_blocks(tmixing_k=tmixing_k)
                announcement_text = ":snowflake: 系統已進入低溫模式"
                resp = self.client.chat_postMessage(
                    channel=self.channel,
                    text=announcement_text,
                    blocks=announcement_blocks,
                )
                self.ctx.audit.log(
                    "slack.message_sent",
                    channel_id=self.channel,
                    payload={
                        "message_kind": "base_temp_mode_announcement",
                        "message_ts": resp.get("ts"),
                        "tmixing_k": tmixing_k,
                    },
                )
        except SlackApiError as exc:
            logger.error("Failed to notify base temp mode entry: %s", exc.response["error"])

    def send_alert(self, alert: AlertRecord) -> None:
        mention = self.ctx.yaml_config.slack.mention_channel_on_critical
        blocks = build_alert_blocks(alert, mention_channel=mention)
        text = f"[{alert.severity.upper()}] {alert.metric_id}: {alert.value}"
        try:
            resp = self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
            )
            ts = resp.get("ts")
            if ts:
                self.ctx.alert_manager.attach_slack_message(alert.alert_id, self.channel, ts)
            self.ctx.audit.log(
                "slack.message_sent",
                alert_id=alert.alert_id,
                metric_id=alert.metric_id,
                channel_id=self.channel,
                payload={"message_kind": "alert", "message_ts": ts},
            )
        except SlackApiError as exc:
            logger.error("Failed to send alert: %s", exc.response["error"])

    def send_reminder(self, alert: AlertRecord) -> None:
        channel = alert.slack_channel or self.channel
        thread_ts = alert.thread_ts
        text = (
            f":repeat: *提醒* — `{alert.metric_id}` 仍為 *{alert.severity}*，"
            f"當前值: `{alert.value}` | Alert ID: `{alert.alert_id}`"
        )
        try:
            self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
            )
            self.ctx.audit.log(
                "slack.message_sent",
                alert_id=alert.alert_id,
                metric_id=alert.metric_id,
                channel_id=channel,
                thread_ts=thread_ts,
                payload={"message_kind": "reminder"},
            )
        except SlackApiError as exc:
            logger.error("Failed to send reminder: %s", exc.response["error"])

    def send_recovery(self, alert: AlertRecord) -> None:
        blocks = build_recovery_blocks(alert)
        text = f"[RECOVERED] {alert.metric_id}: {alert.value}"
        try:
            thread_ts = alert.thread_ts
            self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts,
            )
            self.ctx.audit.log(
                "slack.message_sent",
                alert_id=alert.alert_id,
                metric_id=alert.metric_id,
                channel_id=self.channel,
                payload={"message_kind": "recovery"},
            )
        except SlackApiError as exc:
            logger.error("Failed to send recovery: %s", exc.response["error"])

    def send_api_error(self, error: str) -> None:
        text = f":plug: Bluefors API 連線異常: {error}"
        try:
            self.client.chat_postMessage(channel=self.channel, text=text)
        except SlackApiError:
            pass

    def reply_status(self, channel: str, thread_ts: str | None = None) -> None:
        try:
            info = self.ctx.bluefors_client.fetch_system_info()
        except Exception:
            info = None
        text = build_status_text(
            self.ctx.last_snapshot,
            self.ctx.yaml_config,
            info,
            warmup_status=self.ctx.alert_manager.get_warmup_status(),
            active_alert_count=len(self.ctx.alert_manager.list_active_alerts()),
        )
        self.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)

    def reply_text(self, channel: str, text: str, thread_ts: str | None = None) -> None:
        self.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)

    def update_alert_message(
        self,
        alert: AlertRecord,
        status_note: str,
        *,
        hide_interactions: bool = False,
    ) -> None:
        if not alert.slack_channel or not alert.slack_ts:
            return
        mention = self.ctx.yaml_config.slack.mention_channel_on_critical
        blocks = build_alert_blocks(alert, mention_channel=mention)
        if hide_interactions:
            blocks = [
                block
                for block in blocks
                if block.get("type") != "actions"
                and not str(block.get("block_id", "")).startswith("snooze_")
            ]
        blocks.insert(
            1,
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": status_note}],
            },
        )
        try:
            self.client.chat_update(
                channel=alert.slack_channel,
                ts=alert.slack_ts,
                text=f"[{alert.status}] {alert.metric_id}",
                blocks=blocks,
            )
            self.ctx.audit.log(
                "slack.message_updated",
                alert_id=alert.alert_id,
                channel_id=alert.slack_channel,
                payload={"message_ts": alert.slack_ts, "new_status": alert.status},
            )
        except SlackApiError as exc:
            logger.warning("Failed to update message: %s", exc.response["error"])
