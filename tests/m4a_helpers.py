from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.openai_compatible import DefaultProviderAdapterFactory
from packages.database.models import AIModelRecord, AIProviderRecord, AITaskRouteRecord


async def allow_test_host(host: str, allow_private_network: bool) -> None:
    del host, allow_private_network


def mock_factory(handler: httpx.MockTransport) -> DefaultProviderAdapterFactory:
    os.environ["M4A_TEST_KEY"] = "test-key-never-persisted"
    return DefaultProviderAdapterFactory(
        transport=handler,
        host_validator=allow_test_host,
    )


async def create_ai_stack(
    session: AsyncSession,
    *,
    task_key: str = "draft_generation",
    primary_name: str = "model-primary",
    fallback_name: str | None = None,
    capability: str = "text_generation",
    route_retry_limit: int = 0,
    provider_retry_limit: int = 0,
    embedding_version: str | None = None,
    structured_output_mode: str | None = None,
    dimensions: int | None = None,
    prices: bool = True,
) -> tuple[AIProviderRecord, AIModelRecord, AIModelRecord | None, AITaskRouteRecord]:
    provider = AIProviderRecord(
        provider_key="test-provider",
        display_name="Test Provider",
        provider_type="openai_compatible",
        base_url="https://provider.test/v1",
        credential_ref="env://M4A_TEST_KEY",
        enabled=True,
        timeout_seconds=5,
        max_concurrency=4,
        retry_limit=provider_retry_limit,
        config={},
        created_by="test",
        updated_by="test",
    )
    session.add(provider)
    await session.flush()

    config: dict[str, Any] = {}
    if embedding_version is not None:
        config["embedding_version"] = embedding_version
    if structured_output_mode is not None:
        config["structured_output_mode"] = structured_output_mode
    primary = AIModelRecord(
        provider_id=provider.id,
        model_key="primary",
        model_name=primary_name,
        capabilities=[capability],
        enabled=True,
        input_price_per_million=Decimal("1") if prices else None,
        output_price_per_million=Decimal("2") if prices else None,
        embedding_price_per_million=Decimal("0.5") if prices else None,
        pricing_version="test-pricing-v1",
        dimensions=dimensions,
        config=config,
        created_by="test",
        updated_by="test",
    )
    session.add(primary)
    await session.flush()

    fallback: AIModelRecord | None = None
    if fallback_name is not None:
        fallback = AIModelRecord(
            provider_id=provider.id,
            model_key="fallback",
            model_name=fallback_name,
            capabilities=[capability],
            enabled=True,
            input_price_per_million=Decimal("1") if prices else None,
            output_price_per_million=Decimal("2") if prices else None,
            embedding_price_per_million=Decimal("0.5") if prices else None,
            pricing_version="test-pricing-v1",
            dimensions=dimensions,
            config=config,
            created_by="test",
            updated_by="test",
        )
        session.add(fallback)
        await session.flush()

    route = AITaskRouteRecord(
        task_key=task_key,
        version=1,
        primary_model_id=primary.id,
        fallback_model_ids=[str(fallback.id)] if fallback is not None else [],
        timeout_seconds=5,
        retry_limit=route_retry_limit,
        budget_policy={"reserve_output_tokens": 16},
        config={"max_retry_delay_seconds": 1},
        enabled=True,
        is_active=True,
        created_by="test",
    )
    session.add(route)
    await session.commit()
    return provider, primary, fallback, route
