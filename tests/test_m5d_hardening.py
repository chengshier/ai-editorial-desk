from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.connection_test import AIConnectionTester
from packages.database.models import (
    AIInvocationAttemptRecord,
    AIInvocationRecord,
    AIProviderRecord,
    CollectionBudget,
    ConnectorDefinition,
    ConnectorInstance,
    PlatformAccount,
    Source,
)
from packages.database.session import get_async_sessionmaker
from packages.risk_guard.models import AccountStatus
from packages.validation import (
    CheckLevel,
    M5DPreflightService,
    ValidationCheck,
    ValidationSummary,
    verify_business_invocation,
)
from packages.validation.redaction import sanitize_validation_payload

pytestmark = pytest.mark.usefixtures("clean_database")


def _check(result: ValidationSummary, key: str) -> ValidationCheck:
    return next(item for item in result.checks if item.key == key)


async def _platform_fixture(
    session: AsyncSession,
    *,
    status: AccountStatus,
    manual_review_required: bool = False,
) -> tuple[ConnectorInstance, Source, PlatformAccount]:
    definition = ConnectorDefinition(
        connector_type="mediacrawler",
        platform="bilibili",
        display_name="Bilibili M5-D Test",
        capabilities={"search": True},
        config_schema={},
        ui_schema={},
        implementation_version="m5d-test-v1",
        is_enabled=True,
    )
    session.add(definition)
    await session.flush()
    instance = ConnectorInstance(
        definition_id=definition.id,
        name="M5-D Test Instance",
        enabled=True,
        status="configured",
        config={},
        schedule_config={},
        updated_by="m5d-test",
    )
    session.add(instance)
    await session.flush()
    source = Source(
        connector_instance_id=instance.id,
        name="M5-D Search",
        source_type="mediacrawler",
        mode="search",
        scope_key="m5d-test-keyword",
        config={"keywords": ["m5d"]},
        enabled=True,
        status="active",
        updated_by="m5d-test",
    )
    account = PlatformAccount(
        connector_instance_id=instance.id,
        platform="bilibili",
        display_name="M5-D Account",
        account_identifier="m5d-account",
        browser_profile_ref="profile://isolated-m5d",
        status=status,
        manual_review_required=manual_review_required,
        updated_by="m5d-test",
    )
    session.add_all([source, account])
    await session.flush()
    session.add(
        CollectionBudget(
            scope_type="account",
            scope_key=str(account.id),
            max_runs_per_day=3,
            max_items_per_run=1,
            max_items_per_day=3,
            max_comments_per_run=0,
            max_comments_per_day=0,
            max_concurrency=1,
            timezone="Asia/Shanghai",
            enabled=True,
            updated_by="m5d-test",
        )
    )
    await session.commit()
    return instance, source, account


def test_validation_redaction_removes_sensitive_values() -> None:
    payload = sanitize_validation_payload(
        {
            "provider_key": "production-provider",
            "authorization": "sensitive-auth-value",
            "cookie": "sensitive-cookie-value",
            "api_key": "sensitive-key-value",
            "prompt": "sensitive-prompt-value",
            "browser_profile": "C:/sensitive/profile/path",
            "nested": {"password": "sensitive-password-value"},
        }
    )
    rendered = repr(payload)
    assert "production-provider" in rendered
    for value in (
        "sensitive-auth-value",
        "sensitive-cookie-value",
        "sensitive-key-value",
        "sensitive-prompt-value",
        "sensitive/profile/path",
        "sensitive-password-value",
    ):
        assert value not in rendered


@pytest.mark.asyncio
async def test_preflight_healthy_account_passes_account_and_budget_checks(
    db_session: AsyncSession,
) -> None:
    instance, source, account = await _platform_fixture(
        db_session,
        status=AccountStatus.HEALTHY,
    )
    result = await M5DPreflightService(db_session).run(
        platform="bilibili",
        connector_instance_id=instance.id,
        source_id=source.id,
        account_id=account.id,
        requested_limit=1,
        phase="platform",
    )
    assert _check(result, "platform_account").level is CheckLevel.PASS
    assert _check(result, "collection_budget").level is CheckLevel.PASS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "manual_review"),
    [
        (AccountStatus.REVIEW_REQUIRED, True),
        (AccountStatus.RESTRICTED, True),
    ],
)
async def test_preflight_blocks_risky_accounts(
    db_session: AsyncSession,
    status: AccountStatus,
    manual_review: bool,
) -> None:
    instance, source, account = await _platform_fixture(
        db_session,
        status=status,
        manual_review_required=manual_review,
    )
    result = await M5DPreflightService(db_session).run(
        platform="bilibili",
        connector_instance_id=instance.id,
        source_id=source.id,
        account_id=account.id,
        requested_limit=1,
        phase="platform",
    )
    assert _check(result, "platform_account").level is CheckLevel.BLOCK


