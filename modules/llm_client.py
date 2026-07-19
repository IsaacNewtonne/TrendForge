"""Shared LLM client with credential and local-provider failover."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import openai
from dotenv import load_dotenv
from loguru import logger
from modules.network_security import configure_system_trust_store


load_dotenv()
configure_system_trust_store()


@dataclass(frozen=True)
class LLMTarget:
    label: str
    base_url: str
    api_key: str
    model: Optional[str] = None


class _FailoverCompletions:
    def __init__(self, targets: list[LLMTarget], timeout: Optional[float] = None):
        self.targets = targets
        self.timeout = timeout

    def create(self, **kwargs: Any) -> Any:
        failures: list[str] = []
        for index, target in enumerate(self.targets):
            request = dict(kwargs)
            if target.model:
                request["model"] = target.model
            try:
                client = openai.OpenAI(
                    base_url=target.base_url,
                    api_key=target.api_key,
                    timeout=self.timeout,
                )
                if index:
                    logger.warning(f"LLM failover activated: trying {target.label}")
                response = client.chat.completions.create(**request)
                if index:
                    logger.info(f"LLM failover succeeded with {target.label}")
                return response
            except Exception as exc:
                if not provider_failure(exc):
                    raise
                failures.append(f"{target.label}: {safe_error(exc)}")
                logger.warning(f"LLM provider unavailable ({target.label}): {safe_error(exc)}")

        raise RuntimeError("All configured LLM providers failed: " + " | ".join(failures))


class _FailoverChat:
    def __init__(self, targets: list[LLMTarget], timeout: Optional[float] = None):
        self.completions = _FailoverCompletions(targets, timeout)


class FailoverLLMClient:
    """Small OpenAI-client-compatible surface used by TrendForge."""

    def __init__(self, targets: list[LLMTarget], timeout: Optional[float] = None):
        self.chat = _FailoverChat(targets, timeout)


def create_llm_client(cfg: dict, timeout: Optional[float] = None) -> FailoverLLMClient:
    """Create Zen-primary, Zen-secondary, then local Ollama failover chain."""
    base_url = cfg.get("base_url", "https://opencode.ai/zen/v1")
    targets: list[LLMTarget] = []
    seen_keys: set[str] = set()
    for label, env_name in (
        ("OpenCode Zen primary", "OPENCODE_ZEN_API_KEY"),
        ("OpenCode Zen secondary", "OPENCODE_ZEN_API_KEY_SECONDARY"),
    ):
        key = str(os.getenv(env_name, "")).strip()
        if key and key not in seen_keys:
            targets.append(LLMTarget(label, base_url, key))
            seen_keys.add(key)

    configured_key = str(cfg.get("api_key", "")).strip()
    if not targets and configured_key:
        targets.append(LLMTarget("configured remote provider", base_url, configured_key))

    fallback = cfg.get("ollama_fallback", {}) or {}
    if fallback.get("enabled", True):
        targets.append(
            LLMTarget(
                "local Ollama fallback",
                fallback.get("base_url", "http://localhost:11434/v1"),
                fallback.get("api_key", "ollama"),
                fallback.get("model", "qwen3.5:4b"),
            )
        )
    if not targets:
        raise RuntimeError("No LLM provider is configured.")
    return FailoverLLMClient(targets, timeout)


def provider_failure(exc: Exception) -> bool:
    """Return true only for failures where trying another provider can help."""
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError, openai.AuthenticationError, openai.RateLimitError)):
        return True
    status = getattr(exc, "status_code", None)
    return status in {401, 402, 403, 408, 409, 429} or (isinstance(status, int) and status >= 500)


def safe_error(exc: Exception) -> str:
    """Return bounded diagnostics without headers, requests, or credentials."""
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    return f"{name} (HTTP {status})" if status else name
