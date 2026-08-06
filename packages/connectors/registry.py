from collections.abc import Callable

from packages.connectors.base import BaseConnector

ConnectorFactory = Callable[[], BaseConnector]


class ConnectorRegistry:
    """In-process registry for connector factories.

    Connector configuration lives in the database; this registry only maps a
    stable connector type to its implementation factory.
    """

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, connector_type: str, factory: ConnectorFactory) -> None:
        if not connector_type.strip():
            raise ValueError("connector_type cannot be empty")
        if connector_type in self._factories:
            raise ValueError(f"connector already registered: {connector_type}")
        self._factories[connector_type] = factory

    def create(self, connector_type: str) -> BaseConnector:
        try:
            factory = self._factories[connector_type]
        except KeyError as exc:
            raise KeyError(f"unknown connector type: {connector_type}") from exc
        return factory()

    def list_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
