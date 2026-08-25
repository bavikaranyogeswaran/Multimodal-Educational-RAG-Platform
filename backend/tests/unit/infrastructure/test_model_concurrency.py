"""The local models are shared, and only one caller may be inside one at a time.

Both adapters load their model once and hold it for the life of the process, so every
request in that process scores against the same object. The tokeniser underneath is
reconfigured on entry to set truncation and padding, and a second caller arriving while
that is happening does not read a stale setting — it aborts, and a retrieval that was
working fails with an error from inside the tokeniser that names nothing about the call
that collided with it.

Retrieval reaches this without doing anything unusual: expanding one question into four
and embedding all four at once is a single `gather`, and two students asking at the same
moment is the ordinary case rather than the busy one. So the property under test is not
that the adapters are fast but that they queue, and the fake models here report the
deepest overlap they ever saw rather than merely returning a value.

These use fakes deliberately. Loading the real weights to prove a lock holds would make
the check slow enough to skip, and the constraint belongs to how the adapter calls the
model, not to what the model computes.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from app.infrastructure.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.infrastructure.reranking.cross_encoder import CrossEncoderReranker

#: Long enough that two unsynchronised threads would reliably be inside at once, short
#: enough that the whole file stays in the fast suite.
_DWELL = 0.02

_CALLERS = 6


class _Vectors:
    """Stands in for the numpy array both adapters call `.tolist()` on."""

    def __init__(self, rows: list[list[float]] | list[float]) -> None:
        self._rows = rows

    def tolist(self) -> list[list[float]] | list[float]:
        return self._rows


class _CountingModel:
    """Records the deepest overlap it ever saw, which is the whole point of the fake."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.inside = 0
        self.max_overlap = 0
        self.calls = 0

    def _enter(self) -> None:
        with self._lock:
            self.inside += 1
            self.calls += 1
            self.max_overlap = max(self.max_overlap, self.inside)

    def _leave(self) -> None:
        with self._lock:
            self.inside -= 1

    def _dwell(self) -> None:
        self._enter()
        try:
            time.sleep(_DWELL)
        finally:
            self._leave()


class _FakeEncoder(_CountingModel):
    def encode(self, texts: list[str], **_kwargs: Any) -> _Vectors:
        self._dwell()
        return _Vectors([[0.1, 0.2] for _ in texts])


class _FakeCrossEncoder(_CountingModel):
    def predict(self, pairs: list[list[str]], **_kwargs: Any) -> _Vectors:
        self._dwell()
        return _Vectors([1.0 for _ in pairs])


@pytest.fixture
def encoder(monkeypatch: pytest.MonkeyPatch) -> _FakeEncoder:
    fake = _FakeEncoder()
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda *_a, **_k: fake)
    return fake


@pytest.fixture
def cross_encoder(monkeypatch: pytest.MonkeyPatch) -> _FakeCrossEncoder:
    fake = _FakeCrossEncoder()
    monkeypatch.setattr("sentence_transformers.CrossEncoder", lambda *_a, **_k: fake)
    return fake


class TestEmbedderSerialises:
    async def test_queries_embedded_at_once_do_not_enter_the_model_together(
        self, encoder: _FakeEncoder
    ) -> None:
        """One expanded question becomes several embeddings requested in one gather,
        which is what retrieval does on every query that gets expanded."""
        embedder = SentenceTransformerEmbedder(model_id="fake", device="cpu", batch_size=8)

        await asyncio.gather(*[embedder.embed_query(f"question {i}") for i in range(_CALLERS)])

        assert encoder.calls == _CALLERS
        assert encoder.max_overlap == 1

    async def test_every_caller_still_gets_its_own_answer(self, encoder: _FakeEncoder) -> None:
        """Serialising must not merge or drop calls, only order them."""
        embedder = SentenceTransformerEmbedder(model_id="fake", device="cpu", batch_size=8)

        vectors = await asyncio.gather(
            *[embedder.embed_query(f"question {i}") for i in range(_CALLERS)]
        )

        assert encoder.calls == _CALLERS
        assert len(vectors) == _CALLERS
        assert all(list(vector) == [0.1, 0.2] for vector in vectors)


class TestRerankerSerialises:
    async def test_two_questions_do_not_enter_the_model_together(
        self, cross_encoder: _FakeCrossEncoder
    ) -> None:
        """Not reachable from one request, which is why it went unnoticed: reranking runs
        once per question. Two students asking at the same time is what reaches it."""
        reranker = CrossEncoderReranker(model_id="fake", device="cpu", batch_size=8)

        await asyncio.gather(
            *[reranker.rerank(f"question {i}", ["a passage"]) for i in range(_CALLERS)]
        )

        assert cross_encoder.calls == _CALLERS
        assert cross_encoder.max_overlap == 1

    async def test_an_empty_candidate_list_never_reaches_the_model(
        self, cross_encoder: _FakeCrossEncoder
    ) -> None:
        """So an empty retrieval does not queue behind a real one for nothing."""
        reranker = CrossEncoderReranker(model_id="fake", device="cpu", batch_size=8)

        assert await reranker.rerank("a question", []) == []
        assert cross_encoder.calls == 0
