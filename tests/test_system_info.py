from __future__ import annotations

from alarm_bot.bluefors.system_info import display_system_name, display_system_version


def test_display_system_version_prefers_sw_version():
    assert display_system_version({"sw_version": "10.0", "system_version": "v2.2"}) == "10.0"


def test_display_system_version_falls_back_to_system_version():
    assert display_system_version({"system_version": "v2.2", "api_version": "v2.2"}) == "v2.2"


def test_display_system_version_falls_back_to_api_version():
    assert display_system_version({"api_version": "5.0"}) == "5.0"


def test_display_system_name_uses_default_when_missing():
    assert display_system_name(None, "Bluefors XLD1000") == "Bluefors XLD1000"
    assert display_system_name({"system_name": ""}, "Bluefors XLD1000") == "Bluefors XLD1000"
