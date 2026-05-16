from __future__ import annotations

from omniquery.config import LlmSettings
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.llm.ollama_adapter import OllamaAdapter


def resolve_llm_adapter(settings: LlmSettings) -> LlmPort:
    """Resolve a concrete LlmPort implementation from settings.

    Currently supports `ollama`. OpenAI and Anthropic adapters are added
    in P0.2 (see IMPROVEMENTS.md).
    """
    provider = settings.provider
    if provider == "ollama":
        return OllamaAdapter(
            model=settings.model,
            base_url=settings.ollama_base_url,
            timeout=settings.timeout,
        )
    if provider == "openai":
        from omniquery.infrastructure.llm.openai_adapter import OpenAIAdapter

        if settings.openai_api_key is None:
            raise ValueError("LLM_OPENAI_API_KEY is required for provider=openai")
        return OpenAIAdapter(
            model=settings.model,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )
    if provider == "anthropic":
        from omniquery.infrastructure.llm.anthropic_adapter import AnthropicAdapter

        if settings.anthropic_api_key is None:
            raise ValueError("LLM_ANTHROPIC_API_KEY is required for provider=anthropic")
        return AnthropicAdapter(
            model=settings.model,
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.anthropic_base_url,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
