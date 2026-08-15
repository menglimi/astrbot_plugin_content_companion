# -*- coding: utf-8 -*-
"""Standalone creative service boundary for the companion series."""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
try:
    from quart import request
except Exception:
    request = None

from .creative import CreativeMixin


PLUGIN_NAME = "astrbot_plugin_content_companion"
PLUGIN_VERSION = "0.2.2"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}/page"
MANAGED_PAGE_MESSAGE = (
    "当前能力已由“我会永远陪着你”统一管理，请前往陪伴插件的“陪伴面板”继续操作。"
)
_active_plugin: "ContentCompanionPlugin | None" = None

_CREATIVE_CONFIG_DEFAULTS = {
    "enable_creative_writing": True,
    "creative_inspiration_probability": 0.2,
    "creative_share_probability": 0.28,
    "creative_chars_per_session": 220,
    "creative_max_active_projects": 2,
    "creative_direction_prompt": "",
    "enable_creative_cover_generation": False,
    "CREATIVE_PROVIDER_ID": "",
    "CREATIVE_OUTLINE_PROVIDER_ID": "",
    "CREATIVE_REVIEW_PROVIDER_ID": "",
}
_CREATIVE_RUNTIME_ATTRIBUTES = {
    "enable_creative_writing": "enable_creative_writing",
    "creative_inspiration_probability": "creative_inspiration_probability",
    "creative_share_probability": "creative_share_probability",
    "creative_chars_per_session": "creative_chars_per_session",
    "creative_max_active_projects": "creative_max_active_projects",
    "creative_direction_prompt": "creative_direction_prompt",
    "enable_creative_cover_generation": "enable_creative_cover_generation",
    "CREATIVE_PROVIDER_ID": "creative_provider_id",
    "CREATIVE_OUTLINE_PROVIDER_ID": "creative_outline_provider_id",
    "CREATIVE_REVIEW_PROVIDER_ID": "creative_review_provider_id",
}
_QZONE_CONFIG_DEFAULTS = {
    "enabled": False,
    "cookie": "",
    "life_publish_enabled": False,
    "comment_inbox_enabled": False,
    "generated_image_enabled": False,
}
_QZONE_RUNTIME_ATTRIBUTES = {
    "enabled": "enable_qzone_integration",
    "cookie": "qzone_cookie",
    "life_publish_enabled": "enable_qzone_life_publish",
    "comment_inbox_enabled": "enable_qzone_comment_inbox",
    "generated_image_enabled": "enable_qzone_generated_image_publish",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "enabled", "开启", "是"}:
            return True
        if normalized in {"false", "0", "no", "off", "disabled", "关闭", "否", ""}:
            return False
    return default if value is None else bool(value)


def get_content_companion_api() -> Any | None:
    return getattr(_active_plugin, "extension_api", None) if _active_plugin is not None else None


