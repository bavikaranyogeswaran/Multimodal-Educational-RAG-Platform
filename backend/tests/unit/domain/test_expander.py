"""Tests for QueryExpander.

All tests use a mock ModelGatewayPort. Coverage:
  - expand_queries=False → [query] returned, gateway not called
  - expand_queries=True → gateway called with QUERY_EXPANSION and temperature=0.0
  - original query is always the first element
  - newline-separated variants are parsed and appended
  - numbered prefixes are stripped ("1. ", "2) ")
  - dash/bullet prefixes are stripped ("- ", "* ", "• ")
  - blank lines in model output are ignored
  - result capped at original + 3 variants
  - variant equal to original is not duplicated
  - model returning only blank text → [query] returned
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import ModelTask, QueryClass
from app.domain.models.entities import ModelResponse
from app.domain.retrieval.entities import RetrievalPlan
from app.domain.retrieval.expander import QueryExpander
from app.domain.values import UntrustedText


def _plan(*, expand: bool) -> RetrievalPlan:
    qc = QueryClass.DIRECT if expand else QueryClass.SUMMARY
    return RetrievalPlan.for_query(qc)


def _response(text: str) -> ModelResponse:
    return ModelResponse(
        model_task=ModelTask.QUERY_EXPANSION,
        model_id="test-model",
        content=UntrustedText(text),
        prompt_tokens=20,
        completion_tokens=10,
    )


def _gateway(response_text: str) -> MagicMock:
    gw = MagicMock()
    gw.generate = AsyncMock(return_value=_response(response_text))
    return gw


@pytest.fixture
def expandable_plan() -> RetrievalPlan:
    return _plan(expand=True)


@pytest.fixture
def suppressed_plan() -> RetrievalPlan:
    return _plan(expand=False)


# ---------------------------------------------------------------------------
# Expansion suppression
# ---------------------------------------------------------------------------


class TestExpansionSuppressed:
    async def test_returns_only_original_when_suppressed(
        self, suppressed_plan: RetrievalPlan
    ) -> None:
        gw = _gateway("variant a\nvariant b")
        result = await QueryExpander(gw).expand("gradient descent", suppressed_plan)
        assert result == ["gradient descent"]

    async def test_gateway_not_called_when_suppressed(
        self, suppressed_plan: RetrievalPlan
    ) -> None:
        gw = MagicMock()
        gw.generate = AsyncMock()
        await QueryExpander(gw).expand("gradient descent", suppressed_plan)
        gw.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Model call contract
# ---------------------------------------------------------------------------


class TestModelCall:
    async def test_uses_query_expansion_task(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("variant a")
        await QueryExpander(gw).expand("what is entropy?", expandable_plan)

        request = gw.generate.call_args[0][0]
        assert request.model_task == ModelTask.QUERY_EXPANSION

    async def test_temperature_is_zero(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("variant a")
        await QueryExpander(gw).expand("what is entropy?", expandable_plan)

        request = gw.generate.call_args[0][0]
        assert request.temperature == 0.0

    async def test_query_field_is_original_query(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("variant a")
        query = "how does backpropagation work?"
        await QueryExpander(gw).expand(query, expandable_plan)

        request = gw.generate.call_args[0][0]
        assert request.query == query

    async def test_no_evidence_in_request(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("variant a")
        await QueryExpander(gw).expand("what is a neuron?", expandable_plan)

        request = gw.generate.call_args[0][0]
        assert request.evidence == ()

    async def test_no_conversation_history_in_request(
        self, expandable_plan: RetrievalPlan
    ) -> None:
        gw = _gateway("variant a")
        await QueryExpander(gw).expand("what is a neuron?", expandable_plan)

        request = gw.generate.call_args[0][0]
        assert request.conversation_history == ()


# ---------------------------------------------------------------------------
# Return structure
# ---------------------------------------------------------------------------


class TestReturnStructure:
    async def test_original_is_always_first(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("rephrase 1\nrephrase 2")
        result = await QueryExpander(gw).expand("what is dropout?", expandable_plan)
        assert result[0] == "what is dropout?"

    async def test_variants_appended_after_original(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("rephrase 1\nrephrase 2")
        result = await QueryExpander(gw).expand("what is dropout?", expandable_plan)
        assert "rephrase 1" in result
        assert "rephrase 2" in result

    async def test_empty_model_output_returns_only_original(
        self, expandable_plan: RetrievalPlan
    ) -> None:
        # "1.\n-\n*" — each line has only a list marker; after stripping they are blank
        gw = _gateway("1.\n-\n*")
        result = await QueryExpander(gw).expand("what is dropout?", expandable_plan)
        assert result == ["what is dropout?"]

    async def test_single_variant_appended(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("one alternative")
        result = await QueryExpander(gw).expand("explain relu", expandable_plan)
        assert result == ["explain relu", "one alternative"]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    async def test_strips_numbered_dot_prefix(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("1. first variant\n2. second variant")
        result = await QueryExpander(gw).expand("what is overfitting?", expandable_plan)
        assert "first variant" in result
        assert "second variant" in result

    async def test_strips_numbered_paren_prefix(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("1) first\n2) second")
        result = await QueryExpander(gw).expand("what is overfitting?", expandable_plan)
        assert "first" in result
        assert "second" in result

    async def test_strips_dash_prefix(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("- first variant\n- second variant")
        result = await QueryExpander(gw).expand("explain softmax", expandable_plan)
        assert "first variant" in result
        assert "second variant" in result

    async def test_strips_asterisk_prefix(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("* alpha\n* beta")
        result = await QueryExpander(gw).expand("explain softmax", expandable_plan)
        assert "alpha" in result
        assert "beta" in result

    async def test_strips_bullet_prefix(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("• one\n• two")
        result = await QueryExpander(gw).expand("explain softmax", expandable_plan)
        assert "one" in result
        assert "two" in result

    async def test_blank_lines_in_output_ignored(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("first\n\n\nsecond\n\n")
        result = await QueryExpander(gw).expand("what is relu?", expandable_plan)
        assert result == ["what is relu?", "first", "second"]

    async def test_variants_capped_at_three(self, expandable_plan: RetrievalPlan) -> None:
        gw = _gateway("a\nb\nc\nd\ne")
        result = await QueryExpander(gw).expand("what is relu?", expandable_plan)
        # original + up to 3 variants = 4 total
        assert len(result) == 4

    async def test_variant_equal_to_original_not_duplicated(
        self, expandable_plan: RetrievalPlan
    ) -> None:
        query = "what is relu?"
        gw = _gateway(f"{query}\ndifferent phrasing")
        result = await QueryExpander(gw).expand(query, expandable_plan)
        assert result.count(query) == 1
        assert "different phrasing" in result