@pytest.mark.asyncio
async def test_preflight_reports_migration_mismatch(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, account = await _platform_fixture(
        db_session,
        status=AccountStatus.HEALTHY,
    )
    monkeypatch.setattr(
        "packages.validation.preflight.EXPECTED_MIGRATION_HEAD",
        "unexpected-head",
    )
    result = await M5DPreflightService(db_session).run(
        platform="bilibili",
        connector_instance_id=instance.id,
        source_id=source.id,
        account_id=account.id,
        requested_limit=1,
        phase="platform",
    )
    assert _check(result, "migration").level is CheckLevel.BLOCK


@pytest.mark.asyncio
async def test_fake_provider_invocation_cannot_pass_real_gate(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    invocation = AIInvocationRecord(
        task_key="editorial_scoring",
        route_version=1,
        capability="structured_output",
        status="succeeded",
        input_hash="a" * 64,
        provider_key="mock-provider",
        model_name="mock-model",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        retry_count=0,
        fallback_index=0,
        pricing_snapshot={},
        metadata_json={"fixture": True},
        started_at=now,
        finished_at=now,
    )
    db_session.add(invocation)
    await db_session.flush()
    db_session.add(
        AIInvocationAttemptRecord(
            invocation_id=invocation.id,
            attempt_no=1,
            retry_index=0,
            fallback_index=0,
            provider_key="mock-provider",
            model_name="mock-model",
            status="succeeded",
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            pricing_snapshot={},
            started_at=now,
            finished_at=now,
            metadata_json={"fixture": True},
        )
    )
    await db_session.commit()
    result = await verify_business_invocation(db_session, invocation.id)
    assert result.result is CheckLevel.BLOCK
    assert _check(result, "real_provider_identity").level is CheckLevel.BLOCK
    assert _check(result, "provider_attempt").level is CheckLevel.BLOCK


@pytest.mark.asyncio
async def test_injected_provider_factory_cannot_promote_validation_status(
    db_session: AsyncSession,
) -> None:
    provider = AIProviderRecord(
        provider_key="engineering-mock",
        display_name="Engineering Mock",
        provider_type="openai_compatible",
        base_url="https://example.invalid/v1",
        credential_ref="env://M5D_TEST_KEY",
        enabled=True,
        validation_status="NOT_TESTED",
        config={},
        created_by="m5d-test",
        updated_by="m5d-test",
    )
    db_session.add(provider)
    await db_session.commit()

    class InjectedFactory:
        def build(self, provider_type: str) -> None:
            del provider_type
            return None

    tester = AIConnectionTester(
        get_async_sessionmaker(),
        provider_factory=InjectedFactory(),  # type: ignore[arg-type]
    )
    assert tester.production_validation_eligible is False
    await tester._validation_status(provider.id, "PASSED", "m5d-test")

    await db_session.refresh(provider)
    assert provider.validation_status == "NOT_TESTED"
    assert provider.last_validated_at is None


@pytest.mark.asyncio
async def test_unvalidated_provider_blocks_e2e_provider_gate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M5D_TEST_KEY", "test-only-value")
    provider = AIProviderRecord(
        provider_key="production-compatible",
        display_name="Production Compatible",
        provider_type="openai_compatible",
        base_url="https://provider.example/v1",
        credential_ref="env://M5D_TEST_KEY",
        enabled=True,
        validation_status="NOT_TESTED",
        config={},
        created_by="m5d-test",
        updated_by="m5d-test",
    )
    db_session.add(provider)
    await db_session.commit()
    checks = await M5DPreflightService(db_session)._provider_checks(provider.id, "e2e")
    validation = next(item for item in checks if item.key == "provider_validation")
    assert validation.level is CheckLevel.BLOCK
