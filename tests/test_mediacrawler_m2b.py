from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.connector_management.exceptions import SchemaValidationError
from packages.connector_management.validation import validate_connector_config
from packages.connectors.definitions.manifest import CONNECTOR_DEFINITIONS
from packages.connectors.mediacrawler_adapter.platforms.base import MapperDataError
from packages.connectors.mediacrawler_adapter.platforms.registry import mediacrawler_mapper_registry
from packages.connectors.mediacrawler_adapter.platforms.specs import (
    M2B_IMPLEMENTATION_VERSION,
    PLATFORM_SPECS,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mediacrawler"
FIXTURES = {
    "weibo": ("weibo.json", "wb-1", "wbc-1"),
    "bilibili": ("bilibili.json", "BV1fixture", "bc-1"),
    "zhihu": ("zhihu.json", "zh-1", "zhc-1"),
    "douyin": ("douyin.json", "dy-1", "dyc-1"),
    "xiaohongshu": ("xiaohongshu.json", "xhs-1", "xhsc-1"),
    "kuaishou": ("kuaishou.json", "ks-1", "ksc-1"),
    "baidu_tieba": ("tieba.json", "tb-1", "tbc-1"),
}
MEDIA_PLATFORMS = {"bilibili", "douyin", "xiaohongshu", "kuaishou"}


def _fixture(platform: str) -> dict[str, object]:
    filename = FIXTURES[platform][0]
    return json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("platform", FIXTURES)
def test_platform_mapper_normalizes_real_vendored_shape(platform: str) -> None:
    fixture = _fixture(platform)
    mapper = mediacrawler_mapper_registry.get(platform)
    signal = mapper.map_item(fixture["item"])  # type: ignore[arg-type]
    expected_id = FIXTURES[platform][1]
    assert signal.platform == platform
    assert signal.external_id == expected_id
    assert signal.url.startswith("https://")
    assert signal.published_at is not None
    assert signal.published_at.utcoffset() is not None
    assert signal.author_id
    assert signal.author_name
    assert all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in signal.metrics.values())
    if platform in MEDIA_PLATFORMS:
        assert signal.media
    raw = json.dumps(signal.raw_payload, ensure_ascii=False)
    for marker in (
        "cookie-secret", "token-secret", "Bearer secret", "api-secret",
        "session-secret", "password-secret", "fixture-value-token",
        "fixture-value-auth", "fixture-value-api", "fixture-value-session",
        "fixture-value-password", "fixture-value-xsec",
    ):
        assert marker not in raw
    media = json.dumps(signal.media, ensure_ascii=False)
    assert "xsec_token" not in signal.url.casefold()
    assert "xsec_token" not in media.casefold()
    if platform == "weibo":
        assert signal.title is None
        assert signal.text == "微博 fixture 正文"
        assert signal.metrics["like_count"] == 12000
    if platform == "kuaishou":
        assert signal.metrics["view_count"] == 12000


@pytest.mark.parametrize("platform", FIXTURES)
def test_platform_mapper_optional_malformed_and_comment(platform: str) -> None:
    fixture = _fixture(platform)
    mapper = mediacrawler_mapper_registry.get(platform)
    optional = mapper.map_item(fixture["optional_item"])  # type: ignore[arg-type]
    assert optional.external_id
    with pytest.raises(MapperDataError):
        mapper.map_item(fixture["malformed_item"])  # type: ignore[arg-type]
    comment = mapper.map_comment(fixture["comment"])  # type: ignore[arg-type]
    assert comment.platform == platform
    assert comment.external_comment_id == FIXTURES[platform][2]
    assert comment.content_external_id == FIXTURES[platform][1]
    assert comment.text
    assert comment.published_at is not None
    assert comment.published_at.utcoffset() is not None
    raw = json.dumps(comment.raw_payload, ensure_ascii=False)
    assert "fixture-value" not in raw
    assert "comment-cookie-secret" not in raw
    assert "comment-token-secret" not in raw


def test_mapper_registry_and_definition_capabilities_are_one_to_one() -> None:
    assert mediacrawler_mapper_registry.platforms() == frozenset(PLATFORM_SPECS)
    definitions = {
        item.platform: item
        for item in CONNECTOR_DEFINITIONS
        if item.connector_type == "mediacrawler"
    }
    assert set(definitions) == set(PLATFORM_SPECS)
    for platform, spec in PLATFORM_SPECS.items():
        definition = definitions[platform]
        assert definition.implementation_version == M2B_IMPLEMENTATION_VERSION
        assert definition.capabilities == spec.capabilities
        assert definition.capabilities["homefeed"] is False
        assert definition.capabilities["hotlist"] is False
        mode_enum = definition.config_schema["properties"]["modes"]["items"]["enum"]
        assert mode_enum == list(spec.allowed_modes)
        valid = {
            "modes": ["search"],
            "keyword": "AI 编辑部",
            "include_comments": False,
            "comment_limit": 20,
            "include_subcomments": False,
            "timeout_seconds": 900,
        }
        validate_connector_config(definition.config_schema, valid)
        with pytest.raises(SchemaValidationError):
            validate_connector_config(definition.config_schema, {**valid, "modes": ["homefeed"]})


def test_effective_capabilities_keep_known_pinned_source_gaps_disabled() -> None:
    assert PLATFORM_SPECS["zhihu"].upstream_creator is True
    assert PLATFORM_SPECS["zhihu"].creator is False
    assert "account" not in PLATFORM_SPECS["zhihu"].allowed_modes
    assert PLATFORM_SPECS["xiaohongshu"].upstream_detail is True
    assert PLATFORM_SPECS["xiaohongshu"].detail is False
    assert PLATFORM_SPECS["xiaohongshu"].creator is False
    assert PLATFORM_SPECS["xiaohongshu"].allowed_modes == ("search",)
