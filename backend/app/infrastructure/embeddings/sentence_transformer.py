"""Sentence-Transformers embedding adapter.

Requires the ml dependency group: uv sync --group ml
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence


class SentenceTransformerEmbedder:
    """EmbeddingPort backed by a local sentence-transformers model.

    Model weights are loaded once at construction and held for the worker's
    lifetime. Encoding is synchronous, so each call is offloaded to the
    default thread executor to avoid blocking the event loop.

    One encode runs at a time. The tokeniser underneath is a Rust object that is
    reconfigured on entry to set truncation and padding, so a second thread arriving
    mid-call does not read a stale setting — it aborts the whole call, and the caller
    sees the retrieval fail rather than an embedding come back wrong. Callers that
    embed several texts at once reach this by asking the event loop for both at the
    same time, which is ordinary and correct on their side, so the constraint is held
    here where the model is rather than left for each of them to remember.
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
        self._encoding = threading.Lock()

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
        loop = asyncio.get_running_loop()
        result: list[float] = await loop.run_in_executor(None, self._encode, texts_list)
        return result  # type: ignore[return-value]

    def _encode(self, texts: list[str]) -> list[float]:
        """Encode on the executor thread, one caller at a time.

        Waiting happens on the executor thread rather than the event loop, so a queue
        here delays the embeddings and nothing else.
        """
        with self._encoding:
            encoded = self._model.encode(
                texts,
                batch_size=self._batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        return encoded.tolist()  # type: ignore[no-any-return]

    async def embed_query(self, text: str) -> Sequence[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]
