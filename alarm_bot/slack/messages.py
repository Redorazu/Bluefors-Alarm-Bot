from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from alarm_bot.bluefors.extractor import extract_all
from alarm_bot.bluefors.models import VALID_SAMPLE_STATUSES, MetricReading, SystemSnapshot
from alarm_bot.config import AppYamlConfig, MetricConfig
from alarm_bot.monitoring.metric_tracking import should_show_in_status
from alarm_bot.state.store import AlertRecord
from alarm_bot.time_utils import format_local_timestamp
from alarm_bot.value_formatter import format_metric_value

CATEGORY_LABELS: dict[str | None, str] = {
    "temperature": "溫度",
    "pressure": "壓力",
    "flow": "流量",
    "compressor": "壓縮機",
    "turbo": "Turbo",
    "sensor_connection": "感測器連線",
    None: "其他",
}

CATEGORY_DISPLAY_ORDER: tuple[str | None, ...] = (
    "temperature",
    "pressure",
    "flow",
    "compressor",
    "turbo",
    "sensor_connection",
    None,
)

MAX_ALERT_BLOCKS = 20
MULTI_COLUMN_CATEGORIES: frozenset[str | None] = frozenset({"temperature", "pressure"})


@dataclass
class SlashResponse:
    text: str
    blocks: list[dict] | None = None


HELP_TEXT = """*Bluefors Bot 指令*
• `/bluefors status` — 即時監控讀數
• `/bluefors status <metric_id>` — 單一指標
• `/bluefors alerts` — 進行中示警
• `/bluefors phase` — 運行狀態（升溫 / 低溫）
• `/bluefors warmup` — 升溫模式狀態
• `/bluefors warmup start [備註]` — 手動啟動升溫模式
• `/bluefors warmup stop` — 手動結束升溫模式，恢復完整監控
• `/bluefors muted` — 已關閉通知的指標
• `/bluefors snoozed` — 目前靜音中的指標
• `/bluefors policy` — warmup + mute + snooze 總覽
• `/bluefors ack <alert_id>` — 確認示警
• `/bluefors ignore <alert_id>` — 忽略此次異常
• `/bluefors snooze <metric_id> <分鐘>` — 靜音
• `/bluefors mute <metric_id>` — 關閉指標警報
• `/bluefors unmute <metric_id>` — 重新開啟
• `/bluefors mute-all` / `unmute-all` — 全部靜音/開啟
• `/bluefors clear [confirm]` — 清除所有 alerts/state（危險操作）
• `/bluefors history` — 最近審計事件
• `/bluefors notifications` — CS 內建通知

*Thread 關鍵字:* `status`/`狀態`, `ack`/`確認`, `ignore`/`忽略`, `mute`/`關閉`, `snooze 60`, `help`
"""

SEVERITY_COLORS = {
    "info": "#439FE0",
    "warning": "#ECB22E",
    "critical": "#E01E5A",
    "recovery": "#2EB67D",
}


def _severity_emoji(severity: str) -> str:
    return {"info": ":information_source:", "warning": ":warning:", "critical": ":rotating_light:"}.get(
        severity, ":bell:"
    )


def build_alert_blocks(alert: AlertRecord, mention_channel: bool = False) -> list[dict]:
    emoji = _severity_emoji(alert.severity)
    header = f"{emoji} {alert.severity.upper()} — {alert.metric_id}"
    mention = "<!channel> " if mention_channel and alert.severity == "critical" else ""

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header[:150], "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*記錄值:*\n`{alert.value}`"},
                {"type": "mrkdwn", "text": f"*狀態:*\n`{alert.status}`"},
                {"type": "mrkdwn", "text": f"*閾值:*\n`{alert.condition} {alert.threshold}`"},
                {"type": "mrkdwn", "text": f"*Alert ID:*\n`{alert.alert_id}`"},
            ],
        },
    ]
    if alert.playbook:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*建議處置:*\n{alert.playbook}"},
            }
        )
    if mention:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": mention}}
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"alert_actions_{alert.alert_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "確認已知悉"},
                    "action_id": "alert_ack",
                    "value": alert.alert_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "忽略此次"},
                    "action_id": "alert_ignore",
                    "value": alert.alert_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "關閉此指標警報"},
                    "action_id": "alert_mute_metric",
                    "value": alert.metric_id,
                    "style": "danger",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "查看即時狀態"},
                    "action_id": "alert_status",
                    "value": alert.alert_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "啟動升溫模式"},
                    "action_id": "alert_warmup_start",
                    "value": alert.alert_id,
                    "style": "primary",
                },
            ],
        }
    )
    blocks.append(
        {
            "type": "section",
            "block_id": f"snooze_{alert.alert_id}",
            "text": {"type": "mrkdwn", "text": "*靜音時長:*"},
            "accessory": {
                "type": "static_select",
                "action_id": "alert_snooze",
                "placeholder": {"type": "plain_text", "text": "選擇靜音時間"},
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "5 分鐘"},
                        "value": f"{alert.metric_id}:5",
                    },
                    {
                        "text": {"type": "plain_text", "text": "10 分鐘"},
                        "value": f"{alert.metric_id}:10",
                    },
                    {
                        "text": {"type": "plain_text", "text": "30 分鐘"},
                        "value": f"{alert.metric_id}:30",
                    },
                    {
                        "text": {"type": "plain_text", "text": "1 小時"},
                        "value": f"{alert.metric_id}:60",
                    },
                    {
                        "text": {"type": "plain_text", "text": "4 小時"},
                        "value": f"{alert.metric_id}:240",
                    },
                ],
            },
        }
    )
    return blocks


