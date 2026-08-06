import pytest

from packages.connectors.base import BaseConnector, CollectRequest, RawSignal
from packages.connectors.registry import ConnectorRegistry


class DummyConnector(BaseConnector):
    connector_type = "dummy"

    async def health_check(self) -> dict[str, str]:
        return {"status": "ok"}

    async def collect(self, request: CollectRequest):  # type: ignore[no-untyped-def]
        if False:
            yield RawSignal(platform="dummy", external_id="1", url="https://example.com")


def test_registry_registers_and_creates_connectors() -> None:
    registry = ConnectorRegistry()
    registry.register("dummy", DummyConnector)

    connector = registry.create("dummy")

    assert isinstance(connector, DummyConnector)
    assert registry.list_types() == ("dummy",)


def test_registry_rejects_duplicates() -> None:
    registry = ConnectorRegistry()
    registry.register("dummy", DummyConnector)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("dummy", DummyConnector)
