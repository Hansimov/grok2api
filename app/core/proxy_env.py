from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse, urlunparse


def translate_loopback_proxy_url(
    proxy_url: str, replacement_host: str = "host.docker.internal"
) -> str:
    parsed = urlparse(proxy_url)
    hostname = parsed.hostname or ""
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return proxy_url

    netloc = parsed.netloc.replace(hostname, replacement_host, 1)
    return urlunparse(parsed._replace(netloc=netloc))


def resolve_proxy_from_env(environ: Mapping[str, str] | None = None) -> str:
    env = environ or {}
    for key in (
        "GROK2API_HOST_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        value = str(env.get(key, "")).strip()
        if value:
            return value
    return ""


def resolve_asset_proxy_from_env(environ: Mapping[str, str] | None = None) -> str:
    env = environ or {}
    for key in (
        "GROK2API_HOST_ASSET_PROXY",
        "GROK2API_ASSET_PROXY",
    ):
        value = str(env.get(key, "")).strip()
        if value:
            return value
    return resolve_proxy_from_env(env)


def build_proxy_bootstrap(
    environ: Mapping[str, str] | None,
    *,
    current_base_proxy: str,
    current_asset_proxy: str,
) -> dict[str, str]:
    updates: dict[str, str] = {}
    base_proxy = resolve_proxy_from_env(environ)
    asset_proxy = resolve_asset_proxy_from_env(environ)

    if base_proxy and not current_base_proxy:
        updates["base_proxy_url"] = translate_loopback_proxy_url(base_proxy)
    if asset_proxy and not current_asset_proxy:
        updates["asset_proxy_url"] = translate_loopback_proxy_url(asset_proxy)
    return updates
