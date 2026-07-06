from datetime import UTC, datetime
from types import SimpleNamespace

from alarm_bot.bluefors.models import SystemSnapshot
from alarm_bot.config import AppYamlConfig
from alarm_bot.slack.commands import _dispatch


def _node(value: str) -> dict:
    return {
        "content": {
            "latest_valid_value": {
                "value": value,
                "status": "SYNCHRONIZED",
                "outdated": False,
            }
        }
    }


class _FakeAlertManager:
    def __init__(self) -> None:
        self.called: dict | None = None

    def enter_base_temp_mode(self, *, reason: str, actor: str, tmixing_k: float | None = None) -> None:
        self.called = {"reason": reason, "actor": actor, "tmixing_k": tmixing_k}

    def get_warmup_status(self) -> dict:
        return {"active": True, "source": "manual", "started_by": "U1", "started_at": None, "note": ""}


class _FakeBlueforsClient:
    def fetch_snapshot(self) -> SystemSnapshot:
        return SystemSnapshot(
            fetched_at=datetime.now(UTC),
            nodes={"mapper.bf.temperatures.tmixing": _node("0.05")},
            node_count=1,
        )


def test_warmup_stop_passes_current_tmixing_to_base_temp_mode():
    ctx = SimpleNamespace(
        yaml_config=AppYamlConfig(metrics=[]),
        alert_manager=_FakeAlertManager(),
        bluefors_client=_FakeBlueforsClient(),
        last_snapshot=None,
    )

    msg = _dispatch(ctx, "warmup", ["stop"], "U999")

    assert msg == "已關閉升溫標籤，完整監控示警已恢復。"
    assert ctx.alert_manager.called == {
        "reason": "manual",
        "actor": "U999",
        "tmixing_k": 0.05,
    }
