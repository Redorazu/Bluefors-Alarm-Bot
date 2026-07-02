from __future__ import annotations

from typing import TYPE_CHECKING

from alarm_bot.slack.thread_handler import find_alert_id_from_thread
from alarm_bot.time_utils import format_local_timestamp

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext


def register_actions(app, ctx: AppContext) -> None:
    @app.action("alert_ack")
    def on_ack(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        alert_id = body["actions"][0]["value"]
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")

        ctx.audit.log(
            "slack.user_action",
            alert_id=alert_id,
            user_id=user_id,
            channel_id=channel,
            thread_ts=thread_ts,
            payload={"action_id": "alert_ack"},
        )

        alert = ctx.alert_manager.change_status(alert_id, "ACKNOWLEDGED", user_id)
        if alert and ctx.slack_notifier:
            ctx.slack_notifier.update_alert_message(
                alert,
                f":white_check_mark: 已由 <@{user_id}> 確認",
                hide_interactions=True,
            )
            ctx.slack_notifier.reply_text(
                channel, f"<@{user_id}> 已確認已知悉。", thread_ts=thread_ts
            )
        ctx.audit.log(
            "slack.bot_response",
            alert_id=alert_id,
            user_id=user_id,
            payload={"response_kind": "ack", "success": bool(alert)},
        )

    @app.action("alert_ignore")
    def on_ignore(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        alert_id = body["actions"][0]["value"]
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")

        ctx.audit.log(
            "slack.user_action",
            alert_id=alert_id,
            user_id=user_id,
            channel_id=channel,
            payload={"action_id": "alert_ignore"},
        )

        alert = ctx.alert_manager.change_status(alert_id, "IGNORED", user_id)
        if alert and ctx.slack_notifier:
            ctx.slack_notifier.update_alert_message(
                alert,
                f":no_entry_sign: 已由 <@{user_id}> 忽略此次異常",
                hide_interactions=True,
            )
            ctx.slack_notifier.reply_text(
                channel,
                f"<@{user_id}> 已忽略此次異常，恢復正常前不再重複通知。",
                thread_ts=thread_ts,
            )
        ctx.audit.log(
            "slack.bot_response",
            alert_id=alert_id,
            user_id=user_id,
            payload={"response_kind": "ignore", "success": bool(alert)},
        )

    @app.action("alert_mute_metric")
    def on_mute(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        metric_id = body["actions"][0]["value"]
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")

        ctx.audit.log(
            "slack.user_action",
            metric_id=metric_id,
            user_id=user_id,
            channel_id=channel,
            payload={"action_id": "alert_mute_metric"},
        )

        ctx.alert_manager.mute_metric(metric_id, user_id, True)
        if ctx.slack_notifier:
            alert_id = find_alert_id_from_thread(ctx, thread_ts) if thread_ts else None
            alert = ctx.alert_manager.get_alert(alert_id) if alert_id else None
            if alert:
                ctx.slack_notifier.update_alert_message(
                    alert,
                    f":mute: 已由 <@{user_id}> 關閉 `{metric_id}` 警報",
                    hide_interactions=True,
                )
            ctx.slack_notifier.reply_text(
                channel,
                f"<@{user_id}> 已關閉 `{metric_id}` 的警報通知。",
                thread_ts=thread_ts,
            )

    @app.action("alert_status")
    def on_status(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")
        alert_id = body["actions"][0]["value"]

        ctx.audit.log(
            "slack.user_action",
            alert_id=alert_id,
            user_id=user_id,
            channel_id=channel,
            payload={"action_id": "alert_status"},
        )

        if ctx.slack_notifier:
            ctx.slack_notifier.reply_status(channel, thread_ts=thread_ts)

    @app.action("alert_warmup_start")
    def on_warmup_start(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        alert_id = body["actions"][0]["value"]
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")

        ctx.audit.log(
            "slack.user_action",
            alert_id=alert_id,
            user_id=user_id,
            channel_id=channel,
            thread_ts=thread_ts,
            payload={"action_id": "alert_warmup_start"},
        )

        if ctx.alert_manager.state.warmup_mode.active:
            if ctx.slack_notifier:
                alert = ctx.alert_manager.get_alert(alert_id)
                if alert:
                    ctx.slack_notifier.update_alert_message(
                        alert,
                        f":fire: <@{user_id}> 嘗試啟動升溫模式（目前已在進行中）",
                        hide_interactions=True,
                    )
                ctx.slack_notifier.reply_text(
                    channel,
                    f"<@{user_id}> 升溫模式已在進行中。",
                    thread_ts=thread_ts,
                )
            ctx.audit.log(
                "slack.bot_response",
                alert_id=alert_id,
                user_id=user_id,
                payload={"response_kind": "warmup_start", "success": False, "reason": "already_active"},
            )
            return

        note = f"由示警 `{alert_id}` 按鈕手動啟動"
        ctx.alert_manager.start_warmup_mode(
            source="manual",
            started_by=user_id,
            note=note,
        )
        if ctx.slack_notifier:
            alert = ctx.alert_manager.get_alert(alert_id)
            if alert:
                ctx.slack_notifier.update_alert_message(
                    alert,
                    f":fire: 已由 <@{user_id}> 啟動升溫模式",
                    hide_interactions=True,
                )
            ctx.slack_notifier.reply_text(
                channel,
                f"<@{user_id}> 已啟動升溫模式。",
                thread_ts=thread_ts,
            )
        ctx.audit.log(
            "slack.bot_response",
            alert_id=alert_id,
            user_id=user_id,
            payload={"response_kind": "warmup_start", "success": True},
        )

    @app.action("alert_snooze")
    def on_snooze(ack, body, client, logger):
        ack()
        user_id = body.get("user", {}).get("id", "")
        channel = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("ts")
        selected = body["actions"][0]["selected_option"]["value"]
        metric_id, minutes_s = selected.split(":", 1)
        minutes = int(minutes_s)

        ctx.audit.log(
            "slack.user_action",
            metric_id=metric_id,
            user_id=user_id,
            channel_id=channel,
            payload={"action_id": "alert_snooze", "minutes": minutes},
        )

        until = ctx.alert_manager.snooze_metric(metric_id, minutes, user_id)
        if ctx.slack_notifier:
            alert_id = find_alert_id_from_thread(ctx, thread_ts) if thread_ts else None
            alert = ctx.alert_manager.get_alert(alert_id) if alert_id else None
            if alert:
                ctx.slack_notifier.update_alert_message(
                    alert,
                    f":zzz: 已由 <@{user_id}> 靜音 `{metric_id}` 至 {format_local_timestamp(until)}",
                    hide_interactions=True,
                )
            ctx.slack_notifier.reply_text(
                channel,
                f"<@{user_id}> 已靜音 `{metric_id}` 至 {format_local_timestamp(until)}",
                thread_ts=thread_ts,
            )
