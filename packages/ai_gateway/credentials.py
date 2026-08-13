from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values
from pydantic import SecretStr

from packages.ai_gateway.errors import AICredentialError

_ENV_REF = re.compile(r"^env://([A-Z][A-Z0-9_]{1,127})$")
_ENV_FILE_OVERRIDE = "AI_EDITORIAL_ENV_FILE"


@lru_cache(maxsize=1)
def load_provider_environment() -> tuple[Path | None, dict[str, str]]:
    """Read local provider secrets without exporting them into the process environment.

    Real process-level environment variables remain the highest-priority source for Docker,
    systemd, Kubernetes and cloud secret injection. Local development may use the project
    .env file as a fallback. An explicit AI_EDITORIAL_ENV_FILE path is also supported.
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
        parsed = dotenv_values(candidate)
        values = {
            key: value
            for key, value in parsed.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        return candidate, values
    return None, {}


def _credential_value(name: str) -> str | None:
    process_value = os.getenv(name)
    if process_value:
        return process_value
    _, file_values = load_provider_environment()
    return file_values.get(name)


class CredentialResolver(Protocol):
    """Resolve opaque credential references only inside trusted provider infrastructure."""

    def configured(self, credential_ref: str | None) -> bool: ...

    def resolve(self, credential_ref: str | None) -> SecretStr: ...


class EnvironmentCredentialResolver:
    """Resolve controlled environment-variable references such as env://AI_KEY.

    Cloud / OS environment values take priority. A local project .env is used only as a
    private fallback and is never copied into os.environ, so unrelated child processes do
    not receive provider secrets merely because the application read the local .env file.
    """

    def configured(self, credential_ref: str | None) -> bool:
        if credential_ref is None:
            return False
        match = _ENV_REF.fullmatch(credential_ref.strip())
        if match is None:
            return False
        return bool(_credential_value(match.group(1)))

    def resolve(self, credential_ref: str | None) -> SecretStr:
        if credential_ref is None:
            raise AICredentialError()
        match = _ENV_REF.fullmatch(credential_ref.strip())
        if match is None:
            raise AICredentialError("仅支持受控 env://NAME credential reference")
        value = _credential_value(match.group(1))
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
