from __future__ import annotations

from app.domain.models import ProviderConfig
from app.llm.clients.anthropic_client import AnthropicClient
from app.llm.clients.base_client import LLMClient
from app.llm.clients.deterministic_client import DeterministicLLMClient
from app.llm.clients.openai_client import OpenAIClient


class LLMProviderFactory:
    def __init__(self) -> None:
        self._deterministic = DeterministicLLMClient()

    def create(self, config: ProviderConfig) -> LLMClient:
        if config.llm.provider == "openai":
            return OpenAIClient()
        if config.llm.provider == "anthropic":
            return AnthropicClient()
        return self._deterministic