class ContentCompanionExtensionAPI:
    """Stable API; the host remains the compatibility data owner for now."""

    def __init__(self, plugin: "ContentCompanionPlugin") -> None:
        self._plugin = plugin

    def _owner(self, owner: Any | None) -> Any:
        return owner if owner is not None else self._plugin.host

    def status(self) -> dict[str, Any]:
        migration_completed = bool(self._plugin.host.data.get("legacy_migration_completed"))
        value = {
            "installed": True,
            "enabled": self._plugin.enabled,
            "available": self._plugin.enabled,
            "mode": "standalone_with_legacy_readthrough",
            "data_owner": "content_companion",
            "migration": {
                "completed": migration_completed,
                "pending": self._plugin._reuse_private_companion_data() and not migration_completed,
            },
        }
        value["qzone"] = self._plugin.qzone_status()
        return value

    async def qzone_call(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._plugin.qzone_call(operation, payload or {})

    async def _call(self, owner: Any, method: str, *args: Any, **kwargs: Any) -> Any:
        implementation = getattr(CreativeMixin, method, None)
        if not callable(implementation):
            return None
        return await implementation(self._owner(owner), *args, **kwargs)

    async def advance_creative_projects(self, owner: Any) -> bool:
        await self._call(owner, "_maybe_advance_creative_projects")
        return True

    async def maybe_start_creative_project(self, owner: Any, *, idle_checked: bool = False) -> bool:
        return bool(await self._call(owner, "_maybe_start_creative_project", idle_checked=idle_checked))

    async def generate_creative_project(self, owner: Any, source: dict[str, str]) -> Any:
        return await self._call(owner, "_generate_creative_project", source)

    async def generate_creative_chunk(self, owner: Any, project: dict[str, Any], budget: int) -> str:
        return str(await self._call(owner, "_generate_creative_chunk", project, budget) or "")

    async def review_creative_chunk(self, owner: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._call(owner, "_review_creative_chunk", *args, **kwargs)

    async def apply_creative_manual_edit(self, owner: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._call(owner, "_apply_creative_manual_edit", *args, **kwargs)

    async def rebuild_creative_memory(self, owner: Any, project_id: str) -> Any:
        return await self._call(owner, "_rebuild_creative_memory_from_project", project_id)

    async def maybe_generate_creative_cover(self, owner: Any, project_id: str, *, force: bool = False) -> Any:
        return await self._call(owner, "_maybe_generate_creative_cover", project_id, force=force)

    async def standalone_advance(self) -> bool:
        if not self._plugin.enabled:
            return False
        await self._call(None, "_maybe_advance_creative_projects")
        return True

    def list_projects(self, owner: Any | None = None) -> list[dict[str, Any]]:
        host = self._owner(owner)
        return [dict(item) for item in host._creative_projects() if isinstance(item, dict)]

    def get_project(self, owner: Any | None, selector: str = "") -> dict[str, Any] | None:
        projects = self.list_projects(owner)
        selector = str(selector or "").strip()
        if selector:
            for project in projects:
                if selector in {str(project.get("id") or ""), str(project.get("title") or "")}:
                    return project
        return projects[-1] if projects else None

    async def create_project(self, owner: Any | None, source_text: str) -> dict[str, Any] | None:
        host = self._owner(owner)
        project = await host._generate_creative_project({"source": "user", "label": "用户灵感", "text": str(source_text or "")[:220]})
        if not isinstance(project, dict):
            return None
        async with host._data_lock:
            projects = host._creative_projects()
            projects.append(project)
            host.data["creative_projects"] = projects[-20:]
            host._save_data_sync()
        return dict(project)

    async def advance_now(self, owner: Any | None, selector: str = "") -> dict[str, Any] | None:
        host = self._owner(owner)
        project = self.get_project(owner, selector)
        if not project:
            return None
        project["next_advance_at"] = 0
        await host._maybe_advance_creative_projects()
        return self.get_project(owner, str(project.get("id") or ""))


class StandaloneCreativeHost(CreativeMixin):
    """Small independent host used when the content plugin runs alone."""

    def __init__(self, plugin: "ContentCompanionPlugin") -> None:
        self.plugin = plugin
        self.context = plugin.context
        self.data_dir = str(StarTools.get_data_dir(PLUGIN_NAME))
        self.data_path = Path(self.data_dir) / "creative_state.json"
        self._data_lock = asyncio.Lock()
        self._creative_cover_generation_locks: dict[str, asyncio.Lock] = {}
        self._load_data()
        self._migrate_legacy_state()
        self._sync_config()

    def _sync_config(self) -> None:
        cfg = self.plugin.config
        legacy = self._legacy_config()
        creative_cfg = cfg.get("creative") if isinstance(cfg.get("creative"), dict) else cfg
        def value(name: str, default: Any) -> Any:
            current = creative_cfg.get(name) if isinstance(creative_cfg, dict) else None
            if current not in (None, ""):
                return current
            return legacy.get(name, default)
        self.enable_creative_writing = _as_bool(value("enable_creative_writing", True), True)
        self.enable_creative_cover_generation = _as_bool(value("enable_creative_cover_generation", False), False)
        self.enable_photo_text_action = self._image_companion_api() is not None
        self.enable_photo_reference_image = False
        self.photo_generation_prompt_format = "traditional"
        self.photo_persona_reference_image_path = ""
        self.creative_inspiration_probability = float(value("creative_inspiration_probability", 0.2) or 0.2)
        self.creative_share_probability = float(value("creative_share_probability", 0.28) or 0.28)
        self.creative_max_active_projects = max(1, int(value("creative_max_active_projects", 2) or 2))
        self.creative_chars_per_session = max(120, int(value("creative_chars_per_session", 220) or 220))
        self.creative_provider_id = str(value("CREATIVE_PROVIDER_ID", "") or "")
        self.creative_outline_provider_id = str(value("CREATIVE_OUTLINE_PROVIDER_ID", "") or self.creative_provider_id)
        self.creative_review_provider_id = str(value("CREATIVE_REVIEW_PROVIDER_ID", "") or self.creative_provider_id)
        self.mai_style_provider_id = str(cfg.get("MAI_STYLE_PROVIDER_ID", "") or "")
        self.default_style = str(creative_cfg.get("default_style", "自然") or "自然")
        self.bot_name = str(creative_cfg.get("bot_name", "我会替你留住故事") or "我会替你留住故事")
        self.schedule_persona_prompt = str(creative_cfg.get("persona_prompt", "") or "")
        self.creative_direction_prompt = str(value("creative_direction_prompt", "") or "")
        self.idle_minutes = 30

    def _load_data(self) -> None:
        try:
            if self.data_path.exists():
                value = json.loads(self.data_path.read_text(encoding="utf-8"))
                self.data = value if isinstance(value, dict) else {}
            else:
                self.data = {}
        except Exception:
            self.data = {}
        if not isinstance(self.data.get("creative_projects"), list):
            self.data["creative_projects"] = []

    def _migrate_legacy_state(self) -> None:
        if self.data.get("creative_projects") or not self.plugin._reuse_private_companion_data():
            return
        source = getattr(self.plugin.context, "private_companion_data", None)
        if not isinstance(source, dict):
            try:
                legacy_path = Path(str(StarTools.get_data_dir("astrbot_plugin_private_companion"))) / "companions.json"
                source = json.loads(legacy_path.read_text(encoding="utf-8")) if legacy_path.exists() else None
            except Exception:
                source = None
        if isinstance(source, dict) and isinstance(source.get("creative_projects"), list):
            self.data["creative_projects"] = json.loads(json.dumps(source["creative_projects"], ensure_ascii=False))
            self._save_data_sync()

    def _legacy_config(self) -> dict[str, Any]:
        getter = getattr(self.plugin.context, "get_registered_star", None)
        if not callable(getter):
            return {}
        try:
            metadata = getter("astrbot_plugin_private_companion")
            instance = getattr(metadata, "star_cls", None) if metadata is not None else None
            config = getattr(instance, "config", None)
            return dict(config) if isinstance(config, dict) else {}
        except Exception:
            return {}

    def _save_data_sync(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.data_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.data_path)

    @staticmethod
    def _extract_json_payload(raw_text: str) -> Any:
        text = str(raw_text or "").strip()
        if text.startswith("```"):
            text = text.strip("`").replace("json\n", "", 1).strip()
        try:
            return json.loads(text)
        except Exception:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    return None
        return None

    def _task_provider(self, *values: Any) -> str:
        return next((str(value or "").strip() for value in values if str(value or "").strip()), "")

    async def _llm_call(self, prompt: str, max_tokens: int = 600, provider_id: str | None = None, **_: Any) -> str | None:
        kwargs: dict[str, Any] = {"prompt": prompt}
        if provider_id:
            kwargs["chat_provider_id"] = provider_id
        if max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        try:
            response = await self.context.llm_generate(**kwargs)
            return str(getattr(response, "completion_text", "") or "").strip() or None
        except Exception as exc:
            logger.warning("[ContentCompanion] 独立创作模型调用失败: %s", str(exc)[:160])
            return None

    @staticmethod
    def _get_default_persona_prompt() -> str:
        return "保持具体、克制、自然的创作语气。"

    @staticmethod
    def _get_current_plan_item(_plan: Any) -> dict[str, Any]:
        return {}

    @staticmethod
    def _is_sleepy_plan_item(_item: Any) -> bool:
        return False

    def _bot_currently_idle_for_creative_writing(self) -> bool:
        return True

    def _creative_inspiration_source(self) -> dict[str, str] | None:
        source = super()._creative_inspiration_source()
        if source:
            return source
        direction = str(self.creative_direction_prompt or "").strip()
        if direction:
            return {"source": "configured", "label": "创作方向", "text": direction[:220]}
        # Standalone mode has no companion daily-state stream to seed ideas.
        # Keep the same probabilistic behavior while providing a quiet seed.
        if not self._creative_projects() and random.random() <= 0.2:
            return {"source": "standalone", "label": "窗边灵感", "text": "一个适合慢慢展开的日常小画面"}
        return None

    def _creative_has_pending_proactive_plan(self) -> bool:
        return False

    def _friend_can_receive_proactive_reason(self, *_args: Any, **_kwargs: Any) -> bool:
        return False

    def _is_target_private_user(self, *_args: Any, **_kwargs: Any) -> bool:
        return False

    def _offer_proactive_candidate(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _maybe_schedule_creative_share(self) -> bool:
        return False

    def _defer_creative_project_advance(self, project: dict[str, Any], *, now: float, reason: str) -> int:
        project["next_advance_at"] = now + 60 * 60
        project["last_advance_error"] = str(reason or "")[:180]
        return 60

    def _mark_creative_milestone_disclosed(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def _store_creative_cover_image(self, _project_id: str, image_path: str) -> str:
        return str(image_path or "")

    @staticmethod
    def _creative_cover_file_exists(project: dict[str, Any]) -> bool:
        path = Path(str(project.get("cover_path") or ""))
        try:
            return bool(str(path) and path.exists() and path.is_file())
        except (OSError, ValueError):
            return False

    def _photo_text_available(self) -> bool:
        api = self._image_companion_api()
        if api is None:
            return False
        status = getattr(api, "capability_status", None)
        try:
            value = status(self) if callable(status) else {}
        except Exception:
            return False
        return bool(isinstance(value, dict) and value.get("available"))

    def _image_companion_api(self) -> Any | None:
        names = ("data.plugins.astrbot_plugin_image_companion.main", "astrbot_plugin_image_companion.main")
        for name in names:
            module = sys.modules.get(name)
            getter = getattr(module, "get_image_companion_api", None) if module is not None else None
            try:
                api = getter() if callable(getter) else None
            except Exception:
                api = None
            if api is not None:
                return api
        getter = getattr(self.context, "get_registered_star", None)
        if callable(getter):
            try:
                metadata = getter("astrbot_plugin_image_companion")
                instance = getattr(metadata, "star_cls", None) if metadata is not None else None
                return getattr(instance, "extension_api", None)
            except Exception:
                return None
        return None

    async def _generate_photo_image(self, **kwargs: Any) -> tuple[str, str, str]:
        api = self._image_companion_api()
        generator = getattr(api, "generate_for_companion", None) if api is not None else None
        if not callable(generator):
            return "独立创作扩展", "", "未安装或未启用生图扩展"
        try:
            response = await generator(self, dict(kwargs))
        except Exception as exc:
            return "独立生图服务", "", f"封面生成失败：{str(exc)[:120]}"
        if not isinstance(response, dict):
            return "独立生图服务", "", "生图扩展返回无效结果"
        return (
            str(response.get("backend") or "独立生图服务"),
            str(response.get("image_path") or ""),
            str(response.get("note") or ""),
        )


@register(PLUGIN_NAME, "menglimi", "我会替你留住故事：陪伴体系的独立创作与作品管理扩展。", PLUGIN_VERSION)
class ContentCompanionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        global _active_plugin
        super().__init__(context)
        self.context = context
        self.config = config
        self.enabled = _as_bool(config.get("enabled", True), True)
        self.host = StandaloneCreativeHost(self)
        self.extension_api = ContentCompanionExtensionAPI(self)
        self._migration_task: asyncio.Task | None = None
        _active_plugin = self

    async def initialize(self) -> None:
        try:
            migrated = await self._try_legacy_migration()
        except Exception as exc:
            migrated = False
            logger.warning(
                "[ContentCompanion] 旧版内容迁移暂不可用，保持兼容状态并稍后重试: %s",
                str(exc)[:160],
            )
        if not migrated:
            self._migration_task = asyncio.create_task(self._migration_loop())
        logger.info(
            "[ContentCompanion] 独立创作扩展已加载，使用独立数据与创作执行器；旧数据迁移=%s",
            "completed" if migrated else "pending",
        )
        self._task = asyncio.create_task(self._creative_loop())
        self._register_qzone_page_api()

    def _reuse_private_companion_data(self) -> bool:
        migration = self.config.get("migration")
        if isinstance(migration, dict) and "reuse_private_companion_data" in migration:
            return _as_bool(migration.get("reuse_private_companion_data"), True)
        return _as_bool(self.config.get("reuse_private_companion_data", True), True)

    @staticmethod
    def _normalized_for_default(value: Any, default: Any) -> Any:
        if isinstance(default, bool):
            return _as_bool(value, default)
        if isinstance(default, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return str(value or "").strip()

    def _migrate_config_group(
        self,
        group_name: str,
        defaults: dict[str, Any],
        runtime_attributes: dict[str, str],
        legacy_host: Any,
    ) -> bool:
        group = self.config.get(group_name)
        if not isinstance(group, dict):
            group = {}
            self.config[group_name] = group
        changed = False
        for key, default in defaults.items():
            legacy_value = getattr(legacy_host, runtime_attributes[key], None)
            if legacy_value is None:
                continue
            current = group.get(key, default)
            if self._normalized_for_default(current, default) != self._normalized_for_default(default, default):
                continue
            normalized_legacy = self._normalized_for_default(legacy_value, default)
            if self._normalized_for_default(current, default) == normalized_legacy:
                continue
            group[key] = normalized_legacy
            changed = True
        return changed

    def _migrate_legacy_projects(self, legacy_host: Any) -> bool:
        if self.host.data.get("creative_projects"):
            return False
        source = getattr(legacy_host, "data", None)
        projects = source.get("creative_projects") if isinstance(source, dict) else None
        if not isinstance(projects, list) or not projects:
            return False
        self.host.data["creative_projects"] = json.loads(
            json.dumps(projects, ensure_ascii=False)
        )
        return True

    async def _try_legacy_migration(self) -> bool:
        if self.host.data.get("legacy_migration_completed"):
            return True
        if not self._reuse_private_companion_data():
            self.host.data["legacy_migration_completed"] = True
            self.host.data["legacy_migration_mode"] = "independent"
            self.host._save_data_sync()
            return True
        legacy_host = self._host_plugin()
        if legacy_host is None:
            return False
        projects_changed = self._migrate_legacy_projects(legacy_host)
        config_changed = self._migrate_config_group(
            "creative",
            _CREATIVE_CONFIG_DEFAULTS,
            _CREATIVE_RUNTIME_ATTRIBUTES,
            legacy_host,
        )
        config_changed = self._migrate_config_group(
            "qzone",
            _QZONE_CONFIG_DEFAULTS,
            _QZONE_RUNTIME_ATTRIBUTES,
            legacy_host,
        ) or config_changed
        if config_changed:
            saver = getattr(self.config, "save_config", None)
            if callable(saver):
                try:
                    saver()
                except Exception as exc:
                    logger.warning("[ContentCompanion] 保存兼容配置失败: %s", str(exc)[:160])
        self.host._sync_config()
        self.host.data["legacy_migration_completed"] = True
        self.host.data["legacy_migration_mode"] = "imported"
        self.host.data["legacy_migration_at"] = time.time()
        self.host._save_data_sync()
        logger.info(
            "[ContentCompanion] 旧版内容迁移完成: projects=%s config=%s",
            "imported" if projects_changed else "kept",
            "imported" if config_changed else "kept",
        )
        return True

    async def _migration_loop(self) -> None:
        for _ in range(24):
            try:
                if await self._try_legacy_migration():
                    return
            except Exception as exc:
                logger.debug("[ContentCompanion] 旧版内容迁移重试失败: %s", str(exc)[:160])
            await asyncio.sleep(5)
        logger.warning("[ContentCompanion] 主插件在迁移等待窗口内未就绪，将在下次启动继续迁移")

    def _host_plugin(self) -> Any | None:
        getter = getattr(self.context, "get_registered_star", None)
        if not callable(getter):
            return None
        try:
            metadata = getter("astrbot_plugin_private_companion")
            return getattr(metadata, "star_cls", None) if metadata is not None else None
        except Exception:
            return None

    def _managed_by_private_companion(self) -> bool:
        return self._host_plugin() is not None

    def qzone_status(self) -> dict[str, Any]:
        host = self._host_plugin()
        managed = host is not None
        summary_fn = getattr(host, "_qzone_summary", None) if host is not None else None
        if not callable(summary_fn):
            return {
                "installed": True,
                "enabled": False,
                "available": False,
                "managed_by_private_companion": managed,
                "reason": "private_companion_unavailable",
            }
        try:
            self._apply_qzone_config(host)
            summary = summary_fn(getattr(host, "data", {}) or {})
            qzone_cfg = self.config.get("qzone") if isinstance(self.config.get("qzone"), dict) else None
            migration_pending = self._reuse_private_companion_data() and not self.host.data.get("legacy_migration_completed")
            enabled = (
                bool(summary.get("enabled"))
                if migration_pending
                else _as_bool(qzone_cfg.get("enabled"), False)
                if qzone_cfg is not None and "enabled" in qzone_cfg
                else bool(summary.get("enabled"))
            )
            return {
                "installed": True,
                "enabled": enabled and bool(summary.get("enabled")),
                "available": bool(summary.get("available")),
                "delegated": True,
                "managed_by_private_companion": True,
                "summary": summary,
            }
        except Exception as exc:
            return {
                "installed": True,
                "enabled": False,
                "available": False,
                "managed_by_private_companion": managed,
                "reason": str(exc)[:160],
            }

    def _apply_qzone_config(self, host: Any) -> None:
        if self._reuse_private_companion_data() and not self.host.data.get("legacy_migration_completed"):
            return
        cfg = self.config.get("qzone") if isinstance(self.config.get("qzone"), dict) else {}
        if not isinstance(cfg, dict):
            return
        mapping = {
            "enabled": "enable_qzone_integration",
            "life_publish_enabled": "enable_qzone_life_publish",
            "comment_inbox_enabled": "enable_qzone_comment_inbox",
            "generated_image_enabled": "enable_qzone_generated_image_publish",
        }
        for source, target in mapping.items():
            if source in cfg:
                setattr(host, target, _as_bool(cfg.get(source), False))
        cookie = str(cfg.get("cookie") or "").strip()
        if cookie:
            setattr(host, "qzone_cookie", cookie)

    async def qzone_call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        host = self._host_plugin()
        if host is not None:
            self._apply_qzone_config(host)
        page_api = getattr(host, "page_api", None) if host is not None else None
        handlers = {
            "status": "get_qzone_status", "feed": "get_qzone_feed", "detail": "get_qzone_detail",
            "refresh": "refresh_qzone_cookies", "publish": "publish_qzone_post", "like": "like_qzone_post",
            "comment": "comment_qzone_post", "delete": "delete_qzone_post",
        }
        handler = getattr(page_api, handlers.get(str(operation or "").strip().lower(), ""), None) if page_api else None
        if not callable(handler):
            return {"ok": False, "message": "陪伴主插件未加载或 QQ 空间操作不可用"}
        try:
            return await handler()
        except Exception as exc:
            logger.warning("[ContentCompanion] QQ 空间操作失败: %s", str(exc)[:160])
            return {"ok": False, "message": str(exc)[:160]}

    def _register_qzone_page_api(self) -> None:
        register_api = getattr(self.context, "register_web_api", None)
        if not callable(register_api):
            return
        register_api(f"{PAGE_API_PREFIX}/status", self._page_qzone_status, ["GET"], "Content Companion QQ Zone status")
        register_api(f"{PAGE_API_PREFIX}/feed", self._page_qzone_feed, ["GET"], "Content Companion QQ Zone feed")
        register_api(f"{PAGE_API_PREFIX}/projects", self._page_projects, ["GET"], "Content Companion projects")
        register_api(f"{PAGE_API_PREFIX}/action", self._page_qzone_action, ["POST"], "Content Companion QQ Zone action")

    async def _page_qzone_status(self) -> dict[str, Any]:
        return {"ok": True, "data": self.qzone_status()}

    async def _page_qzone_feed(self) -> dict[str, Any]:
        return await self.qzone_call("feed", {})

    async def _page_projects(self) -> dict[str, Any]:
        projects = self.extension_api.list_projects()
        return {"ok": True, "items": projects[-50:], "total": len(projects)}

    async def _page_qzone_action(self) -> dict[str, Any]:
        if self._managed_by_private_companion():
            return {
                "ok": False,
                "status": "managed_by_private_companion",
                "message": MANAGED_PAGE_MESSAGE,
            }
        if request is None:
            return {"ok": False, "message": "页面请求上下文不可用"}
        payload = await request.get_json(silent=True) or {}
        return await self.qzone_call(str(payload.get("action") or "status"), payload)

    async def _creative_loop(self) -> None:
        while True:
            try:
                await self.extension_api.standalone_advance()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[ContentCompanion] 独立创作推进失败: %s", str(exc)[:160])
            await asyncio.sleep(15 * 60)

    async def terminate(self) -> None:
        tasks = [getattr(self, "_task", None), getattr(self, "_migration_task", None)]
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in tasks if task is not None),
            return_exceptions=True,
        )

    @filter.command("创作")
    async def creative_command(self, event: AstrMessageEvent):
        if not self.enabled:
            yield event.plain_result("独立创作扩展当前已关闭。")
            return
        raw = str(getattr(event, "message_str", "") or "").strip()
        command_text = raw.split("创作", 1)[-1].strip() if "创作" in raw else ""
        action, _, argument = command_text.partition(" ")
        action = action.strip().lower()
        argument = argument.strip()
        if action in {"开始", "新建", "建立"}:
            if not argument:
                yield event.plain_result("请在“创作 开始”后补充一个灵感或主题。")
                return
            project = await self.extension_api.create_project(None, argument)
            yield event.plain_result(f"已建立创作项目《{project.get('title') if project else '未命名作品'}》。")
            return
        if action in {"续写", "推进", "继续"}:
            project = await self.extension_api.advance_now(None, argument)
            yield event.plain_result("已尝试推进最近的创作片段。" if project else "没有找到可推进的创作项目。")
            return
        if action in {"查看", "阅读", "读取"}:
            project = self.extension_api.get_project(None, argument)
            if not project:
                yield event.plain_result("创作书柜中还没有可读取的作品。")
                return
            chunks = project.get("draft_chunks") if isinstance(project.get("draft_chunks"), list) else []
            text = "\n\n".join(str(chunk.get("text") or "") for chunk in chunks if isinstance(chunk, dict))
            yield event.plain_result(f"《{project.get('title') or '未命名作品'}》\n{text[:6000] or '这篇作品还没有正文。'}")
            return
        if action in {"分享", "片段", "摘录"}:
            project = self.extension_api.get_project(None, argument)
            if not project:
                yield event.plain_result("创作书柜中还没有可分享的作品。")
                return
            chunks = project.get("draft_chunks") if isinstance(project.get("draft_chunks"), list) else []
            latest = next((chunk for chunk in reversed(chunks) if isinstance(chunk, dict) and str(chunk.get("text") or "").strip()), None)
            if not latest:
                yield event.plain_result("这篇作品还没有可分享的正文片段。")
                return
            yield event.plain_result(f"《{project.get('title') or '未命名作品'}》片段：\n{str(latest.get('text') or '')[:1200]}")
            return
        projects = self.extension_api.list_projects()
        if not projects:
            yield event.plain_result("创作书柜目前还是空的；启用创作推进后，Bot 会在合适的空闲时间建立作品。")
            return
        lines = ["当前创作项目："]
        for index, project in enumerate(projects[-8:], 1):
            lines.append(
                f"{index}. {project.get('title') or '未命名作品'}｜{project.get('work_type') or '作品'}｜"
                f"{project.get('current_chars', 0)}/{project.get('target_chars', 0)} 字｜{project.get('status') or 'drafting'}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(name="content_companion_view_work")
    async def content_companion_view_work(self, event: AstrMessageEvent, selector: str = "") -> str:
        project = self.extension_api.get_project(None, selector)
        if not project:
            return json.dumps({"status": "empty", "message": "创作书柜中还没有可读取的作品。"}, ensure_ascii=False)
        chunks = project.get("draft_chunks") if isinstance(project.get("draft_chunks"), list) else []
        text = "\n\n".join(str(chunk.get("text") or "") for chunk in chunks if isinstance(chunk, dict))
        return json.dumps(
            {"status": "success", "project": {"id": project.get("id"), "title": project.get("title"), "work_type": project.get("work_type"), "text": text[:6000]}},
            ensure_ascii=False,
        )
