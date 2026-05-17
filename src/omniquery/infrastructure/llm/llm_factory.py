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
    if provider == "bedrock":
        # boto3 imported lazily inside the adapter so users without
        # the 'bedrock' extra never trip on a missing dep.
        from omniquery.infrastructure.llm.bedrock_adapter import BedrockAdapter

        return BedrockAdapter(
            model=settings.model,
            region=settings.bedrock_region,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )
    if provider == "vertex":
        # Requires both the 'vertex' extra (anthropic[vertex]) and a
        # configured project; we fail fast with a clear message
        # instead of letting the SDK raise on first call.
        if not settings.vertex_project:
            raise ValueError("LLM_VERTEX_PROJECT is required for provider=vertex")
        from omniquery.infrastructure.llm.vertex_adapter import VertexAdapter

        return VertexAdapter(
            model=settings.model,
            project=settings.vertex_project,
            region=settings.vertex_region,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
