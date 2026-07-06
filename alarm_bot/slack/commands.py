from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from alarm_bot.slack.messages import (
    SlashResponse,
    build_alerts_list_blocks,
    build_help_blocks,
    build_metrics_list_blocks,
    build_phase_status_text,
    build_status_blocks,
    build_status_single_blocks,
    build_warmup_status_text,
    format_metric_label,
)
from alarm_bot.time_utils import format_local_timestamp

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext


def respond_in_channel(respond, response: SlashResponse | str) -> None:
    if isinstance(response, str):
        respond(text=response, response_type="in_channel")
        return
    kwargs: dict = {"text": response.text, "response_type": "in_channel"}
    if response.blocks:
        kwargs["blocks"] = response.blocks
    respond(**kwargs)


def register_commands(app, ctx: AppContext) -> None:
    @app.command("/bluefors")
    def handle_bluefors(ack, respond, command, logger):
        ack()
        user_id = command.get("user_id", "")
        text = (command.get("text") or "").strip()
        parts = text.split()
        sub = parts[0].lower() if parts else "help"
        args = parts[1:]

        ctx.audit.log(
            "slack.slash_command",
            user_id=user_id,
            channel_id=command.get("channel_id"),
            payload={"command": sub, "args": args},
        )

        try:
            response = _dispatch(ctx, sub, args, user_id)
            respond_in_channel(respond, response)
            ctx.audit.log(
                "slack.bot_response",
                user_id=user_id,
                payload={"response_kind": sub, "success": True},
            )
        except Exception as exc:
            logger.exception("slash command failed")
            respond_in_channel(respond, f"指令執行失敗: {exc}")
            ctx.audit.log(
                "slack.bot_response",
                user_id=user_id,
                payload={"response_kind": sub, "success": False, "detail": str(exc)},
            )


