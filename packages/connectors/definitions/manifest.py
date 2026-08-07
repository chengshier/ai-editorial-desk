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
                    },
                },
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top", "rising"],
                },
                "include_comments": {"type": "boolean", "default": False},
                "comment_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 50,
                    "default": 0,
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
        platform="baidu_realtime",
        display_name="百度实时热搜",
        capabilities={
            "registration_state": "registered",
            "hotlist": True,
            "requires_account": False,
            "supports_checkpoint": False,
        },
        config_schema=_object_schema(
            title="百度实时热搜配置",
            properties={
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                }
            },
        ),
        ui_schema={"limit": {"widget": "number"}},
        implementation_version="0.1.0",
    ),
    ConnectorDefinitionManifest(
        connector_type="manual",
        platform="web",
        display_name="手工 URL 导入",
        capabilities={
            "registration_state": "registered",
            "detail": True,
            "requires_account": False,
            "supports_checkpoint": False,
        },
        config_schema=_object_schema(
            title="手工 URL 导入配置",
            properties={},
        ),
        ui_schema={},
        implementation_version="0.1.0",
    ),
)
