import hmac

from fastapi import Header

from packages.common.config import get_settings
from packages.connector_management.exceptions import ActorRequiredError, AuthorizationError


async def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Protect internal management APIs with constant-time token comparison."""

    expected = get_settings().admin_token_value
    provided = x_admin_token or ""
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise AuthorizationError("管理员凭据无效")


async def require_actor_id(
    x_actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
) -> str:
    """Require an auditable operator identifier for all mutations."""

    actor = (x_actor_id or "").strip()
    if not actor:
        raise ActorRequiredError("修改操作必须提供 X-Actor-ID")
    if len(actor) > 255:
        raise ActorRequiredError("X-Actor-ID 长度不能超过 255")
    return actor