def _dispatch(ctx: AppContext, sub: str, args: list[str], user_id: str) -> SlashResponse | str:
    if sub in ("help", ""):
        return build_help_blocks(ctx.yaml_config.metrics)

    if sub == "metrics":
        return _metrics_list(ctx)

    if sub == "status":
        if args:
            return _status_single(ctx, args[0])
        return _status_all(ctx)

    if sub == "alerts":
        return build_alerts_list_blocks(
            ctx.alert_manager.list_active_alerts(),
            metrics=ctx.yaml_config.metrics,
        )

    if sub == "muted":
        return _muted_status(ctx)

    if sub == "snoozed":
        return _snoozed_status(ctx)

    if sub == "policy":
        warmup = build_warmup_status_text(ctx.alert_manager.get_warmup_status())
        muted = _muted_status(ctx)
        snoozed = _snoozed_status(ctx)
        return f"{warmup}\n\n{muted}\n\n{snoozed}"

    if sub == "phase":
        return build_phase_status_text(ctx.alert_manager.get_warmup_status())

    if sub == "warmup":
        if not args:
            return _warmup_status(ctx)
        action = args[0].lower()
        if action == "start":
            note = " ".join(args[1:]).strip()
            ctx.alert_manager.start_warmup_mode(
                source="manual",
                started_by=user_id,
                note=note,
            )
            return "已啟動升溫標籤（系統升溫中，部分示警已抑制）。"
        if action == "stop":
            ctx.alert_manager.enter_base_temp_mode(
                reason="manual",
                actor=user_id,
                tmixing_k=_current_tmixing_k(ctx),
            )
            return "已關閉升溫標籤，完整監控示警已恢復。"
        return _warmup_status(ctx)

    if sub == "ack" and args:
        alert = ctx.alert_manager.change_status(args[0], "ACKNOWLEDGED", user_id)
        if not alert:
            return f"找不到示警 `{args[0]}`"
        if ctx.slack_notifier:
            ctx.slack_notifier.update_alert_message(
                alert, f":white_check_mark: 已由 <@{user_id}> 確認"
            )
        return f"已確認示警 `{args[0]}`"

    if sub == "ignore" and args:
        alert = ctx.alert_manager.change_status(args[0], "IGNORED", user_id)
        if not alert:
            return f"找不到示警 `{args[0]}`"
        return f"已忽略示警 `{args[0]}`，恢復正常前不再重複通知。"

    if sub == "snooze" and len(args) >= 2:
        metric_id, minutes_s = args[0], args[1]
        try:
            minutes = int(minutes_s)
        except ValueError:
            return "分鐘數必須為整數"
        until = ctx.alert_manager.snooze_metric(metric_id, minutes, user_id)
        return (
            f"已靜音 {format_metric_label(metric_id, ctx.yaml_config.metrics)} "
            f"至 {format_local_timestamp(until)}"
        )

    if sub == "mute" and args:
        metric_id = args[0]
        ctx.alert_manager.mute_metric(metric_id, user_id, True)
        return f"已關閉 {format_metric_label(metric_id, ctx.yaml_config.metrics)} 的警報通知。"

    if sub == "unmute" and args:
        metric_id = args[0]
        ctx.alert_manager.mute_metric(metric_id, user_id, False)
        return f"已重新開啟 {format_metric_label(metric_id, ctx.yaml_config.metrics)} 的警報通知。"

    if sub == "mute-all":
        for m in ctx.yaml_config.metrics:
            ctx.alert_manager.mute_metric(m.id, user_id, True)
        return "已關閉所有指標的警報通知。"

    if sub == "unmute-all":
        for m in ctx.yaml_config.metrics:
            ctx.alert_manager.mute_metric(m.id, user_id, False)
        return "已重新開啟所有指標的警報通知。"

    if sub == "clear":
        if not args or args[0].lower() != "confirm":
            return (
                "⚠️ 此操作將清除所有 alerts/state（含 mute、snooze、升溫標籤狀態）。\n"
                "若確定執行，請輸入：`/bluefors clear confirm`"
            )
        summary = ctx.alert_manager.clear_all_state(user_id)
        return (
            "✅ 已清除所有留存 state。\n"
            f"• alerts: {summary['alerts']}\n"
            f"• muted: {summary['muted']}\n"
            f"• snoozed: {summary['snoozed']}"
        )

    if sub == "history":
        alert_id = args[0] if args else None
        events = ctx.audit.query(alert_id=alert_id, limit=20)
        if not events:
            return "沒有審計紀錄。"
        lines = ["*最近審計事件:*"]
        for e in events:
            ts_raw = str(e.get("ts") or "")
            ts_display = _format_history_timestamp(ts_raw)
            lines.append(
                f"• {ts_display} (`{ts_raw}`) {e.get('event_type')} "
                f"alert={e.get('alert_id')} metric={e.get('metric_id')}"
            )
        return "\n".join(lines)

    if sub == "notifications":
        notes = ctx.bluefors_client.fetch_notifications()
        if not notes:
            return "CS 目前沒有 notifications。"
        lines = ["*Control Software notifications:*"]
        for n in notes[:15]:
            lines.append(
                f"• [{n.get('type')}/{n.get('severity')}] {n.get('title')}: {n.get('message', '')[:80]}"
            )
        return "\n".join(lines)

    if sub == "paths":
        snap = ctx.last_snapshot
        if not snap:
            try:
                snap = ctx.bluefors_client.fetch_snapshot()
                ctx.last_snapshot = snap
            except Exception as exc:
                return f"無法取得 snapshot: {exc}"
        lines = ["*設定的 value_path 對照:*"]
        for m in ctx.yaml_config.metrics:
            found = m.value_path in snap.nodes
            lines.append(f"• `{m.value_path}` ({m.id}): {'OK' if found else 'NOT FOUND'}")
        return "\n".join(lines)

    return f"未知子指令 `{sub}`。使用 `/bluefors help` 查看說明。"


def _metrics_list(ctx: AppContext) -> SlashResponse | str:
    try:
        snap = ctx.last_snapshot or ctx.bluefors_client.fetch_snapshot()
        ctx.last_snapshot = snap
    except Exception as exc:
        return f"無法取得 snapshot: {exc}"

    from alarm_bot.bluefors.extractor import extract_all

    readings = extract_all(snap, ctx.yaml_config.metrics)
    readings_by_id = {reading.metric_id: reading for reading in readings}
    return build_metrics_list_blocks(ctx.yaml_config.metrics, readings_by_id)


