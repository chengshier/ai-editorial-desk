from dataclasses import replace

import pytest
from sqlalchemy import func, select

from packages.connector_management.exceptions import DefinitionSyncError
from packages.connector_management.services import ConnectorDefinitionSyncService
from packages.connectors.definitions import CONNECTOR_DEFINITIONS
from packages.database.models import ConnectorDefinition


@pytest.mark.usefixtures("clean_database")
async def test_definition_sync_is_idempotent_and_preserves_enabled(db_session) -> None:  # type: ignore[no-untyped-def]
    service = ConnectorDefinitionSyncService(db_session)
    first = await service.sync()
    assert first.created == 11
    assert first.updated == 0

    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "weibo")
    )
    assert definition is not None
    definition.is_enabled = False
    await db_session.commit()

    second = await service.sync()
    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 11
    await db_session.refresh(definition)
    assert definition.is_enabled is False


@pytest.mark.usefixtures("clean_database")
async def test_definition_sync_updates_code_owned_version(db_session) -> None:  # type: ignore[no-untyped-def]
    service = ConnectorDefinitionSyncService(db_session)
    await service.sync()
    changed = tuple(
        replace(item, implementation_version="0.2.0")
        if item.platform == "rss"
        else item
        for item in CONNECTOR_DEFINITIONS
    )
    result = await service.sync(changed)
    assert result.updated == 1
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "rss")
    )
    assert definition is not None
    assert definition.implementation_version == "0.2.0"


@pytest.mark.usefixtures("clean_database")
async def test_definition_sync_rolls_back_as_one_transaction(db_session) -> None:  # type: ignore[no-untyped-def]
    invalid = replace(CONNECTOR_DEFINITIONS[-1], config_schema={"type": "invalid"})
    with pytest.raises(DefinitionSyncError):
        await ConnectorDefinitionSyncService(db_session).sync(
            (CONNECTOR_DEFINITIONS[0], invalid)
        )
    count = await db_session.scalar(select(func.count()).select_from(ConnectorDefinition))
    assert count == 0
