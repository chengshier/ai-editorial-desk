from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    DefinitionSyncError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import (
    AuditLogRepository,
    ConnectorDefinitionRepository,
    Page,
)
from packages.connectors.definitions import CONNECTOR_DEFINITIONS, ConnectorDefinitionManifest
from packages.database.models import ConnectorDefinition


@dataclass(slots=True, frozen=True)
class DefinitionSyncResult:
    created: int
    updated: int
    unchanged: int
    failed: int = 0


def _definition_state_snapshot(definition: ConnectorDefinition) -> dict[str, object]:
    return {
        "connector_type": definition.connector_type,
        "platform": definition.platform,
        "implementation_version": definition.implementation_version,
        "is_enabled": definition.is_enabled,
    }


class ConnectorDefinitionSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConnectorDefinitionRepository(session)

    async def sync(
        self,
        definitions: Iterable[ConnectorDefinitionManifest] = CONNECTOR_DEFINITIONS,
    ) -> DefinitionSyncResult:
        created = 0
        updated = 0
        unchanged = 0
        try:
            async with self.session.begin():
                for manifest in definitions:
                    self._validate_manifest(manifest)
                    current = await self.repository.get_by_key(
                        manifest.connector_type, manifest.platform
                    )
                    if current is None:
                        self.repository.add(
                            ConnectorDefinition(
                                connector_type=manifest.connector_type,
                                platform=manifest.platform,
                                display_name=manifest.display_name,
                                capabilities=manifest.capabilities,
                                config_schema=manifest.config_schema,
                                ui_schema=manifest.ui_schema,
                                implementation_version=manifest.implementation_version,
                                is_enabled=manifest.is_enabled_default,
                            )
                        )
                        created += 1
                        continue

                    changed = False
                    code_owned_fields = {
                        "display_name": manifest.display_name,
                        "capabilities": manifest.capabilities,
                        "config_schema": manifest.config_schema,
                        "ui_schema": manifest.ui_schema,
                        "implementation_version": manifest.implementation_version,
                    }
                    for field_name, value in code_owned_fields.items():
                        if getattr(current, field_name) != value:
                            setattr(current, field_name, value)
                            changed = True
                    if changed:
                        updated += 1
                    else:
                        unchanged += 1
        except Exception as exc:
            raise DefinitionSyncError("连接器定义同步失败，事务已回滚") from exc
        return DefinitionSyncResult(created=created, updated=updated, unchanged=unchanged)

    @staticmethod
    def _validate_manifest(manifest: ConnectorDefinitionManifest) -> None:
        if not manifest.connector_type.strip() or not manifest.platform.strip():
            raise ValueError("connector_type and platform cannot be empty")
        try:
            Draft202012Validator.check_schema(manifest.config_schema)
        except SchemaError as exc:
            raise ValueError(
                f"invalid config schema: {manifest.connector_type}/{manifest.platform}"
            ) from exc


class ConnectorDefinitionQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = ConnectorDefinitionRepository(session)

    async def get(self, definition_id: UUID) -> ConnectorDefinition:
        definition = await self.repository.get(definition_id)
        if definition is None:
            raise ResourceNotFoundError("连接器定义不存在")
        return definition

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_type: str | None,
        platform: str | None,
        is_enabled: bool | None,
    ) -> Page[ConnectorDefinition]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            connector_type=connector_type,
            platform=platform,
            is_enabled=is_enabled,
        )


class ConnectorDefinitionStateService:
    """Mutate only the operator-owned runtime switch on a code-owned definition."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConnectorDefinitionRepository(session)
        self.audit = AuditLogRepository(session)

    async def enable(self, *, definition_id: UUID, actor: str) -> ConnectorDefinition:
        return await self._set_enabled(definition_id=definition_id, actor=actor, enabled=True)

    async def disable(self, *, definition_id: UUID, actor: str) -> ConnectorDefinition:
        return await self._set_enabled(definition_id=definition_id, actor=actor, enabled=False)

    async def _set_enabled(
        self,
        *,
        definition_id: UUID,
        actor: str,
        enabled: bool,
    ) -> ConnectorDefinition:
        async with self.session.begin():
            definition = await self.repository.get(definition_id)
            if definition is None:
                raise ResourceNotFoundError("连接器定义不存在")
            if definition.is_enabled == enabled:
                return definition
            before = _definition_state_snapshot(definition)
            definition.is_enabled = enabled
            self.audit.add(
                entity_type="connector_definition",
                entity_id=definition.id,
                action="enable" if enabled else "disable",
                actor=actor,
                before_data=before,
                after_data=_definition_state_snapshot(definition),
            )
        return definition
