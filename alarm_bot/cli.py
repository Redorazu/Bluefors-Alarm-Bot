from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from alarm_bot.config import load_yaml_config
from alarm_bot.path_suggester import load_snapshot_nodes, render_yaml_patch, suggest_metric_paths
from alarm_bot.paths import ENV_PATH

logger = logging.getLogger(__name__)

SETUP_PROMPTS = [
    ("BLUEFORS_BASE_URL", "Bluefors API base URL", "https://192.168.1.10:49098"),
    ("BLUEFORS_API_KEY", "Bluefors API key (read-only)", ""),
    ("BLUEFORS_VERIFY_SSL", "Verify SSL (true/false)", "false"),
    ("BLUEFORS_SNAPSHOT_BRANCH", "Snapshot branch (empty=full tree)", ""),
    ("SLACK_BOT_TOKEN", "Slack Bot token (xoxb-...)", ""),
    ("SLACK_APP_TOKEN", "Slack App token (xapp-...)", ""),
    ("SLACK_ALERT_CHANNEL_ID", "Slack alert channel ID", ""),
    ("POLL_INTERVAL_SECONDS", "Poll interval seconds", "30"),
]


def _write_env(values: dict[str, str]) -> None:
    lines = [f"{k}={v}\n" for k, v in values.items()]
    ENV_PATH.write_text("".join(lines), encoding="utf-8")


def cmd_setup(_: argparse.Namespace) -> int:
    from alarm_bot.bootstrap import (
        create_app_context,
        ensure_local_config_files,
        ensure_runtime_dirs,
        run_health_checks,
    )

    print("=== Bluefors Alarm Bot 初始化 ===\n")
    ensure_runtime_dirs()
    created_files = ensure_local_config_files()
    for path in created_files:
        print(f"已建立預設設定檔: {path}")

    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    values = dict(existing)
    for key, prompt, default in SETUP_PROMPTS:
        current = values.get(key, default)
        entered = input(f"{prompt} [{current}]: ").strip()
        values[key] = entered if entered else current

    _write_env(values)
    print(f"\n已寫入 {ENV_PATH}")

    ctx = create_app_context()
    ctx.state.mark_initialized()
    ok, messages = run_health_checks(ctx)
    for m in messages:
        print(m)
    if ok:
        print("\n初始化完成。執行 run 啟動 bot。")
        return 0
    print("\n連線測試有失敗項目，請檢查設定後再試。")
    return 1


def cmd_check(_: argparse.Namespace) -> int:
    from alarm_bot.bootstrap import create_app_context, run_health_checks, validate_runtime_config

    ctx = create_app_context()
    errors = validate_runtime_config(ctx)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1
    ok, messages = run_health_checks(ctx)
    for m in messages:
        print(m)
    return 0 if ok else 1


def cmd_run(_: argparse.Namespace) -> int:
    from alarm_bot.bootstrap import create_app_context, ensure_runtime_dirs, validate_runtime_config

    ensure_runtime_dirs()
    ctx = create_app_context()
    errors = validate_runtime_config(ctx)
    if errors:
        for e in errors:
            logger.error(e)
        print("設定不完整。請先執行 setup。", file=sys.stderr)
        return 1

    from alarm_bot.slack.app import create_bolt_app

    _, handler = create_bolt_app(ctx)
    if ctx.poller:
        ctx.poller.start()

    logger.info("Bluefors Alarm Bot running (Socket Mode)")
    handler.start()
    return 0


def cmd_suggest_paths(args: argparse.Namespace) -> int:
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"ERROR: snapshot file not found: {snapshot_path}")
        return 1

    yaml_cfg = load_yaml_config()
    nodes = load_snapshot_nodes(snapshot_path)
    suggestions = suggest_metric_paths(yaml_cfg.metrics, nodes)
    print(render_yaml_patch(yaml_cfg.metrics, suggestions))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bluefors Control Software monitor + Slack alerts")
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="First-time initialization wizard")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run", help="Start monitoring and Slack bot")
    p_run.set_defaults(func=cmd_run)

    p_check = sub.add_parser("check", help="Test Bluefors and Slack connectivity")
    p_check.set_defaults(func=cmd_check)

    p_suggest = sub.add_parser(
        "suggest-paths",
        help="Suggest metric value_path entries from snapshot JSON",
    )
    p_suggest.add_argument(
        "--snapshot",
        default="values_example.json",
        help="Path to snapshot JSON file (default: values_example.json)",
    )
    p_suggest.set_defaults(func=cmd_suggest_paths)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
