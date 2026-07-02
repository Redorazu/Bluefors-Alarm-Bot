from __future__ import annotations

from typing import TYPE_CHECKING

from alarm_bot.slack.actions import register_actions
from alarm_bot.slack.commands import register_commands
from alarm_bot.slack.messages import HELP_TEXT
from alarm_bot.slack.thread_handler import (
    find_alert_id_from_thread,
    parse_snooze_args,
    parse_thread_command,
)
from alarm_bot.time_utils import format_local_timestamp

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext


def create_bolt_app(ctx: AppContext):
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=ctx.env.slack_bot_token)
    register_commands(app, ctx)
    register_actions(app, ctx)
    _register_thread_messages(app, ctx)
    _register_channel_welcome(app, ctx)
    ctx.bolt_app = app
    handler = SocketModeHandler(app, ctx.env.slack_app_token)
    return app, handler


def _register_thread_messages(app, ctx: AppContext) -> None:
    @app.event("message")
    def on_message(event, logger, say):
        if event.get("bot_id") or event.get("subtype"):
            return
        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return
        channel = event.get("channel")
        user_id = event.get("user", "")
        text = event.get("text", "")

        alert_id = find_alert_id_from_thread(ctx, thread_ts)
        cmd, args = parse_thread_command(text)
        if not cmd:
            return

        ctx.audit.log(
            "slack.thread_command",
            alert_id=alert_id,
            user_id=user_id,
            channel_id=channel,
            thread_ts=thread_ts,
            payload={"raw_text": text, "parsed_command": cmd},
        )

        try:
            reply = _handle_thread(ctx, cmd, args, alert_id, user_id)
            if reply and ctx.slack_notifier:
                ctx.slack_notifier.reply_text(channel, reply, thread_ts=thread_ts)
            ctx.audit.log(
                "slack.bot_response",
                alert_id=alert_id,
                user_id=user_id,
                payload={"response_kind": cmd, "success": True},
            )
        except Exception as exc:
            logger.exception("thread command failed")
            if ctx.slack_notifier:
                ctx.slack_notifier.reply_text(
                    channel, f"指令失敗: {exc}", thread_ts=thread_ts
                )


def _register_channel_welcome(app, ctx: AppContext) -> None:
    @app.event("member_joined_channel")
    def on_member_joined_channel(event, context, client, logger):
        if event.get("user") != context.bot_user_id:
            return

        channel = event["channel"]
        welcome = (
            "👋 已加入此頻道。我是 *Bluefors Alarm Bot*，"
            "負責監控 Bluefors 系統並發送示警。\n\n"
            f"{HELP_TEXT}"
        )

        try:
            client.chat_postMessage(channel=channel, text=welcome)
            ctx.audit.log(
                "slack.message_sent",
                channel_id=channel,
                payload={"message_kind": "channel_welcome"},
            )
        except Exception:
            logger.exception("failed to send channel welcome message")


def _handle_thread(
    ctx: AppContext,
    cmd: str,
    args: list[str],
    alert_id: str | None,
    user_id: str,
) -> str | None:
    if cmd == "help":
        return HELP_TEXT

    if cmd == "status":
        from alarm_bot.slack.commands import _status_all

        return _status_all(ctx)

    if cmd == "ack" and alert_id:
        alert = ctx.alert_manager.change_status(alert_id, "ACKNOWLEDGED", user_id)
        if alert and ctx.slack_notifier:
            ctx.slack_notifier.update_alert_message(
                alert, f":white_check_mark: 已由 <@{user_id}> 確認"
            )
        return f"<@{user_id}> 已確認已知悉。"

    if cmd == "ignore" and alert_id:
        ctx.alert_manager.change_status(alert_id, "IGNORED", user_id)
        return f"<@{user_id}> 已忽略此次異常。"

    if cmd == "mute" and alert_id:
        alert = ctx.alert_manager.get_alert(alert_id)
        if alert:
            ctx.alert_manager.mute_metric(alert.metric_id, user_id, True)
            return f"<@{user_id}> 已關閉 `{alert.metric_id}` 警報。"
        return "找不到對應示警。"

    if cmd == "snooze":
        minutes = parse_snooze_args(args)
        if alert_id:
            alert = ctx.alert_manager.get_alert(alert_id)
            if alert:
                until = ctx.alert_manager.snooze_metric(alert.metric_id, minutes, user_id)
                return f"<@{user_id}> 已靜音 `{alert.metric_id}` 至 {format_local_timestamp(until)}"
        return "找不到對應示警。"

    return f"未知指令 `{cmd}`。輸入 help 查看說明。"
