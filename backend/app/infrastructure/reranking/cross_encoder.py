"""Cross-encoder reranker adapter backed by sentence-transformers.

Requires the ml dependency group: uv sync --group ml

The model is loaded once at construction and held for the process lifetime.
`predict` is synchronous, so each call is offloaded to the default thread
executor to avoid blocking the event loop during batch scoring.

Held for the process lifetime means shared by every request in it, so scoring is
serialised: the tokeniser underneath is reconfigured on entry, and a second caller
arriving mid-call aborts the scoring outright rather than returning anything wrong.
One question at a time reaches the model, and the queue costs latency only.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence


class CrossEncoderReranker:
    """RerankerPort backed by a local cross-encoder model (e.g. ms-marco-MiniLM-L6-v2).

    Scores are raw logits from the model's classification head. Higher values
    indicate more relevant (query, passage) pairs. Callers use the scores for
    relative ordering only — they are not calibrated probabilities.
    """

    def __init__(self, *, model_id: str, device: str, batch_size: int) -> None:
        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install the ml dependency group: uv sync --group ml"
            ) from exc
        self._model = CrossEncoder(model_id, device=device)
        self._batch_size = batch_size
        self._scoring = threading.Lock()

    async def rerank(
        self,
        query: str,
        candidates: Sequence[str],
    ) -> Sequence[float]:
        """Score each candidate against the query.

        Returns one score per candidate in the same order as `candidates`.
        An empty candidate list returns immediately without touching the model.
        """
        if not candidates:
            return []

        pairs = [[query, c] for c in candidates]
        loop = asyncio.get_running_loop()

        scores: list[float] = await loop.run_in_executor(None, self._predict, pairs)

        return scores

    def _predict(self, pairs: list[list[str]]) -> list[float]:
        """Score on the executor thread, one caller at a time.

        Waiting happens on the executor thread rather than the event loop, so a queue
        here delays the scoring and nothing else.
        """
        with self._scoring:
            scored = self._model.predict(
                pairs,
                batch_size=self._batch_size,
                show_progress_bar=False,
            )
        return scored.tolist()  # type: ignore[no-any-return]
