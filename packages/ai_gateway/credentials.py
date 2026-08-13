from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
from pydantic import SecretStr

from packages.ai_gateway.errors import AICredentialError

_ENV_REF = re.compile(r"^env://([A-Z][A-Z0-9_]{1,127})$")
_ENV_FILE_OVERRIDE = "AI_EDITORIAL_ENV_FILE"


@lru_cache(maxsize=1)
def load_provider_environment() -> Path | None:
    """Load a local .env once without overriding deployment-provided environment values.

    Production deployments may inject secrets through the OS, Docker, systemd, Kubernetes,
    or a cloud secret manager. Those values always win. Local development may instead keep
    provider secrets in the project .env file. An explicit AI_EDITORIAL_ENV_FILE path is
    supported for controlled deployments that prefer a dedicated env file.
    """

    explicit_path = os.getenv(_ENV_FILE_OVERRIDE)
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    candidates.append(Path.cwd() / ".env")
    project_root = Path(__file__).resolve().parents[2]
    project_env = project_root / ".env"
    if project_env not in candidates:
        candidates.append(project_env)

    for candidate in candidates:
        if not candidate.is_file():
            continue
        load_dotenv(dotenv_path=candidate, override=False)
        return candidate
    return None


class CredentialResolver(Protocol):
    """Resolve opaque credential references only inside trusted provider infrastructure."""

    def configured(self, credential_ref: str | None) -> bool: ...

    def resolve(self, credential_ref: str | None) -> SecretStr: ...


class EnvironmentCredentialResolver:
    """Resolve controlled environment-variable references such as env://AI_KEY.

    A local project .env is loaded lazily for developer convenience. Real process-level
    environment variables keep higher priority because dotenv loading never overrides them.
    """

    def configured(self, credential_ref: str | None) -> bool:
        load_provider_environment()
        if credential_ref is None:
            return False
        match = _ENV_REF.fullmatch(credential_ref.strip())
        if match is None:
            return False
        return bool(os.getenv(match.group(1)))

    def resolve(self, credential_ref: str | None) -> SecretStr:
        load_provider_environment()
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