def build_recovery_blocks(alert: AlertRecord) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":white_check_mark: *已恢復* — `{alert.metric_id}`\n"
                    f"當前值: {alert.value} | Alert ID: `{alert.alert_id}`"
                ),
            },
        }
    ]


def format_sample_status_suffix(metric: MetricConfig, reading: MetricReading) -> str:
    if reading.value_type == "sample_status":
        return ""
    if metric.id == "magnet_enabled":
        return ""
    status = reading.sample_status
    if not status:
        return ""
    if metric.category == "sensor_connection":
        return f" ({status})"
    if status not in VALID_SAMPLE_STATUSES:
        return f" ({status})"
    return ""


def format_metric_status_line(metric: MetricConfig, reading: MetricReading) -> str:
    value, display_unit = format_metric_value(metric, reading)
    unit = f" {display_unit}" if display_unit else ""
    suffix = format_sample_status_suffix(metric, reading)
    return f"• *{reading.name}*: `{value}`{unit}{suffix}"


def format_snapshot_timestamp(fetched_at: datetime) -> str:
    return fetched_at.astimezone().strftime("%Y-%m-%d %H:%M")


def _status_mode_label(warmup_status: dict | None) -> str:
    warmup = warmup_status or {}
    return "升溫模式" if warmup.get("active") else "低溫模式"


def _display_system_name(system_info: dict | None, default_system_name: str) -> str:
    if not system_info:
        return default_system_name
    name = str(system_info.get("system_name", "")).strip()
    return name or default_system_name


def _display_system_version(system_info: dict | None) -> str:
    if not system_info:
        return "n/a"
    for key in ("sw_version", "system_version", "api_version"):
        val = system_info.get(key)
        text = str(val).strip() if val is not None else ""
        if text:
            return text
    return "n/a"


def collect_status_groups(
    snapshot: SystemSnapshot,
    yaml_config: AppYamlConfig,
) -> dict[str | None, list[tuple[MetricConfig, MetricReading]]]:
    readings = extract_all(snapshot, yaml_config.metrics)
    reading_by_id = {r.metric_id: r for r in readings}
    groups: dict[str | None, list[tuple[MetricConfig, MetricReading]]] = defaultdict(list)

    for metric in yaml_config.metrics:
        reading = reading_by_id.get(metric.id)
        if reading is None:
            continue
        if not should_show_in_status(metric, reading, reading_by_id):
            continue
        groups[metric.category].append((metric, reading))
    return groups


def build_status_text(
    snapshot: SystemSnapshot | None,
    yaml_config: AppYamlConfig,
    system_info: dict | None = None,
    *,
    warmup_status: dict | None = None,
    active_alert_count: int = 0,
) -> str:
    lines = ["*Bluefors 即時狀態*"]
    default_system_name = yaml_config.slack.default_system_name

    lines.append(f"運行: *{_status_mode_label(warmup_status)}* | 進行中示警: *{active_alert_count}*")

    if system_info:
        lines.append(
            f"系統: {_display_system_name(system_info, default_system_name)} | "
            f"版本: {_display_system_version(system_info)}"
        )
    if snapshot is None:
        lines.append("_尚無快照資料，請稍後再試。_")
        return "\n".join(lines)

    groups = collect_status_groups(snapshot, yaml_config)

    for category in CATEGORY_DISPLAY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        lines.append("")
        lines.append(f"*{CATEGORY_LABELS[category]}*")
        for metric, reading in items:
            lines.append(format_metric_status_line(metric, reading))

    lines.append("")
    lines.append(f"_快照時間: {format_snapshot_timestamp(snapshot.fetched_at)}_")
    return "\n".join(lines)


