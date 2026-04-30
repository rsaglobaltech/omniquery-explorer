from __future__ import annotations

import httpx

from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort


class OllamaEmbeddingAdapter(EmbeddingPort):
    """
    Driven adapter that calls the Ollama `/api/embed` endpoint to obtain
    text embeddings.

    Ollama REST API (v0.2+):
        POST http://localhost:11434/api/embed
        Body: { model, input: str | list[str] }
        Response: { embeddings: list[list[float]] }

    Args:
        model:    Embedding model name (default: "nomic-embed-text").
        base_url: Ollama server base URL (default: "http://localhost:11434").
        timeout:  HTTP timeout in seconds (default: 60).
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # EmbeddingPort implementation
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        vectors = await self._call([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._call(texts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call(self, inputs: list[str]) -> list[list[float]]:
        payload = {"model": self._model, "input": inputs}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/embed", json=payload
            )
            response.raise_for_status()

        data = response.json()
        try:
            return data["embeddings"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected Ollama embed response: {data}"
            ) from exc
