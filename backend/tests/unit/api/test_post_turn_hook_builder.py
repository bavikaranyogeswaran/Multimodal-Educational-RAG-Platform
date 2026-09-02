"""Tests for _build_post_turn_hook in app.api.dependencies.answer.

Verifies the hook:
  - calls ExtractMemoryUseCase with the assistant message id
  - calls EmbedMemoryUseCase with the embeddable_ids from extraction
  - skips embedding when no embeddable_ids are returned
  - commits each session after its work
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.dependencies.answer import _build_post_turn_hook
from app.domain.scope import ScopeContext

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_ASSISTANT_ID = uuid.uuid4()


def _make_container(extractor: object, embedder: object) -> MagicMock:
    container = MagicMock()
    container.memory_extractor = extractor
    container.embedder = embedder
    return container


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.merge = AsyncMock()
    return session


def _session_factory(*sessions):
    """Return a factory that yields sessions in order."""
    _sessions = list(sessions)

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncMock]:
        yield _sessions.pop(0)

    return _factory


def _extract_result(*, embeddable_ids: tuple[uuid.UUID, ...] = ()) -> MagicMock:
    result = MagicMock()
    result.embeddable_ids = embeddable_ids
    return result


# ---------------------------------------------------------------------------
# Extraction is called
# ---------------------------------------------------------------------------


class TestExtractionCalled:
    async def test_extract_use_case_called_with_assistant_id(self) -> None:
        fact_id = uuid.uuid4()
        extractor = AsyncMock()
        embedder = AsyncMock()
        container = _make_container(extractor, embedder)
        s1 = _make_session()
        s2 = _make_session()

        with (
            patch(
                "app.api.dependencies.answer.ExtractMemoryUseCase"
            ) as MockExtract,
            patch(
                "app.api.dependencies.answer.EmbedMemoryUseCase"
            ) as MockEmbed,
            patch(
                "app.api.dependencies.answer.SqlConversationRepository"
            ),
            patch(
                "app.api.dependencies.answer.SqlMemoryRepository"
            ),
        ):
            MockExtract.return_value.execute = AsyncMock(
                return_value=_extract_result(embeddable_ids=(fact_id,))
            )
            MockEmbed.return_value.execute = AsyncMock(return_value=MagicMock())

            hook = _build_post_turn_hook(
                session_factory=_session_factory(s1, s2),
                scope=_SCOPE,
                container=container,
            )
            await hook(_SCOPE, _ASSISTANT_ID)

        call_kwargs = MockExtract.return_value.execute.call_args[0][0]
        assert call_kwargs.message_id == _ASSISTANT_ID
        assert call_kwargs.scope is _SCOPE

    async def test_extraction_session_committed(self) -> None:
        extractor = AsyncMock()
        embedder = AsyncMock()
        container = _make_container(extractor, embedder)
        s1 = _make_session()
        s2 = _make_session()

        with (
            patch("app.api.dependencies.answer.ExtractMemoryUseCase") as MockExtract,
            patch("app.api.dependencies.answer.EmbedMemoryUseCase") as MockEmbed,
            patch("app.api.dependencies.answer.SqlConversationRepository"),
            patch("app.api.dependencies.answer.SqlMemoryRepository"),
        ):
            MockExtract.return_value.execute = AsyncMock(
                return_value=_extract_result(embeddable_ids=(uuid.uuid4(),))
            )
            MockEmbed.return_value.execute = AsyncMock(return_value=MagicMock())

            hook = _build_post_turn_hook(
                session_factory=_session_factory(s1, s2),
                scope=_SCOPE,
                container=container,
            )
            await hook(_SCOPE, _ASSISTANT_ID)

        s1.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Embedding is called when facts are extractable
# ---------------------------------------------------------------------------


class TestEmbeddingCalled:
    async def test_embed_use_case_called_with_embeddable_ids(self) -> None:
        fact_id = uuid.uuid4()
        extractor = AsyncMock()
        embedder = AsyncMock()
        container = _make_container(extractor, embedder)
        s1 = _make_session()
        s2 = _make_session()

        with (
            patch("app.api.dependencies.answer.ExtractMemoryUseCase") as MockExtract,
            patch("app.api.dependencies.answer.EmbedMemoryUseCase") as MockEmbed,
            patch("app.api.dependencies.answer.SqlConversationRepository"),
            patch("app.api.dependencies.answer.SqlMemoryRepository"),
        ):
            MockExtract.return_value.execute = AsyncMock(
                return_value=_extract_result(embeddable_ids=(fact_id,))
            )
            MockEmbed.return_value.execute = AsyncMock(return_value=MagicMock())

            hook = _build_post_turn_hook(
                session_factory=_session_factory(s1, s2),
                scope=_SCOPE,
                container=container,
            )
            await hook(_SCOPE, _ASSISTANT_ID)

        embed_cmd = MockEmbed.return_value.execute.call_args[0][0]
        assert fact_id in embed_cmd.fact_ids

    async def test_embedding_session_committed(self) -> None:
        fact_id = uuid.uuid4()
        extractor = AsyncMock()
        embedder = AsyncMock()
        container = _make_container(extractor, embedder)
        s1 = _make_session()
        s2 = _make_session()

        with (
            patch("app.api.dependencies.answer.ExtractMemoryUseCase") as MockExtract,
            patch("app.api.dependencies.answer.EmbedMemoryUseCase") as MockEmbed,
            patch("app.api.dependencies.answer.SqlConversationRepository"),
            patch("app.api.dependencies.answer.SqlMemoryRepository"),
        ):
            MockExtract.return_value.execute = AsyncMock(
                return_value=_extract_result(embeddable_ids=(fact_id,))
            )
            MockEmbed.return_value.execute = AsyncMock(return_value=MagicMock())

            hook = _build_post_turn_hook(
                session_factory=_session_factory(s1, s2),
                scope=_SCOPE,
                container=container,
            )
            await hook(_SCOPE, _ASSISTANT_ID)

        s2.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Embedding skipped when no facts extracted
# ---------------------------------------------------------------------------


class TestEmbeddingSkipped:
    async def test_embed_not_called_when_no_embeddable_ids(self) -> None:
        extractor = AsyncMock()
        embedder = AsyncMock()
        container = _make_container(extractor, embedder)
        s1 = _make_session()

        with (
            patch("app.api.dependencies.answer.ExtractMemoryUseCase") as MockExtract,
            patch("app.api.dependencies.answer.EmbedMemoryUseCase") as MockEmbed,
            patch("app.api.dependencies.answer.SqlConversationRepository"),
            patch("app.api.dependencies.answer.SqlMemoryRepository"),
        ):
            MockExtract.return_value.execute = AsyncMock(
                return_value=_extract_result(embeddable_ids=())
            )

            hook = _build_post_turn_hook(
                session_factory=_session_factory(s1),
                scope=_SCOPE,
                container=container,
            )
            await hook(_SCOPE, _ASSISTANT_ID)

        MockEmbed.return_value.execute.assert_not_called()
