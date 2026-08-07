from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    LoginState,
    MediaCrawlerCheckpoint,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
    parse_media_crawler_invocation,
    parse_media_crawler_result,
)


def test_protocol_11_checkpoint_and_profile_metadata_are_json_safe() -> None:
    invocation = MediaCrawlerInvocation(
        run_id=uuid4(),
        platform=MediaCrawlerPlatform.WEIBO,
        mode=MediaCrawlerMode.SEARCH,
        source_id=uuid4(),
        keyword="AI",
        requested_limit=10,
        checkpoint=MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            page=2,
            last_external_id="known-1",
            latest_published_at=datetime(2026, 8, 7, tzinfo=UTC),
            metadata={"strategy": "page_resume_replay_window"},
        ),
        profile_context={
            "account_configured": True,
            "browser_profile_configured": True,
            "login_state": LoginState.UNKNOWN,
        },
        timeout_seconds=30,
    )

    payload = invocation.model_dump(mode="json")
    assert payload["protocol_version"] == "1.1"
    assert payload["checkpoint"]["page"] == 2
    assert payload["profile_context"]["browser_profile_configured"] is True
    assert "browser_profile_ref" in payload
    assert MEDIACRAWLER_PROTOCOL_VERSION == "1.1"


def test_legacy_10_invocation_is_explicitly_upgraded() -> None:
    raw = {
        "protocol_version": "1.0",
        "run_id": str(uuid4()),
        "platform": "weibo",
        "mode": "search",
        "source_id": str(uuid4()),
        "keyword": "AI",
        "requested_limit": 5,
        "comment_limit": 0,
        "include_comments": False,
        "include_subcomments": False,
        "checkpoint": {"page": 3, "last_external_id": "legacy-id"},
        "account_ref": "account-ref",
        "browser_profile_ref": "profile-ref",
        "timeout_seconds": 30,
    }

    invocation = parse_media_crawler_invocation(raw)
    assert invocation.protocol_version == "1.1"
    assert invocation.checkpoint is not None
    assert invocation.checkpoint.page == 3
    assert invocation.checkpoint.platform is MediaCrawlerPlatform.WEIBO
    assert invocation.profile_context.browser_profile_configured is True


def test_legacy_10_result_without_checkpoint_is_explicitly_upgraded() -> None:
    now = datetime.now(UTC).isoformat()
    raw = {
        "protocol_version": "1.0",
        "run_id": str(uuid4()),
        "platform": "weibo",
        "status": "success",
        "items": [],
        "comments": [],
        "checkpoint": None,
        "counters": {"items": 0, "comments": 0, "warnings": 0, "errors": 0},
        "warnings": [],
        "risk_events": [],
        "errors": [],
        "started_at": now,
        "finished_at": now,
    }

    result = parse_media_crawler_result(raw)
    assert result.protocol_version == "1.1"
    assert result.feature_metadata.legacy_protocol_source == "1.0"


def test_unknown_protocol_never_silently_falls_back() -> None:
    raw = {
        "protocol_version": "2.0",
        "run_id": str(uuid4()),
        "platform": "weibo",
        "mode": "search",
        "source_id": str(uuid4()),
        "keyword": "AI",
        "requested_limit": 1,
    }
    with pytest.raises(ValueError, match="unsupported MediaCrawler invocation protocol version"):
        parse_media_crawler_invocation(raw)


def test_checkpoint_rejects_sensitive_metadata_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            metadata={"credential_ref": "hidden"},
        )
    with pytest.raises(ValidationError):
        MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            latest_published_at=datetime(2026, 8, 7),
        )


def test_result_rejects_checkpoint_for_another_platform() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        MediaCrawlerResultEnvelope(
            protocol_version="1.1",
            run_id=uuid4(),
            platform=MediaCrawlerPlatform.WEIBO,
            status=MediaCrawlerResultStatus.SUCCESS,
            checkpoint=MediaCrawlerCheckpoint(
                platform=MediaCrawlerPlatform.BILIBILI,
                mode=MediaCrawlerMode.SEARCH,
                page=1,
            ),
            started_at=now,
            finished_at=now,
        )
