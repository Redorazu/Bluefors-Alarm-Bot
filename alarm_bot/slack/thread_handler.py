from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext


THREAD_COMMANDS = {
    "status": "status",
    "狀態": "status",
    "st": "status",
    "ack": "ack",
    "確認": "ack",
    "收到": "ack",
    "ignore": "ignore",
    "忽略": "ignore",
    "mute": "mute",
    "關閉": "mute",
    "關掉警報": "mute",
    "snooze": "snooze",
    "靜音": "snooze",
    "help": "help",
    "幫助": "help",
}


def parse_thread_command(text: str) -> tuple[str, list[str]]:
    text = text.strip()
    if not text:
        return "", []
    parts = text.split()
    cmd = parts[0].lower()
    mapped = THREAD_COMMANDS.get(cmd, cmd)
    return mapped, parts[1:]


def find_alert_id_from_thread(ctx: AppContext, thread_ts: str) -> str | None:
    for alert in ctx.alert_manager.state.alerts.values():
        if alert.thread_ts == thread_ts or alert.slack_ts == thread_ts:
            return alert.alert_id
    return None


def parse_snooze_args(args: list[str]) -> int:
    if not args:
        return 30
    try:
        return int(args[0])
    except ValueError:
        return 30
