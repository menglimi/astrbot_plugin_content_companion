# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot_plugin_content_companion.main import ContentCompanionExtensionAPI, StandaloneCreativeHost


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


@pytest.mark.asyncio
async def test_extension_api_lists_and_selects_projects() -> None:
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
