"""Tests for QueryRewriter.

All tests use a mock ModelGatewayPort — no inference runs. Coverage:
  - empty history → (query, False), no gateway call
  - non-follow-up queries → (query, False), no gateway call
  - each follow-up signal category → gateway called, (rewritten, True) returned
  - model call uses ModelTask.QUERY_REWRITE and temperature=0.0
  - history is passed in the request's conversation_history field
  - current query is in the request's query field
  - rewritten text comes from response.content.value
  - was_rewritten=False for pass-through, True after model call
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import MessageRole, ModelTask
from app.domain.models.entities import ConversationTurn, ModelResponse
from app.domain.retrieval.rewriter import QueryRewriter
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _turn(role: MessageRole, text: str) -> ConversationTurn:
    return ConversationTurn(role=role, content=UntrustedText(text))


def _history() -> tuple[ConversationTurn, ...]:
    return (
        _turn(MessageRole.USER, "What is gradient descent?"),
        _turn(MessageRole.ASSISTANT, "Gradient descent is an optimisation algorithm."),
    )


def _response(text: str) -> ModelResponse:
    return ModelResponse(
        model_task=ModelTask.QUERY_REWRITE,
        model_id="test-model",
        content=UntrustedText(text),
        prompt_tokens=30,
        completion_tokens=15,
    )


def _gateway(rewritten: str) -> MagicMock:
    gw = MagicMock()
    gw.generate = AsyncMock(return_value=_response(rewritten))
    return gw


@pytest.fixture
def gw() -> MagicMock:
    return _gateway("How does the gradient descent learning rate affect convergence?")


# ---------------------------------------------------------------------------
# Short-circuit: empty history
# ---------------------------------------------------------------------------


class TestEmptyHistory:
    async def test_returns_original_when_no_history(self, gw: MagicMock) -> None:
        query, was_rewritten = await QueryRewriter(gw).rewrite("it converges quickly", ())
        assert query == "it converges quickly"
        assert was_rewritten is False

    async def test_gateway_not_called_when_no_history(self, gw: MagicMock) -> None:
        await QueryRewriter(gw).rewrite("explain it", ())
        gw.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Short-circuit: no follow-up signal
# ---------------------------------------------------------------------------


class TestNoFollowUpSignal:
    @pytest.mark.parametrize(
        "query",
        [
            "What is backpropagation?",
            "How does gradient descent work?",
            "Explain the attention mechanism",
            "Define entropy in information theory",
            "What are the differences between L1 and L2 regularization?",
            "Summarize chapter 3",
        ],
    )
    async def test_independent_queries_pass_through(
        self, query: str, gw: MagicMock
    ) -> None:
        result_query, was_rewritten = await QueryRewriter(gw).rewrite(query, _history())
        assert result_query == query
        assert was_rewritten is False

    async def test_gateway_not_called_for_independent_query(self, gw: MagicMock) -> None:
        await QueryRewriter(gw).rewrite("What is entropy?", _history())
        gw.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Follow-up detection: anaphoric opening
# ---------------------------------------------------------------------------


class TestAnaphoricOpening:
    @pytest.mark.parametrize(
        "query",
        [
            "It converges slowly at high learning rates",
            "This is what I meant by vanishing gradients",
            "That approach has a drawback",
            "They are used in every layer",
            "These are the key properties",
            "Those results confirm the theory",
            "Its derivative is always positive",
            "Their weights are updated together",
            "Them being frozen helps with transfer learning",
            "The same applies to ReLU",
            "The above is why momentum is used",
            "The previous explanation was unclear",
        ],
    )
    async def test_detects_anaphoric_opening(self, query: str) -> None:
        gw = _gateway("Standalone version of: " + query)
        _, was_rewritten = await QueryRewriter(gw).rewrite(query, _history())
        assert was_rewritten is True


# ---------------------------------------------------------------------------
# Follow-up detection: bare interrogative
# ---------------------------------------------------------------------------


class TestBareInterrogative:
    @pytest.mark.parametrize(
        "query",
        [
            "Why?",
            "How?",
            "When?",
            "Who?",
            "Which?",
            "What?",
            "Why??",
        ],
    )
    async def test_detects_bare_interrogative(self, query: str) -> None:
        gw = _gateway("Standalone version of: " + query)
        _, was_rewritten = await QueryRewriter(gw).rewrite(query, _history())
        assert was_rewritten is True


# ---------------------------------------------------------------------------
# Follow-up detection: back-reference phrases
# ---------------------------------------------------------------------------


class TestBackReferencePhrases:
    @pytest.mark.parametrize(
        "query",
        [
            "As mentioned, what is the formula?",
            "As described above, how does it work?",
            "As stated earlier, what does that mean?",
            "As explained, can you show an example?",
            "As noted, is this the standard approach?",
            "You mentioned that it diverges — why?",
            "You said it was important; can you elaborate?",
            "Tell me more about the learning rate",
            "Can you elaborate on that?",
            "Explain it in more detail",
            "Explain that with an example",
            "Explain this concept further",
            "Explain them one by one",
            "What does it mean exactly?",
            "What does this mean in practice?",
            "What about it specifically?",
            "What about that property?",
        ],
    )
    async def test_detects_back_reference_phrase(self, query: str) -> None:
        gw = _gateway("Standalone: " + query)
        _, was_rewritten = await QueryRewriter(gw).rewrite(query, _history())
        assert was_rewritten is True


# ---------------------------------------------------------------------------
# Follow-up detection: continuation openings
# ---------------------------------------------------------------------------


class TestContinuationOpening:
    @pytest.mark.parametrize(
        "query",
        [
            "And what does the loss function look like?",
            "But why does it oscillate?",
            "So how is the weight updated?",
            "And how does momentum help?",
            "But when should I use Adam instead?",
        ],
    )
    async def test_detects_continuation_opening(self, query: str) -> None:
        gw = _gateway("Standalone: " + query)
        _, was_rewritten = await QueryRewriter(gw).rewrite(query, _history())
        assert was_rewritten is True


# ---------------------------------------------------------------------------
# Model call contract
# ---------------------------------------------------------------------------


class TestModelCall:
    async def test_uses_query_rewrite_task(self, gw: MagicMock) -> None:
        await QueryRewriter(gw).rewrite("explain it", _history())
        request = gw.generate.call_args[0][0]
        assert request.model_task == ModelTask.QUERY_REWRITE

    async def test_temperature_is_zero(self, gw: MagicMock) -> None:
        await QueryRewriter(gw).rewrite("explain it", _history())
        request = gw.generate.call_args[0][0]
        assert request.temperature == 0.0

    async def test_query_field_is_original_query(self, gw: MagicMock) -> None:
        query = "explain it"
        await QueryRewriter(gw).rewrite(query, _history())
        request = gw.generate.call_args[0][0]
        assert request.query == query

    async def test_history_passed_in_conversation_history(self, gw: MagicMock) -> None:
        hist = _history()
        await QueryRewriter(gw).rewrite("explain it", hist)
        request = gw.generate.call_args[0][0]
        assert request.conversation_history == hist

    async def test_no_evidence_in_request(self, gw: MagicMock) -> None:
        await QueryRewriter(gw).rewrite("explain it", _history())
        request = gw.generate.call_args[0][0]
        assert request.evidence == ()


# ---------------------------------------------------------------------------
# Return values
# ---------------------------------------------------------------------------


class TestReturnValues:
    async def test_was_rewritten_false_for_passthrough(self) -> None:
        gw = _gateway("should not be called")
        _, was_rewritten = await QueryRewriter(gw).rewrite("What is entropy?", _history())
        assert was_rewritten is False

    async def test_was_rewritten_true_after_model_call(self, gw: MagicMock) -> None:
        _, was_rewritten = await QueryRewriter(gw).rewrite("explain it", _history())
        assert was_rewritten is True

    async def test_returns_model_response_as_standalone(self) -> None:
        rewritten = "How does the learning rate affect gradient descent convergence speed?"
        gw = _gateway(rewritten)
        # "Tell me more" fires the back-reference heuristic
        query, was_rewritten = await QueryRewriter(gw).rewrite(
            "Tell me more about how it affects speed", _history()
        )
        assert query == rewritten
        assert was_rewritten is True

    async def test_strips_leading_trailing_whitespace(self) -> None:
        gw = _gateway("  How does it converge?  ")
        query, _ = await QueryRewriter(gw).rewrite("how?", _history())
        assert query == "How does it converge?"
