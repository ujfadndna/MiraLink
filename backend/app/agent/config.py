"""Agent 配置。"""
from __future__ import annotations

import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_provider() -> str:
    """Auto-detect the first available LLM provider from environment keys."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"  # default, will fail if no key set


def _detect_api_key(provider: str) -> Optional[str]:
    """Get the API key for the provider from environment."""
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    return os.getenv(key_map.get(provider, ""))


def _detect_base_url(provider: str) -> Optional[str]:
    """Get the base URL if not default."""
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_BASE_URL") or None
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    if provider == "openai":
        return os.getenv("OPENAI_BASE_URL") or None
    return None


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM 配置 — 默认值 None，由 env_file 或环境变量覆盖
    agent_llm_provider: str = "anthropic"
    agent_llm_model: str = "claude-haiku-4-5-20251001"
    agent_llm_temperature: float = 0.7
    agent_llm_api_key: Optional[str] = None
    agent_llm_base_url: Optional[str] = None

    def get_llm_provider(self) -> str:
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("DEEPSEEK_API_KEY"):
            return "deepseek"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return self.agent_llm_provider

    # Agent 行为
    short_memory_turns: int = 20
    enforce_identity_disclosure: bool = True


agent_settings = AgentSettings()
