from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from packages.connectors.mediacrawler_adapter.protocol import MediaCrawlerPlatform


class SignatureProviderError(RuntimeError):
    """Controlled provider failure; never a signal to bypass platform protections."""


@dataclass(slots=True, frozen=True)
class SignatureRequestContext:
    platform: MediaCrawlerPlatform
    run_id: UUID


@dataclass(slots=True, frozen=True)
class SignatureRuntimePlan:
    provider_id: str
    upstream_signer: str


class SignatureProvider(Protocol):
    provider_id: str

    def prepare_runtime(self, context: SignatureRequestContext) -> SignatureRuntimePlan: ...


_UPSTREAM_SIGNERS = {
    MediaCrawlerPlatform.WEIBO: "vendor-default/no-explicit-signer",
    MediaCrawlerPlatform.BILIBILI: "vendor-default/BilibiliSign",
    MediaCrawlerPlatform.ZHIHU: "vendor-default/help.sign",
    MediaCrawlerPlatform.DOUYIN: "vendor-default/get_a_bogus",
    MediaCrawlerPlatform.XIAOHONGSHU: "vendor-default/sign_with_xhshow",
    MediaCrawlerPlatform.KUAISHOU: "vendor-default/get_ks_sign_from_playwright",
    MediaCrawlerPlatform.BAIDU_TIEBA: "vendor-default/_sign_pc_params",
}


class DefaultSignatureProvider:
    """Delegate signing to the pinned vendored implementation without adding algorithms."""

    provider_id = "vendor-default"

    def prepare_runtime(self, context: SignatureRequestContext) -> SignatureRuntimePlan:
        try:
            signer = _UPSTREAM_SIGNERS[context.platform]
        except KeyError as exc:
            raise SignatureProviderError(
                f"no controlled signature provider for {context.platform.value}"
            ) from exc
        return SignatureRuntimePlan(
            provider_id=self.provider_id,
            upstream_signer=signer,
        )


class SignatureProviderRegistry:
    """Code-owned registry. There is intentionally no dynamic import/config path."""

    def __init__(self) -> None:
        self._providers: dict[MediaCrawlerPlatform, SignatureProvider] = {}

    def register(
        self,
        platform: MediaCrawlerPlatform,
        provider: SignatureProvider,
    ) -> None:
        if platform in self._providers:
            raise ValueError(
                f"signature provider already registered: {platform.value}"
            )
        self._providers[platform] = provider

    def get(self, platform: MediaCrawlerPlatform | str) -> SignatureProvider:
        try:
            normalized = MediaCrawlerPlatform(platform)
        except ValueError as exc:
            raise SignatureProviderError(
                "unsupported platform for controlled signature provider"
            ) from exc
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise SignatureProviderError(
                f"no controlled signature provider for {normalized.value}"
            ) from exc


def build_signature_provider_registry() -> SignatureProviderRegistry:
    registry = SignatureProviderRegistry()
    for platform in MediaCrawlerPlatform:
        registry.register(platform, DefaultSignatureProvider())
    return registry


signature_provider_registry = build_signature_provider_registry()
