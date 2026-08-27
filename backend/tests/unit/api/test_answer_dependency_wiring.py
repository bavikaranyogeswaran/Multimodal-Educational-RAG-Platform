"""Tests that get_answer_use_case actually hands AnswerUseCase its collaborators.

AnswerUseCase takes kb_repo, graph_repo, memory_repo and multi_hop as optional
arguments that default to None, and it degrades silently when one is missing: no
graph context, no memory context, no decomposition, and no error either. That is
the right behaviour at the use-case level — those paths are genuinely optional —
but it means a dependency that forgets to pass one produces a system that answers
questions with a whole retrieval path switched off, while every unit test that
constructs the use case directly keeps passing.

These tests close that gap by asserting on what the dependency builds, so a
collaborator dropped from the call is a failure here rather than a feature that
quietly stops working in production.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.dependencies.answer import get_answer_use_case
from app.domain.scope import ScopeContext

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _container() -> MagicMock:
    """A container whose slots are all satisfiable without touching a model or a socket."""
    container = MagicMock()
    container.token_counter.count = lambda text: len(text.split())
    container.memory_extractor = None
    return container


async def _build() -> object:
    """Assemble the use case the way the route does, with the model adapters stubbed.

    Only the two Ollama adapters are patched: they are constructed eagerly and would
    otherwise reach for a gateway. Everything else is real, which is the point — the
    repositories under test are the real classes, constructed against a mock session.
    """
    with (
        patch("app.api.dependencies.answer.OllamaClaimEntailment"),
        patch("app.api.dependencies.answer.OllamaAnswerFaithfulness"),
    ):
        return await get_answer_use_case(
            retrieve=AsyncMock(),
            scope=_SCOPE,
            session=MagicMock(),
            container=_container(),
        )


# ---------------------------------------------------------------------------
# The optional collaborators are passed, not left to default
# ---------------------------------------------------------------------------


class TestCollaboratorsAreWired:
    @pytest.mark.parametrize(
        "attribute",
        ["_kb_repo", "_graph_repo", "_memory_repo"],
    )
    async def test_collaborator_is_not_none(self, attribute: str) -> None:
        use_case = await _build()
        assert getattr(use_case, attribute) is not None, (
            f"{attribute} was left at its None default, so the retrieval path it "
            f"serves is switched off on every turn"
        )

    async def test_repositories_carry_the_request_scope(self) -> None:
        """A repository built on the wrong scope would read another student's rows."""
        use_case = await _build()
        for attribute in ("_kb_repo", "_graph_repo", "_memory_repo"):
            repo = getattr(use_case, attribute)
            assert repo._scope is _SCOPE

    async def test_repositories_share_the_request_session(self) -> None:
        """All three reads happen before streaming starts, so one session serves them."""
        use_case = await _build()
        sessions = {
            getattr(use_case, attribute)._session
            for attribute in ("_kb_repo", "_graph_repo", "_memory_repo")
        }
        assert len(sessions) == 1


# ---------------------------------------------------------------------------
# Multi-hop is knowingly absent rather than forgotten
# ---------------------------------------------------------------------------


class TestMultiHopStillUnwired:
    async def test_multi_hop_is_none_until_its_adapters_exist(self) -> None:
        """Guards the boundary between "not built" and "built but dropped".

        MultiHopAnswerUseCase needs three model-backed adapters that do not exist
        yet — query decomposition, coverage classification and hierarchical
        synthesis. Until they do, the dependency cannot supply it, and this test
        records that as a deliberate state. When those adapters land, this test
        should fail and be replaced by the positive assertion above.
        """
        use_case = await _build()
        assert use_case._multi_hop is None
