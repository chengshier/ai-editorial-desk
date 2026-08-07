from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from packages.connectors.base import BaseConnector, CollectionResult, CollectRequest, RawSignal
from packages.connectors.http import ConnectorFetchError, SafeHTTPFetcher
from packages.signals.urls import UnsafeURLError, normalize_http_url, resolve_redirect_url

MANUAL_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "text/html",
        "text/plain",
    }
)
MAX_EXTRACTED_TEXT = 200_000


class ManualImportError(ValueError):
    pass


class _PageExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.in_title = False
        self.ignored_depth = 0
        self.canonical_url: str | None = None
        self.meta_description: str | None = None
        self.og_title: str | None = None
        self.language: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        attributes = {
            name.casefold(): value
            for name, value in attrs
            if value is not None
        }
        if normalized_tag == "html":
            self.language = attributes.get("lang") or self.language
        elif normalized_tag == "title":
            self.in_title = True
        elif normalized_tag in {"script", "style", "noscript"}:
            self.ignored_depth += 1
        elif normalized_tag == "link":
            if (attributes.get("rel") or "").casefold() == "canonical":
                self.canonical_url = attributes.get("href") or self.canonical_url
        elif normalized_tag == "meta":
            name = (attributes.get("name") or "").casefold()
            property_name = (attributes.get("property") or "").casefold()
            content = attributes.get("content")
            if name == "description" and content:
                self.meta_description = content
            if property_name == "og:title" and content:
                self.og_title = content

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "title":
            self.in_title = False
        elif normalized_tag in {"script", "style", "noscript"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if not self.ignored_depth:
            self.text_parts.append(value)


def _decode_body(body: bytes, content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    encoding = match.group(1).strip('"\'') if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def extract_page(
    *,
    body: bytes,
    content_type: str,
    base_url: str,
) -> dict[str, str | None]:
    media_type = content_type.split(";", 1)[0].strip().casefold()
    text = _decode_body(body, content_type)
    if media_type == "text/plain":
        return {
            "title": None,
            "canonical_url": base_url,
            "description": None,
            "text": text[:MAX_EXTRACTED_TEXT].strip() or None,
            "language": None,
        }

    parser = _PageExtractor()
    parser.feed(text)
    canonical_url = base_url
    if parser.canonical_url:
        try:
            canonical_url = resolve_redirect_url(base_url, parser.canonical_url)
        except UnsafeURLError:
            canonical_url = base_url
    page_text = " ".join(parser.text_parts).strip()
    return {
        "title": " ".join(parser.title_parts).strip() or parser.og_title,
        "canonical_url": canonical_url,
        "description": parser.meta_description,
        "text": page_text[:MAX_EXTRACTED_TEXT] or parser.meta_description,
        "language": parser.language,
    }


class ManualURLConnector(BaseConnector):
    connector_type = "manual"

    def __init__(self, fetcher: SafeHTTPFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeHTTPFetcher()

    async def health_check(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "implemented": True,
            "validated": False,
        }

    async def collect(self, request: CollectRequest) -> CollectionResult:
        url = request.query or str(request.parameters.get("url") or "")
        if not url:
            raise ManualImportError("手工导入缺少 URL")
        original_url = normalize_http_url(url)
        user_title = _optional_text(request.parameters.get("title"))
        user_text = _optional_text(request.parameters.get("text"))
        note = _optional_text(request.parameters.get("note"))
        fetch_metadata = bool(request.parameters.get("fetch_metadata", True))

        page: dict[str, str | None] = {
            "title": None,
            "canonical_url": original_url,
            "description": None,
            "text": None,
            "language": None,
        }
        fetch_status = "not_requested"
        fetch_error_code: str | None = None
        if fetch_metadata:
            try:
                response = await self.fetcher.fetch(
                    original_url,
                    allowed_content_types=MANUAL_CONTENT_TYPES,
                    headers={
                        "Accept": "text/html, application/xhtml+xml, text/plain",
                        "User-Agent": "AI-Editorial-Desk/0.4 Manual",
                    },
                )
                page = extract_page(
                    body=response.body,
                    content_type=response.headers.get("content-type", "text/html"),
                    base_url=response.url,
                )
                fetch_status = "fetched"
            except UnsafeURLError:
                raise
            except ConnectorFetchError as exc:
                fetch_status = "failed"
                fetch_error_code = exc.code
                if not user_title and not user_text:
                    raise ManualImportError("无法抓取公开页面，且未提供可保存内容") from exc

        canonical_url = page["canonical_url"] or original_url
        title = user_title or page["title"] or page["description"]
        text = user_text or page["text"] or page["description"]
        if fetch_status == "fetched" and (user_title or user_text):
            content_origin = "partial"
        elif fetch_status == "fetched":
            content_origin = "fetched"
        else:
            content_origin = "user_provided"

        signal = RawSignal(
            platform="manual_url",
            external_id=None,
            url=original_url,
            canonical_url=canonical_url,
            title=title,
            text=text,
            language=page["language"],
            raw_payload={
                "fetch_status": fetch_status,
                "fetch_error_code": fetch_error_code,
                "content_origin": content_origin,
                "note": note,
                "meta_description": page["description"],
            },
        )
        return CollectionResult(
            signals=(signal,),
            metadata={
                "fetch_status": fetch_status,
                "content_origin": content_origin,
            },
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "MANUAL_CONTENT_TYPES",
    "ManualImportError",
    "ManualURLConnector",
    "extract_page",
]