def build_status_blocks(
    snapshot: SystemSnapshot | None,
    yaml_config: AppYamlConfig,
    system_info: dict | None = None,
    *,
    warmup_status: dict | None = None,
    active_alert_count: int = 0,
) -> SlashResponse:
    fallback_text = build_status_text(
        snapshot,
        yaml_config,
        system_info,
        warmup_status=warmup_status,
        active_alert_count=active_alert_count,
    )
    if snapshot is None:
        return SlashResponse(
            text=fallback_text,
            blocks=[
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Bluefors 即時狀態", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": fallback_text},
                },
            ],
        )

    default_system_name = yaml_config.slack.default_system_name
    summary = (
        f"*運行:* {_status_mode_label(warmup_status)}\n"
        f"*進行中示警:* {active_alert_count}"
    )
    if system_info:
        summary += (
            f"\n*系統:* {_display_system_name(system_info, default_system_name)} | "
            f"*版本:* {_display_system_version(system_info)}"
        )

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Bluefors 即時狀態", "emoji": True},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]

    groups = collect_status_groups(snapshot, yaml_config)
    max_status_fields = max(1, yaml_config.slack.status_fields_per_section)
    for category in CATEGORY_DISPLAY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{CATEGORY_LABELS[category]}*",
                },
            }
        )
        lines = [format_metric_status_line(metric, reading) for metric, reading in items]
        if category in MULTI_COLUMN_CATEGORIES:
            for idx in range(0, len(lines), max_status_fields):
                chunk = lines[idx : idx + max_status_fields]
                blocks.append(
                    {
                        "type": "section",
                        "fields": [{"type": "mrkdwn", "text": line} for line in chunk],
                    }
                )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)},
                }
            )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"快照時間: {format_snapshot_timestamp(snapshot.fetched_at)}",
                }
            ],
        }
    )
    return SlashResponse(text="Bluefors 即時狀態", blocks=blocks)


def build_status_single_blocks(
    metric: MetricConfig,
    reading: MetricReading,
) -> SlashResponse:
    line = format_metric_status_line(metric, reading)
    value, display_unit = format_metric_value(metric, reading)
    value_text = f"{value} {display_unit}".strip()
    return SlashResponse(
        text=f"{metric.name}: {value_text}",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": metric.name, "emoji": True},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": line}},
        ],
    )


def build_alerts_list_text(alerts: list[AlertRecord]) -> str:
    if not alerts:
        return "目前沒有進行中的示警。"
    lines = ["*進行中的示警:*"]
    for a in alerts:
        lines.append(
            f"• `{a.alert_id}` | {a.metric_id} | {a.severity} | {a.status} | 值={a.value}"
        )
    return "\n".join(lines)


def build_alerts_list_blocks(alerts: list[AlertRecord]) -> SlashResponse:
    if not alerts:
        return SlashResponse(
            text="目前沒有進行中的示警。",
            blocks=[
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "進行中的示警", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "_目前沒有進行中的示警。_"},
                },
            ],
        )

    shown = alerts[:MAX_ALERT_BLOCKS]
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"進行中的示警 ({len(alerts)})",
                "emoji": True,
            },
        }
    ]
    for alert in shown:
        emoji = _severity_emoji(alert.severity)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{alert.severity.upper()}* — `{alert.metric_id}`",
                },
                "fields": [
                    {"type": "mrkdwn", "text": f"*記錄值:*\n`{alert.value}`"},
                    {"type": "mrkdwn", "text": f"*狀態:*\n`{alert.status}`"},
                    {"type": "mrkdwn", "text": f"*閾值:*\n`{alert.condition} {alert.threshold}`"},
                    {"type": "mrkdwn", "text": f"*Alert ID:*\n`{alert.alert_id}`"},
                ],
            }
        )

    if len(alerts) > len(shown):
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"另有 {len(alerts) - len(shown)} 筆示警未顯示，請至 Slack 搜尋或查 audit。",
                    }
                ],
            }
        )

    return SlashResponse(text=f"進行中的示警: {len(alerts)}", blocks=blocks)


def build_help_blocks() -> SlashResponse:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Bluefors Bot 指令", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*查詢*\n"
                    "• `/bluefors status` — 即時監控讀數\n"
                    "• `/bluefors status <metric_id>` — 單一指標\n"
                    "• `/bluefors alerts` — 進行中示警\n"
                    "• `/bluefors phase` — 運行狀態（升溫 / 低溫）\n"
                    "• `/bluefors paths` — 檢查 value_path\n"
                    "• `/bluefors notifications` — CS 內建通知"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*升溫模式*\n"
                    "• `/bluefors warmup` — 升溫模式狀態\n"
                    "• `/bluefors warmup start [備註]` — 手動啟動\n"
                    "• `/bluefors warmup stop` — 手動結束，恢復完整監控\n"
                    "• `/bluefors policy` — warmup + mute + snooze 總覽"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*示警操作*\n"
                    "• `/bluefors ack <alert_id>` — 確認示警\n"
                    "• `/bluefors ignore <alert_id>` — 忽略此次異常\n"
                    "• `/bluefors snooze <metric_id> <分鐘>` — 靜音\n"
                    "• `/bluefors mute <metric_id>` / `unmute` — 關閉／開啟指標\n"
                    "• `/bluefors mute-all` / `unmute-all` — 全部靜音／開啟\n"
                    "• `/bluefors clear [confirm]` — 清除所有 alerts/state\n"
                    "• `/bluefors muted` / `snoozed` — 已關閉或暫停通知的指標\n"
                    "• `/bluefors history [alert_id]` — 最近審計事件"
                ),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "*Thread 關鍵字:* `status`/`狀態`, `ack`/`確認`, `ignore`/`忽略`, "
                        "`mute`/`關閉`, `snooze 60`, `help`"
                    ),
                }
            ],
        },
    ]
    return SlashResponse(text="Bluefors Bot 指令說明", blocks=blocks)


