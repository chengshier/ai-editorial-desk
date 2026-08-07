import asyncio
import json
from pathlib import Path
from typing import Any

from packages.common.config import get_settings
from packages.connectors.base import (
    BaseConnector,
    CollectionResult,
    CollectRequest,
    RawSignal,
)


class MediaCrawlerAdapterError(RuntimeError):
    """Raised when the MediaCrawler subprocess cannot be executed safely."""


class MediaCrawlerAdapter(BaseConnector):
    """Run MediaCrawler as an isolated subprocess and map JSONL to RawSignal.

    The command/output contract is intentionally isolated here. MediaCrawler
    must not leak its internal models or database schema into the main system.
    """

    connector_type = "mediacrawler"

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.settings = get_settings()

    def _home(self) -> Path:
        return Path(self.settings.mediacrawler_home).expanduser().resolve()

    async def health_check(self) -> dict[str, Any]:
        home = self._home()
        entrypoint = home / "main.py"
        return {
            "status": "ok" if entrypoint.is_file() else "not_installed",
            "platform": self.platform,
            "home": str(home),
            "entrypoint": str(entrypoint),
        }

    async def collect(self, request: CollectRequest) -> CollectionResult:
        home = self._home()
        entrypoint = home / "main.py"
        if not entrypoint.is_file():
            raise MediaCrawlerAdapterError(
                "MediaCrawler is not installed at the configured path. "
                "See third_party/README.md."
            )

        command = self._build_command(entrypoint, request)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(home),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.settings.mediacrawler_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise MediaCrawlerAdapterError("MediaCrawler task timed out") from exc

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")[-4000:]
            raise MediaCrawlerAdapterError(
                f"MediaCrawler exited with code {process.returncode}: {error_text}"
            )

        signals: list[RawSignal] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            signals.append(self._map_payload(payload))
        return CollectionResult(signals=tuple(signals))

    def _build_command(self, entrypoint: Path, request: CollectRequest) -> list[str]:
        command = [
            self.settings.mediacrawler_python,
            str(entrypoint),
            "--platform",
            self.platform,
            "--type",
            request.mode,
            "--save_data_option",
            "jsonl",
        ]
        if request.query:
            command.extend(["--keywords", request.query])
        if request.target_ids:
            command.extend(["--specified_id", ",".join(request.target_ids)])
        return command

    def _map_payload(self, payload: dict[str, Any]) -> RawSignal:
        external_id = str(
            payload.get("external_id")
            or payload.get("note_id")
            or payload.get("aweme_id")
            or payload.get("video_id")
            or payload.get("id")
            or ""
        )
        url = str(
            payload.get("url")
            or payload.get("note_url")
            or payload.get("aweme_url")
            or ""
        )
        if not external_id or not url:
            raise MediaCrawlerAdapterError("MediaCrawler payload lacks external_id or url")

        return RawSignal(
            platform=self.platform,
            external_id=external_id,
            url=url,
            title=payload.get("title"),
            text=payload.get("desc") or payload.get("content") or payload.get("text"),
            author_id=payload.get("user_id") or payload.get("author_id"),
            author_name=payload.get("nickname") or payload.get("author_name"),
            metrics={},
            media=[],
            raw_payload=payload,
        )
