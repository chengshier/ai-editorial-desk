from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
import socket
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from packages.ai_gateway.credentials import CredentialResolver, EnvironmentCredentialResolver
from packages.ai_gateway.domain import (
    AIModelTarget,
    AIUsage,
    EmbeddingProviderRequest,
    EmbeddingProviderResponse,
    StructuredProviderRequest,
    StructuredProviderResponse,
    TextProviderRequest,
    TextProviderResponse,
)
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError, AIProviderError
from packages.ai_gateway.providers import AIProviderAdapter
from packages.ai_gateway.structured_output import structured_output_mode

HostValidator = Callable[[str, bool], Awaitable[None]]


async def _default_host_validator(host: str, allow_private_network: bool) -> None:
    if allow_private_network:
        return
    try:
        literal = ipaddress.ip_address(host)
        addresses = (literal,)
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                host,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise AIProviderError(
                AIErrorCode.NETWORK_ERROR,
                "Provider 主机无法解析",
                retryable=True,
            ) from exc
        addresses = tuple(ipaddress.ip_address(record[4][0]) for record in records)
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise AIProviderError(
                AIErrorCode.INVALID_REQUEST,
                "Provider base_url 指向受限网络地址；"
                "本地模型必须显式启用 private network policy",
            )


async def validate_provider_base_url(
    base_url: str,
    config: dict[str, Any],
    *,
    host_validator: HostValidator = _default_host_validator,
) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise AIProviderError(
            AIErrorCode.INVALID_REQUEST,
            "Provider base_url 仅允许 http/https",
        )
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AIProviderError(
            AIErrorCode.INVALID_REQUEST,
            "Provider base_url 格式无效或包含禁止字段",
        )
    allow_private = bool(config.get("allow_private_network", False))
    allow_http = bool(config.get("allow_insecure_http", False))
    if parsed.scheme == "http" and not allow_http:
        raise AIProviderError(
            AIErrorCode.INVALID_REQUEST,
            "HTTP Provider 必须显式启用 allow_insecure_http",
        )
    await host_validator(parsed.hostname, allow_private)
    return base_url.strip().rstrip("/")