def _status_all(ctx: AppContext) -> SlashResponse | str:
    try:
        snap = ctx.bluefors_client.fetch_snapshot()
        ctx.last_snapshot = snap
        info = ctx.bluefors_client.fetch_system_info()
    except Exception as exc:
        return f"無法取得狀態: {exc}"
    return build_status_blocks(
        snap,
        ctx.yaml_config,
        info,
        warmup_status=ctx.alert_manager.get_warmup_status(),
        active_alert_count=len(ctx.alert_manager.list_active_alerts()),
    )


def _status_single(ctx: AppContext, metric_id: str) -> SlashResponse | str:
    metric = next((m for m in ctx.yaml_config.metrics if m.id == metric_id), None)
    if not metric:
        return f"找不到指標 `{metric_id}`"
    try:
        snap = ctx.bluefors_client.fetch_snapshot()
        ctx.last_snapshot = snap
    except Exception as exc:
        return f"無法取得狀態: {exc}"
    from alarm_bot.bluefors.extractor import extract_metric
    from alarm_bot.monitoring.metric_tracking import is_reading_present

    reading = extract_metric(snap, metric)
    if metric.optional and not is_reading_present(reading):
        return f"*{metric.name}*: 未安裝（無讀值）"
    return build_status_single_blocks(metric, reading)


def _warmup_status(ctx: AppContext) -> str:
    status = ctx.alert_manager.get_warmup_status()
    text = build_warmup_status_text(status)
    try:
        from alarm_bot.monitoring.phase_detector import PhaseDetector

        snap = ctx.last_snapshot or ctx.bluefors_client.fetch_snapshot()
        ctx.last_snapshot = snap
        detector = PhaseDetector(ctx.yaml_config.operating_phases)
        temps = detector.read_temperatures(snap)
        t50k = temps.get("t50k")
        if t50k and t50k.value_k is not None:
            text += f"\n• 目前 t50k: `{t50k.value_k}` K"
        elif t50k and t50k.over_range:
            text += "\n• 目前 t50k: over-range"
    except Exception:
        pass
    return text


def _current_tmixing_k(ctx: AppContext) -> float | None:
    try:
        from alarm_bot.monitoring.phase_detector import PhaseDetector

        snap = ctx.last_snapshot or ctx.bluefors_client.fetch_snapshot()
        ctx.last_snapshot = snap
        detector = PhaseDetector(ctx.yaml_config.operating_phases)
        tmixing = detector.read_temperatures(snap).get("tmixing")
        if not tmixing or tmixing.over_range:
            return None
        return tmixing.value_k
    except Exception:
        return None


def _muted_status(ctx: AppContext) -> str:
    muted_ids = [metric_id for metric_id, muted in ctx.alert_manager.state.metric_muted.items() if muted]
    if not muted_ids:
        return "*Muted 指標:* 無"
    lines = ["*Muted 指標:*"]
    metrics = ctx.yaml_config.metrics
    for metric_id in sorted(muted_ids):
        lines.append(f"• {format_metric_label(metric_id, metrics)}")
    return "\n".join(lines)


def _snoozed_status(ctx: AppContext) -> str:
    now = datetime.now(UTC)
    active: list[tuple[str, datetime]] = []
    for metric_id, until in ctx.alert_manager.state.metric_snooze_until.items():
        try:
            dt = datetime.fromisoformat(until)
        except ValueError:
            continue
        if dt > now:
            active.append((metric_id, dt))

    if not active:
        return "*Snoozed 指標:* 無"

    lines = ["*Snoozed 指標:*"]
    metrics = ctx.yaml_config.metrics
    for metric_id, until in sorted(active, key=lambda x: x[0]):
        lines.append(
            f"• {format_metric_label(metric_id, metrics)} until "
            f"`{format_local_timestamp(until)}`"
        )
    return "\n".join(lines)


def _format_history_timestamp(ts_raw: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_raw)
    except ValueError:
        return ts_raw
    return format_local_timestamp(dt)
