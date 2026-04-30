from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingPort(ABC):
    """
    Outbound port — contract every embedding adapter must fulfil.

    An embedding adapter converts arbitrary text to a dense vector
    (list of floats) in a fixed-dimensional semantic space.
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            A dense float vector (dimension depends on the underlying model).
        """

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of text strings in a single request where possible.

        Args:
            texts: List of texts to embed.

        Returns:
            List of dense float vectors, one per input text.
        """
