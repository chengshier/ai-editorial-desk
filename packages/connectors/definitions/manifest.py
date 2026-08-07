from dataclasses import dataclass
from typing import Any

from packages.connectors.mediacrawler_adapter.platforms.specs import (
    M2C_IMPLEMENTATION_VERSION,
    PLATFORM_SPECS,
    build_config_schema,
    build_ui_schema,
)


@dataclass(frozen=True, slots=True)
class ConnectorDefinitionManifest:
    connector_type: str
    platform: str
    display_name: str
    capabilities: dict[str, Any]
    config_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    implementation_version: str
    is_enabled_default: bool = True


def _object_schema(
    *,
    title: str,
    properties: dict[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


def _mediacrawler_definition(platform: str) -> ConnectorDefinitionManifest:
    spec = PLATFORM_SPECS[platform]
    return ConnectorDefinitionManifest(
        connector_type="mediacrawler",
        platform=spec.platform,
        display_name=spec.display_name,
        capabilities=spec.capabilities,
        config_schema=build_config_schema(spec),
        ui_schema=build_ui_schema(spec),
        implementation_version=M2C_IMPLEMENTATION_VERSION,
    )


CONNECTOR_DEFINITIONS: tuple[ConnectorDefinitionManifest, ...] = (
    _mediacrawler_definition("weibo"),
    _mediacrawler_definition("bilibili"),
    _mediacrawler_definition("zhihu"),
    _mediacrawler_definition("douyin"),
    _mediacrawler_definition("xiaohongshu"),
    _mediacrawler_definition("kuaishou"),
    _mediacrawler_definition("baidu_tieba"),
    ConnectorDefinitionManifest(
        connector_type="rss",
        platform="rss",
        display_name="RSS / Atom",
        capabilities={
            "registration_state": "registered",
            "feed": True,
            "requires_account": False,
            "supports_checkpoint": True,
        },
        config_schema=_object_schema(
            title="RSS 来源配置",
            required=("feed_urls",),
            properties={
                "feed_urls": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 2000,
                    },
                },
                "language": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 16,
                },
                "category": {"type": "string", "maxLength": 100},
            },
        ),
        ui_schema={"feed_urls": {"widget": "url_list"}},
        implementation_version="0.1.0",
    ),
    ConnectorDefinitionManifest(
        connector_type="reddit",
        platform="reddit",
        display_name="Reddit",
        capabilities={
            "registration_state": "registered",
            "feed": True,
            "search": True,
            "comments": True,
            "requires_account": False,
            "supports_checkpoint": True,
        },
        config_schema=_object_schema(
            title="Reddit 来源配置",
            required=("subreddits", "sort"),
            properties={
                "subreddits": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9_]+$",
                        "maxLength": 64,
                    },
                },
                "sort": {
                    "type": "string",
                    "enum": ["new", "rising", "hot", "top"],
                },
                "time_filter": {
                    "type": "string",
                    "enum": ["hour", "day", "week", "month", "year", "all"],
                },
            },
        ),
        ui_schema={
            "subreddits": {"widget": "tags"},
            "sort": {"widget": "select"},
        },
        implementation_version="0.1.0",
    ),
    ConnectorDefinitionManifest(
        connector_type="hotlist",
        platform="hotlist",
        display_name="国内公开热榜",
        capabilities={
            "registration_state": "registered",
            "hotlist": True,
            "requires_account": False,
            "supports_checkpoint": True,
        },
        config_schema=_object_schema(
            title="国内公开热榜来源配置",
            required=("sources",),
            properties={
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "enum": ["baidu_realtime"],
                    },
                    "default": ["baidu_realtime"],
                    "description": "M1 仅开放百度官方实时热搜公开 JSON 入口",
                },
                "categories": {
                    "type": "array",
                    "maxItems": 30,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                    },
                    "description": "保留后续公开热榜分类能力，M1 百度实时榜暂不使用",
                },
            },
        ),
        ui_schema={
            "sources": {
                "widget": "checkbox_group",
                "label": "公开热榜来源",
                "help": "当前仅允许无需登录的百度官方实时热搜入口",
                "order": 10,
            },
            "categories": {
                "widget": "tags",
                "label": "分类",
                "order": 20,
            },
        },
        implementation_version="0.2.0",
    ),
    ConnectorDefinitionManifest(
        connector_type="manual",
        platform="manual_url",
        display_name="手工 URL",
        capabilities={
            "registration_state": "registered",
            "manual_import": True,
            "requires_account": False,
            "supports_checkpoint": False,
        },
        config_schema=_object_schema(
            title="手工 URL 配置",
            properties={
                "allowed_domains": {
                    "type": "array",
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                    },
                },
                "default_language": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 16,
                },
            },
        ),
        ui_schema={"allowed_domains": {"widget": "tags"}},
        implementation_version="0.1.0",
    ),
)
