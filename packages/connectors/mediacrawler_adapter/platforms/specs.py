from __future__ import annotations

from dataclasses import dataclass
from typing import Any

M2C_IMPLEMENTATION_VERSION = "mediacrawler-m2c-v1"


@dataclass(frozen=True, slots=True)
class MediaCrawlerPlatformSpec:
    platform: str
    display_name: str
    search: bool
    detail: bool
    creator: bool
    comments: bool
    allowed_modes: tuple[str, ...]
    upstream_detail: bool = True
    upstream_creator: bool = True

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "registration_state": "registered",
            "search": self.search,
            "detail": self.detail,
            "creator": self.creator,
            "account": self.creator,
            "comments": self.comments,
            "homefeed": False,
            "hotlist": False,
            "requires_account": True,
            "supports_checkpoint": True,
            "incremental_search": self.search,
            "incremental_detail": False,
            "incremental_creator": False,
            "allowed_modes": list(self.allowed_modes),
        }


PLATFORM_SPECS: dict[str, MediaCrawlerPlatformSpec] = {
    "weibo": MediaCrawlerPlatformSpec(
        platform="weibo", display_name="微博", search=True, detail=True,
        creator=True, comments=True,
        allowed_modes=("search", "account", "detail", "comments"),
    ),
    "bilibili": MediaCrawlerPlatformSpec(
        platform="bilibili", display_name="B站", search=True, detail=True,
        creator=True, comments=True,
        allowed_modes=("search", "account", "detail", "comments"),
    ),
    "zhihu": MediaCrawlerPlatformSpec(
        platform="zhihu", display_name="知乎", search=True, detail=True,
        creator=False, comments=True,
        allowed_modes=("search", "detail", "comments"), upstream_creator=True,
    ),
    "douyin": MediaCrawlerPlatformSpec(
        platform="douyin", display_name="抖音", search=True, detail=True,
        creator=True, comments=True,
        allowed_modes=("search", "account", "detail", "comments"),
    ),
    "xiaohongshu": MediaCrawlerPlatformSpec(
        platform="xiaohongshu", display_name="小红书", search=True, detail=False,
        creator=False, comments=True, allowed_modes=("search",),
        upstream_detail=True, upstream_creator=True,
    ),
    "kuaishou": MediaCrawlerPlatformSpec(
        platform="kuaishou", display_name="快手", search=True, detail=True,
        creator=True, comments=True,
        allowed_modes=("search", "account", "detail", "comments"),
    ),
    "baidu_tieba": MediaCrawlerPlatformSpec(
        platform="baidu_tieba", display_name="百度贴吧", search=True, detail=True,
        creator=True, comments=True,
        allowed_modes=("search", "account", "detail", "comments"),
    ),
}


def get_platform_spec(platform: str) -> MediaCrawlerPlatformSpec:
    try:
        return PLATFORM_SPECS[platform]
    except KeyError as exc:
        raise ValueError(f"unsupported MediaCrawler platform: {platform}") from exc


def build_config_schema(spec: MediaCrawlerPlatformSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "modes": {
            "type": "array", "title": "采集模式", "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(spec.allowed_modes)},
            "default": ["search"] if spec.search else [spec.allowed_modes[0]],
        },
        "include_comments": {"type": "boolean", "title": "采集一级评论", "default": False},
        "comment_limit": {
            "type": "integer", "title": "单内容评论上限", "minimum": 0,
            "maximum": 50, "default": 20,
        },
        "include_subcomments": {"type": "boolean", "title": "采集二级评论", "default": False},
        "timeout_seconds": {
            "type": "integer", "title": "单次运行超时（秒）", "minimum": 30,
            "maximum": 1800, "default": 900,
        },
    }
    # keyword/content_ids/creator_id are retained only for backward compatibility with
    # previously persisted instance configs. New collection targets belong to Source.
    if spec.search:
        properties["keyword"] = {
            "type": "string", "title": "旧版关键词", "minLength": 1, "maxLength": 200,
            "description": "兼容旧实例配置；新建搜索目标请在信源中配置。",
        }
    if spec.detail or "comments" in spec.allowed_modes:
        properties["content_ids"] = {
            "type": "array", "title": "旧版内容 ID / URL", "minItems": 1,
            "maxItems": 100, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
            "description": "兼容旧实例配置；新建内容目标请在信源中配置。",
        }
    if spec.creator:
        properties["creator_id"] = {
            "type": "string", "title": "旧版创作者 ID / URL", "minLength": 1, "maxLength": 500,
            "description": "兼容旧实例配置；新建创作者目标请在信源中配置。",
        }
    if not spec.comments:
        properties["include_comments"]["const"] = False
        properties["include_subcomments"]["const"] = False
        properties["comment_limit"]["maximum"] = 0
        properties["comment_limit"]["default"] = 0
    all_of: list[dict[str, Any]] = [
        {
            "if": {
                "properties": {"include_subcomments": {"const": True}},
                "required": ["include_subcomments"],
            },
            "then": {
                "properties": {"include_comments": {"const": True}},
                "required": ["include_comments"],
            },
        }
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{spec.display_name} MediaCrawler 配置",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": ["modes"],
        "allOf": all_of,
    }


def build_ui_schema(spec: MediaCrawlerPlatformSpec) -> dict[str, Any]:
    ui: dict[str, Any] = {
        "modes": {
            "widget": "checkbox_group", "label": "允许的采集模式", "order": 10,
            "help": (
                "这里只控制该实例允许执行哪些模式。"
                "搜索关键词、内容 ID、创作者等具体采集目标在“信源”页面配置。"
            ),
        },
        "include_comments": {
            "label": "默认采集一级评论", "order": 50,
            "help": (
                "实例级默认值；信源可在后续扩展中覆盖，"
                "最终仍受 CollectorRuntime 评论预算限制。"
            ),
        },
        "comment_limit": {
            "label": "单内容评论上限", "order": 60,
            "visible_when": {"field": "include_comments", "equals": True},
        },
        "include_subcomments": {
            "label": "默认采集二级评论", "order": 70,
            "visible_when": {"field": "include_comments", "equals": True},
            "help": "默认关闭；仍遵守既有风险与预算边界。",
        },
        "timeout_seconds": {"label": "运行超时（秒）", "order": 80},
    }
    if spec.search:
        ui["keyword"] = {"widget": "hidden", "order": 20}
    if "content_ids" in build_config_schema(spec)["properties"]:
        ui["content_ids"] = {"widget": "hidden", "order": 30}
    if spec.creator:
        ui["creator_id"] = {"widget": "hidden", "order": 40}
    return ui