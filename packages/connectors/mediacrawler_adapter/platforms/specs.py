from __future__ import annotations

from dataclasses import dataclass
from typing import Any

M2B_IMPLEMENTATION_VERSION = "mediacrawler-m2b-v1"


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
            "allowed_modes": list(self.allowed_modes),
        }


PLATFORM_SPECS: dict[str, MediaCrawlerPlatformSpec] = {
    "weibo": MediaCrawlerPlatformSpec(
        "weibo", "微博", True, True, True, True,
        ("search", "account", "detail", "comments"),
    ),
    "bilibili": MediaCrawlerPlatformSpec(
        "bilibili", "B站", True, True, True, True,
        ("search", "account", "detail", "comments"),
    ),
    # Vendored core has creator collection, but pinned CLI does not wire --creator_id
    # to ZHIHU_CREATOR_URL_LIST. M2-B keeps effective runtime capability disabled.
    "zhihu": MediaCrawlerPlatformSpec(
        "zhihu", "知乎", True, True, False, True,
        ("search", "detail", "comments"),
        upstream_creator=True,
    ),
    "douyin": MediaCrawlerPlatformSpec(
        "douyin", "抖音", True, True, True, True,
        ("search", "account", "detail", "comments"),
    ),
    # Pinned XHS detail/creator require xsec_token-bearing target URLs. Ordinary config
    # must not persist those credentials, so M2-B exposes search (+ attached comments)
    # only. The mapper still handles the vendored JSONL shape for fixture coverage.
    "xiaohongshu": MediaCrawlerPlatformSpec(
        "xiaohongshu", "小红书", True, False, False, True,
        ("search",),
        upstream_detail=True,
        upstream_creator=True,
    ),
    "kuaishou": MediaCrawlerPlatformSpec(
        "kuaishou", "快手", True, True, True, True,
        ("search", "account", "detail", "comments"),
    ),
    "baidu_tieba": MediaCrawlerPlatformSpec(
        "baidu_tieba", "百度贴吧", True, True, True, True,
        ("search", "account", "detail", "comments"),
    ),
}


def get_platform_spec(platform: str) -> MediaCrawlerPlatformSpec:
    try:
        return PLATFORM_SPECS[platform]
    except KeyError as exc:
        raise ValueError(f"unsupported MediaCrawler platform: {platform}") from exc


def _contains_mode(mode: str) -> dict[str, Any]:
    return {
        "properties": {
            "modes": {
                "contains": {"const": mode},
            }
        },
        "required": ["modes"],
    }


def build_config_schema(spec: MediaCrawlerPlatformSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "modes": {
            "type": "array",
            "title": "采集模式",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(spec.allowed_modes)},
            "default": ["search"] if spec.search else [spec.allowed_modes[0]],
        },
        "include_comments": {
            "type": "boolean",
            "title": "采集一级评论",
            "default": False,
        },
        "comment_limit": {
            "type": "integer",
            "title": "单内容评论上限",
            "minimum": 0,
            "maximum": 50,
            "default": 20,
        },
        "include_subcomments": {
            "type": "boolean",
            "title": "采集二级评论",
            "default": False,
        },
        "timeout_seconds": {
            "type": "integer",
            "title": "单次运行超时（秒）",
            "minimum": 30,
            "maximum": 1800,
            "default": 900,
        },
    }
    all_of: list[dict[str, Any]] = []
    if spec.search:
        properties["keyword"] = {
            "type": "string",
            "title": "关键词",
            "minLength": 1,
            "maxLength": 200,
        }
        all_of.append({"if": _contains_mode("search"), "then": {"required": ["keyword"]}})
    if spec.detail or "comments" in spec.allowed_modes:
        properties["content_ids"] = {
            "type": "array",
            "title": "内容 ID / URL",
            "minItems": 1,
            "maxItems": 100,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        }
        detail_modes = [mode for mode in ("detail", "comments") if mode in spec.allowed_modes]
        for mode in detail_modes:
            all_of.append({"if": _contains_mode(mode), "then": {"required": ["content_ids"]}})
    if spec.creator:
        properties["creator_id"] = {
            "type": "string",
            "title": "创作者 ID / URL",
            "minLength": 1,
            "maxLength": 500,
        }
        all_of.append({"if": _contains_mode("account"), "then": {"required": ["creator_id"]}})
    if not spec.comments:
        properties["include_comments"]["const"] = False
        properties["include_subcomments"]["const"] = False
        properties["comment_limit"]["maximum"] = 0
        properties["comment_limit"]["default"] = 0
    all_of.append(
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
    )
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
            "widget": "checkbox_group",
            "label": "采集模式",
            "order": 10,
            "help": "仅展示当前 pinned MediaCrawler 通过主系统安全边界可执行的模式。",
        },
        "include_comments": {
            "label": "采集一级评论",
            "order": 50,
            "help": "默认关闭；启用后仍受 CollectorRuntime 评论预算限制。",
        },
        "comment_limit": {
            "label": "单内容评论上限",
            "order": 60,
            "visible_when": {"field": "include_comments", "equals": True},
        },
        "include_subcomments": {
            "label": "采集二级评论",
            "order": 70,
            "visible_when": {"field": "include_comments", "equals": True},
            "help": "默认关闭。M2-B 不进行任何真实平台评论采集。",
        },
        "timeout_seconds": {"label": "运行超时（秒）", "order": 80},
    }
    if spec.search:
        ui["keyword"] = {
            "widget": "text",
            "label": "关键词",
            "order": 20,
            "visible_when": {"field": "modes", "contains": "search"},
        }
    if "content_ids" in build_config_schema(spec)["properties"]:
        ui["content_ids"] = {
            "widget": "tags",
            "label": "内容 ID / URL",
            "order": 30,
            "visible_when": {
                "field": "modes",
                "contains_any": ["detail", "comments"],
            },
        }
    if spec.creator:
        ui["creator_id"] = {
            "widget": "text",
            "label": "创作者 ID / URL",
            "order": 40,
            "visible_when": {"field": "modes", "contains": "account"},
        }
    return ui
