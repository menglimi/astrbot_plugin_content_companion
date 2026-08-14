# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from astrbot_plugin_content_companion.main import (
    ContentCompanionExtensionAPI,
    ContentCompanionPlugin,
    StandaloneCreativeHost,
)


class _Plugin:
    context = SimpleNamespace()
    config = {"creative": {"enable_creative_writing": True}}


def test_standalone_host_uses_utf8_state_file(tmp_path: Path) -> None:
    plugin = _Plugin()
    host = StandaloneCreativeHost.__new__(StandaloneCreativeHost)
    host.plugin = plugin
    host.data_dir = str(tmp_path)
    host.data_path = tmp_path / "creative_state.json"
    host.data = {"creative_projects": [{"title": "雨夜故事"}]}
    host._save_data_sync()

    payload = json.loads(host.data_path.read_text(encoding="utf-8"))
    assert payload["creative_projects"][0]["title"] == "雨夜故事"


def test_extension_api_lists_and_selects_projects() -> None:
    host = SimpleNamespace(
        _creative_projects=lambda: [
            {"id": "one", "title": "第一篇"},
            {"id": "two", "title": "第二篇"},
        ]
    )
    plugin = SimpleNamespace(host=host)
    api = ContentCompanionExtensionAPI(plugin)
    assert api.get_project(None, "one")["title"] == "第一篇"
    assert api.get_project(None, "missing")["title"] == "第二篇"


class _Config(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self) -> None:
        self.saved += 1


def _migration_plugin(config: _Config) -> ContentCompanionPlugin:
    plugin = ContentCompanionPlugin.__new__(ContentCompanionPlugin)
    plugin.config = config
    plugin.host = SimpleNamespace(
        data={"creative_projects": []},
        sync_count=0,
        save_count=0,
    )

    def sync_config() -> None:
        plugin.host.sync_count += 1

    def save_data() -> None:
        plugin.host.save_count += 1

    plugin.host._sync_config = sync_config
    plugin.host._save_data_sync = save_data
    return plugin


def test_migration_waits_for_late_host_then_imports_legacy_state() -> None:
    async def run() -> None:
        await _assert_late_host_migration()

    asyncio.run(run())


async def _assert_late_host_migration() -> None:
    config = _Config(
        {
            "migration": {"reuse_private_companion_data": True},
            "creative": {
                "enable_creative_writing": True,
                "creative_share_probability": 0.9,
                "creative_chars_per_session": 220,
            },
            "qzone": {
                "enabled": False,
                "cookie": "",
                "generated_image_enabled": False,
            },
        }
    )
    plugin = _migration_plugin(config)
    plugin._host_plugin = lambda: None

    assert await plugin._try_legacy_migration() is False
    assert "legacy_migration_completed" not in plugin.host.data

    legacy = SimpleNamespace(
        data={"creative_projects": [{"id": "old", "title": "旧作品"}]},
        enable_creative_writing=False,
        creative_inspiration_probability=0.35,
        creative_share_probability=0.6,
        creative_chars_per_session=360,
        creative_max_active_projects=4,
        creative_direction_prompt="沿用旧方向",
        enable_creative_cover_generation=True,
        creative_provider_id="creative-provider",
        creative_outline_provider_id="outline-provider",
        creative_review_provider_id="review-provider",
        enable_qzone_integration=True,
        qzone_cookie="uin=o10001; skey=test",
        enable_qzone_life_publish=True,
        enable_qzone_comment_inbox=True,
        enable_qzone_generated_image_publish=True,
    )
    plugin._host_plugin = lambda: legacy

    assert await plugin._try_legacy_migration() is True
    assert plugin.host.data["creative_projects"][0]["title"] == "旧作品"
    assert plugin.host.data["legacy_migration_completed"] is True
    assert config["creative"]["enable_creative_writing"] is False
    assert config["creative"]["creative_share_probability"] == 0.9
    assert config["creative"]["creative_chars_per_session"] == 360
    assert config["qzone"]["enabled"] is True
    assert config["qzone"]["cookie"] == "uin=o10001; skey=test"
    assert config["qzone"]["generated_image_enabled"] is True
    assert config.saved == 1
    assert plugin.host.sync_count == 1
    assert plugin.host.save_count == 1


def test_pending_migration_does_not_override_legacy_qzone_state() -> None:
    config = _Config(
        {
            "migration": {"reuse_private_companion_data": True},
            "qzone": {"enabled": False, "life_publish_enabled": False},
        }
    )
    plugin = _migration_plugin(config)
    legacy = SimpleNamespace(
        data={},
        enable_qzone_integration=True,
        enable_qzone_life_publish=True,
        _qzone_summary=lambda _data: {"enabled": True, "available": True},
    )
    plugin._host_plugin = lambda: legacy

    status = plugin.qzone_status()

    assert status["enabled"] is True
    assert legacy.enable_qzone_integration is True
    assert legacy.enable_qzone_life_publish is True