def _usage(payload: Any) -> AIUsage:
    if not isinstance(payload, dict):
        return AIUsage()
    input_tokens = payload.get("prompt_tokens", payload.get("input_tokens"))
    output_tokens = payload.get("completion_tokens", payload.get("output_tokens"))
    total_tokens = payload.get("total_tokens")

    def number(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = int(value)
        return result if result >= 0 else None

    return AIUsage(
        input_tokens=number(input_tokens),
        output_tokens=number(output_tokens),
        total_tokens=number(total_tokens),
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


_MAX_PROVIDER_ERROR_FIELD_LENGTH = 120
_MAX_PROVIDER_ERROR_MESSAGE_LENGTH = 500
_PROVIDER_ERROR_BODY_MARKER = re.compile(
    r"(?i)(authorization|credential_ref|request\s+body|messages\s*[:=]|response_format\s*[:=])"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_NAMED_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password|"
    r"authorization|credential)"
    r"\s*(?:[:=]|is\s+)\s*[^\s,;]+"
)
_KEY_LIKE_VALUE = re.compile(r"\b(?:sk|pk|rk|ds|api)-[a-zA-Z0-9_-]{8,}\b")


def _sanitize_provider_error_value(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > limit or _PROVIDER_ERROR_BODY_MARKER.search(normalized):
        return None
    normalized = _BEARER_VALUE.sub("Bearer [REDACTED]", normalized)
    normalized = _NAMED_SECRET_VALUE.sub(r"\1=[REDACTED]", normalized)
    normalized = _KEY_LIKE_VALUE.sub("[REDACTED]", normalized)
    return normalized


def _provider_error_detail(response: httpx.Response) -> dict[str, str] | None:
    """Extract a small diagnostic from standard OpenAI-style error JSON only."""

    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    detail: dict[str, str] = {}
    for source, destination, limit in (
        ("type", "provider_error_type", _MAX_PROVIDER_ERROR_FIELD_LENGTH),
        ("code", "provider_error_code", _MAX_PROVIDER_ERROR_FIELD_LENGTH),
        ("param", "provider_error_param", _MAX_PROVIDER_ERROR_FIELD_LENGTH),
        ("message", "provider_error_message", _MAX_PROVIDER_ERROR_MESSAGE_LENGTH),
    ):
        sanitized = _sanitize_provider_error_value(error.get(source), limit=limit)
        if sanitized is not None:
            detail[destination] = sanitized
    return detail or None


def _invalid_request_error(response: httpx.Response) -> AIProviderError:
    detail = _provider_error_detail(response)
    text = json.dumps(detail, ensure_ascii=True).casefold() if detail is not None else ""
    if "context" in text and ("length" in text or "token" in text):
        return AIProviderError(
            AIErrorCode.CONTEXT_LENGTH_EXCEEDED,
            "Provider 上下文长度超限",
            provider_error_detail=detail,
        )
    return AIProviderError(
        AIErrorCode.INVALID_REQUEST,
        "Provider 拒绝了请求",
        provider_error_detail=detail,
    )


def _http_error(response: httpx.Response) -> AIProviderError:
    status = response.status_code
    if status in {401, 403}:
        return AIProviderError(AIErrorCode.AUTH_ERROR, "Provider 认证失败")
    if status == 429:
        return AIProviderError(
            AIErrorCode.RATE_LIMITED,
            "Provider 请求受限",
            retryable=True,
            retry_after_seconds=_retry_after(response),
        )
    if status in {408, 504}:
        return AIProviderError(
            AIErrorCode.TIMEOUT,
            "Provider 请求超时",
            retryable=True,
        )
    if status == 404:
        return AIProviderError(
            AIErrorCode.MODEL_NOT_FOUND,
            "Provider 模型或端点不存在",
        )
    if status in {400, 422}:
        return _invalid_request_error(response)
    if 500 <= status < 600:
        return AIProviderError(
            AIErrorCode.PROVIDER_UNAVAILABLE,
            "Provider 暂时不可用",
            retryable=True,
        )
    return AIProviderError(AIErrorCode.UNKNOWN_PROVIDER_ERROR, "Provider 返回未知错误")


class OpenAICompatibleProvider(AIProviderAdapter):
    """OpenAI-compatible adapter for configured cloud or local endpoints."""

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        host_validator: HostValidator = _default_host_validator,
    ) -> None:
        self.credential_resolver = credential_resolver or EnvironmentCredentialResolver()
        self.transport = transport
        self.host_validator = host_validator

    async def _post(
        self,
        *,
        target: AIModelTarget,
        endpoint: str,
        body: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], str | None]:
        # Missing credentials fail before DNS/network work and never fall back to a hidden key.
        credential = self.credential_resolver.resolve(target.credential_ref)
        base_url = await validate_provider_base_url(
            target.base_url,
            target.provider_config,
            host_validator=self.host_validator,
        )
        headers = {
            "Authorization": f"Bearer {credential.get_secret_value()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(endpoint, json=body)
        except httpx.TimeoutException as exc:
            raise AIProviderError(
                AIErrorCode.TIMEOUT,
                "Provider 请求超时",
                retryable=True,
            ) from exc
        except httpx.NetworkError as exc:
            raise AIProviderError(
                AIErrorCode.NETWORK_ERROR,
                "Provider 网络调用失败",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(
                AIErrorCode.UNKNOWN_PROVIDER_ERROR,
                "Provider HTTP 调用失败",
            ) from exc
        if not response.is_success:
            raise _http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider 返回非 JSON 响应",
            ) from exc
        if not isinstance(payload, dict):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider JSON 响应结构无效",
            )
        request_id = response.headers.get("x-request-id")
        if request_id is None and isinstance(payload.get("id"), str):
            request_id = payload["id"]
        return payload, request_id

    async def embed(
        self,
        *,
        target: AIModelTarget,
        request: EmbeddingProviderRequest,
        timeout_seconds: float,
    ) -> EmbeddingProviderResponse:
        payload, request_id = await self._post(
            target=target,
            endpoint="/embeddings",
            body={"model": target.model_name, "input": list(request.texts)},
            timeout_seconds=timeout_seconds,
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Embedding 响应缺少 data",
            )
        ordered = sorted(
            data,
            key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
        )
        vectors: list[tuple[float, ...]] = []
        for item in ordered:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise AIProviderError(
                    AIErrorCode.INVALID_RESPONSE,
                    "Embedding 向量结构无效",
                )
            try:
                vector = tuple(float(value) for value in item["embedding"])
            except (TypeError, ValueError) as exc:
                raise AIProviderError(
                    AIErrorCode.INVALID_RESPONSE,
                    "Embedding 向量包含无效值",
                ) from exc
            vectors.append(vector)
        return EmbeddingProviderResponse(
            vectors=tuple(vectors),
            usage=_usage(payload.get("usage")),
            provider_request_id=request_id,
        )

    async def generate_text(
        self,
        *,
        target: AIModelTarget,
        request: TextProviderRequest,
        timeout_seconds: float,
    ) -> TextProviderResponse:
        body: dict[str, Any] = {
            "model": target.model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        payload, request_id = await self._post(
            target=target,
            endpoint="/chat/completions",
            body=body,
            timeout_seconds=timeout_seconds,
        )
        return TextProviderResponse(
            text=self._message_content(payload),
            usage=_usage(payload.get("usage")),
            provider_request_id=request_id,
        )

    async def generate_structured(
        self,
        *,
        target: AIModelTarget,
        request: StructuredProviderRequest,
        timeout_seconds: float,
    ) -> StructuredProviderResponse:
        try:
            mode = structured_output_mode(target.model_config)
        except ValueError as exc:
            raise AIProviderError(
                AIErrorCode.INVALID_REQUEST,
                "AI Model structured_output_mode 配置无效",
            ) from exc
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]
        response_format: dict[str, Any]
        if mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Return only a JSON object. Do not include Markdown or code fences. "
                        "The JSON object must conform to this JSON Schema: "
                        + json.dumps(
                            request.schema,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    ),
                },
            )
        body: dict[str, Any] = {
            "model": target.model_name,
            "messages": messages,
            "response_format": response_format,
        }
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        payload, request_id = await self._post(
            target=target,
            endpoint="/chat/completions",
            body=body,
            timeout_seconds=timeout_seconds,
        )
        content = self._message_content(payload)
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                AIErrorCode.STRUCTURED_OUTPUT_INVALID,
                "Provider structured output 不是合法 JSON",
                retryable=True,
                provider_response_detail=self._structured_response_detail(
                    payload=payload,
                    provider_request_id=request_id,
                    content=content,
                ),
                provider_usage=_usage(payload.get("usage")),
                provider_request_id=request_id,
            ) from exc
        if not isinstance(structured, dict):
            raise AIProviderError(
                AIErrorCode.STRUCTURED_OUTPUT_INVALID,
                "Provider structured output 必须是 JSON object",
                retryable=True,
            )
        return StructuredProviderResponse(
            data=structured,
            usage=_usage(payload.get("usage")),
            provider_request_id=request_id,
        )

    @staticmethod
    def _structured_response_detail(
        *,
        payload: dict[str, Any],
        provider_request_id: str | None,
        content: str,
    ) -> dict[str, object]:
        detail: dict[str, object] = {
            "content_empty": not content,
            "content_length": len(content),
        }
        if provider_request_id is not None:
            detail["provider_request_id"] = provider_request_id
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        if isinstance(choice, dict) and isinstance(choice.get("finish_reason"), str):
            detail["finish_reason"] = choice["finish_reason"][:120]
        message = choice.get("message") if isinstance(choice, dict) else None
        reasoning_content = (
            message.get("reasoning_content") if isinstance(message, dict) else None
        )
        detail["reasoning_content_present"] = isinstance(reasoning_content, str)
        if isinstance(reasoning_content, str):
            detail["reasoning_content_length"] = len(reasoning_content)
        usage = _usage(payload.get("usage"))
        if usage.input_tokens is not None:
            detail["input_tokens"] = usage.input_tokens
        if usage.output_tokens is not None:
            detail["output_tokens"] = usage.output_tokens
        if usage.total_tokens is not None:
            detail["total_tokens"] = usage.total_tokens
        return detail

    @staticmethod
    def _message_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider 响应缺少 choices",
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider 响应缺少 message",
            )
        if message.get("refusal"):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider 拒绝返回内容",
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise AIProviderError(
                AIErrorCode.INVALID_RESPONSE,
                "Provider 响应 content 无效",
            )
        return content


class DefaultProviderAdapterFactory:
    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        host_validator: HostValidator = _default_host_validator,
    ) -> None:
        self.adapter = OpenAICompatibleProvider(
            credential_resolver=credential_resolver,
            transport=transport,
            host_validator=host_validator,
        )

    def build(self, provider_type: str) -> AIProviderAdapter:
        if provider_type in {"openai_compatible", "local_openai_compatible"}:
            return self.adapter
        raise AIGatewayError(
            AIErrorCode.PROVIDER_UNAVAILABLE,
            f"不支持的 Provider type: {provider_type}",
        )
