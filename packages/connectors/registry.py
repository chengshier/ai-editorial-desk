from collections.abc import Callable

from packages.connectors.base import BaseConnector

ConnectorFactory = Callable[[], BaseConnector]


class ConnectorRegistry:
    """Map stable connector types to explicit implementation factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, connector_type: str, factory: ConnectorFactory) -> None:
        normalized = connector_type.strip()
        if not normalized:
            raise ValueError("connector_type cannot be empty")
        if normalized in self._factories:
            raise ValueError(f"connector already registered: {normalized}")
        self._factories[normalized] = factory

    def has(self, connector_type: str) -> bool:
        return connector_type in self._factories

    def create(self, connector_type: str) -> BaseConnector:
        try:
            factory = self._factories[connector_type]
        except KeyError as exc:
            raise KeyError(
                f"connector implementation unavailable: {connector_type}"
            ) from exc
        return factory()

    def list_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
