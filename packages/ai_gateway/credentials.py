from __future__ import annotations

import os
import re
from typing import Protocol

from pydantic import SecretStr

from packages.ai_gateway.errors import AICredentialError

_ENV_REF = re.compile(r"^env://([A-Z][A-Z0-9_]{1,127})$")


class CredentialResolver(Protocol):
    """Resolve opaque credential references only inside trusted provider infrastructure."""

    def configured(self, credential_ref: str | None) -> bool: ...

    def resolve(self, credential_ref: str | None) -> SecretStr: ...


class EnvironmentCredentialResolver:
    """M4-A resolver for controlled environment-variable references such as env://AI_KEY."""

    def configured(self, credential_ref: str | None) -> bool:
        if credential_ref is None:
            return False
        match = _ENV_REF.fullmatch(credential_ref.strip())
        if match is None:
            return False
        return bool(os.getenv(match.group(1)))

    def resolve(self, credential_ref: str | None) -> SecretStr:
        if credential_ref is None:
            raise AICredentialError()
        match = _ENV_REF.fullmatch(credential_ref.strip())
        if match is None:
            raise AICredentialError("仅支持受控 env://NAME credential reference")
        value = os.getenv(match.group(1))
        if not value:
            raise AICredentialError()
        return SecretStr(value)


def credential_ref_mask(credential_ref: str | None) -> str | None:
    """Expose only the opaque backend kind, never the referenced secret name or value."""

    if credential_ref is None:
        return None
    if credential_ref.startswith("env://"):
        return "env://***"
    return "opaque://***"