MODE_LABELS = {
    "warmup": "升溫模式",
    "cryo_normal": "低溫模式（正常運行）",
}


WARMUP_SOURCE_LABELS = {
    "manual": "手動啟動",
    "auto_t50k": "自動偵測（t50k）",
    "auto_4k_heater": "自動偵測（4K heater）",
}


def _display_started_by(started_by: str | None) -> str:
    raw = (started_by or "").strip()
    if not raw:
        return "n/a"
    if raw in {"system", "auto"}:
        return raw
    if raw.startswith("<@") and raw.endswith(">"):
        return raw
    if raw.startswith("U") or raw.startswith("W"):
        return f"<@{raw}>"
    return raw


def build_warmup_label_blocks(
    *,
    source: str,
    started_by: str,
    note: str,
    started_at: str | None,
) -> list[dict]:
    source_label = WARMUP_SOURCE_LABELS.get(source, source)
    if source.startswith("auto_") and source not in WARMUP_SOURCE_LABELS:
        source_label = "自動偵測"
    started = _format_iso_or_na(started_at)
    starter = _display_started_by(started_by)
    text_note = f"\n備註: {note}" if note else ""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔥 升溫模式進行中", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*狀態:* 升溫 label 有效中\n"
                    f"*來源:* {source_label} (`{source}`)\n"
                    f"*啟動者:* {starter}\n"
                    f"*開始時間:* {started}{text_note}\n\n"
                    "_升溫期間抑制溫度、壓力、流量與感測器連線示警；壓縮機與 turbo 仍會示警。_"
                ),
            },
        },
    ]


BASE_TEMP_MODE_REASON_LABELS = {
    "auto_tmixing": "tmixing 已低於 100 mK（自動進入低溫模式）",
    "manual": "手動進入低溫模式",
}


def build_base_temp_mode_announcement_blocks(*, tmixing_k: float | None) -> list[dict]:
    tmixing_text = f"{tmixing_k} K" if tmixing_k is not None else "n/a"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "❄️ 進入低溫模式",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*運行階段:* 低溫模式（正常運行）\n"
                    f"*tmixing:* `{tmixing_text}`（低於 100 mK 閾值）\n"
                    f"*升溫模式:* 已關閉\n\n"
                    "_完整溫度、壓力、流量與感測器連線示警監控已恢復。_"
                ),
            },
        },
    ]


def build_base_temp_mode_label_blocks(*, reason: str, tmixing_k: float | None) -> list[dict]:
    reason_label = BASE_TEMP_MODE_REASON_LABELS.get(reason, reason)
    tmixing_text = f"{tmixing_k} K" if tmixing_k is not None else "n/a"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":snowflake: *已進入低溫模式*\n"
                    f"觸發方式: {reason_label}\n"
                    f"tmixing: `{tmixing_text}`\n"
                    f"已恢復完整監控示警。"
                ),
            },
        }
    ]


def build_warmup_status_text(status: dict) -> str:
    if not status.get("active"):
        return "*升溫模式:* 未啟用"
    source = status.get("source") or "unknown"
    source_label = WARMUP_SOURCE_LABELS.get(source, source)
    lines = [
        "*升溫模式:* 進行中",
        f"• 來源: {source_label} (`{source}`)",
        f"• 啟動者: {_display_started_by(status.get('started_by'))}",
        f"• 開始: {_format_iso_or_na(status.get('started_at'))}",
    ]
    if status.get("note"):
        lines.append(f"• 備註: {status['note']}")
    return "\n".join(lines)


def build_phase_status_text(status: dict) -> str:
    mode = status.get("mode", "cryo_normal")
    mode_label = MODE_LABELS.get(mode, mode)
    warmup = build_warmup_status_text(status)
    return f"*運行狀態:* {mode_label}\n{warmup}"


def _format_iso_or_na(value: str | None) -> str:
    if not value:
        return "n/a"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return format_local_timestamp(dt)
