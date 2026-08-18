"""Sentence-Transformers embedding adapter.

Requires the ml dependency group: uv sync --group ml
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence


class SentenceTransformerEmbedder:
    """EmbeddingPort backed by a local sentence-transformers model.

    Model weights are loaded once at construction and held for the worker's
    lifetime. Encoding is synchronous, so each call is offloaded to the
    default thread executor to avoid blocking the event loop.
    """

    def __init__(self, *, model_id: str, device: str, batch_size: int) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install the ml dependency group: uv sync --group ml"
            ) from exc
        self._model = SentenceTransformer(model_id, device=device)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        """What the model actually produces, asked of the model rather than configured.

        The width is also declared in settings and reserved in the vector column, and the
        point of reading it here is to notice when they disagree. Sentence-Transformers
        renamed this accessor in 5.6 and the old name still answers, with a warning on
        every call — which in a worker log is noise that trains people to skim.
        """
        read = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        dim = read()
        return int(dim) if dim is not None else 0

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        texts_list = list(texts)
        batch = self._batch_size
        loop = asyncio.get_running_loop()
        result: list[float] = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts_list,
                batch_size=batch,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist(),
        )
        return result  # type: ignore[return-value]

    async def embed_query(self, text: str) -> Sequence[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]
