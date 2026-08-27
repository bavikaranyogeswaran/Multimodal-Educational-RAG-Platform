"""Tests for HierarchicalSynthesizer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.application.queries.evidence_selector import SubQuestionEvidence
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer, MultiHopAnswer
from app.domain.enums import CoverageStatus
from app.domain.ports.multi_hop import MultiHopSynthesisPort, SubAnswerItem
from app.domain.retrieval.decomposition import SubQuestion


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sq(sq_id: str) -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _sub_evidence(
    sq_id: str,
    status: CoverageStatus = CoverageStatus.SUPPORTED,
    evidence: list | None = None,
) -> SubQuestionEvidence:
    return SubQuestionEvidence(
        sub_question=_sq(sq_id),
        evidence=tuple(evidence or []),
        coverage=status,
    )


def _port(
    *,
    sub_answer: str = "sub-answer",
    final_answer: str = "final answer",
) -> AsyncMock:
    port = AsyncMock(spec=MultiHopSynthesisPort)
    port.synthesize_sub_answer = AsyncMock(return_value=sub_answer)
    port.synthesize_final = AsyncMock(return_value=final_answer)
    return port


# ---------------------------------------------------------------------------
# single sub-question
# ---------------------------------------------------------------------------


class TestSingleSubQuestion:
    async def test_returns_multi_hop_answer(self) -> None:
        port = _port(sub_answer="sub", final_answer="final")
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("original query", [_sub_evidence("Q1")])

        assert isinstance(result, MultiHopAnswer)
        assert result.answer == "final"

    async def test_sub_answer_port_called_once(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [_sub_evidence("Q1")])

        port.synthesize_sub_answer.assert_awaited_once()

    async def test_final_port_called_once(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [_sub_evidence("Q1")])

        port.synthesize_final.assert_awaited_once()

    async def test_sub_answer_uses_sub_question_text(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [_sub_evidence("Q1")])

        args = port.synthesize_sub_answer.call_args.args
        assert args[0] == "Question Q1?"

    async def test_sub_answer_receives_evidence(self) -> None:
        ev = MagicMock()
        port = _port()
        se = _sub_evidence("Q1", evidence=[ev])
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [se])

        args = port.synthesize_sub_answer.call_args.args
        assert ev in args[1]

    async def test_sub_answer_receives_coverage(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [_sub_evidence("Q1", CoverageStatus.PARTIALLY_SUPPORTED)])

        args = port.synthesize_sub_answer.call_args.args
        assert args[2] is CoverageStatus.PARTIALLY_SUPPORTED

    async def test_final_synthesis_receives_original_query(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("what is photosynthesis?", [_sub_evidence("Q1")])

        args = port.synthesize_final.call_args.args
        assert args[0] == "what is photosynthesis?"


# ---------------------------------------------------------------------------
# multiple sub-questions
# ---------------------------------------------------------------------------


class TestMultipleSubQuestions:
    async def test_sub_answer_called_once_per_sub_question(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [
            _sub_evidence("Q1"),
            _sub_evidence("Q2"),
            _sub_evidence("Q3"),
        ])

        assert port.synthesize_sub_answer.await_count == 3

    async def test_final_call_receives_all_sub_answers(self) -> None:
        port = AsyncMock(spec=MultiHopSynthesisPort)
        port.synthesize_sub_answer = AsyncMock(side_effect=["ans1", "ans2"])
        port.synthesize_final = AsyncMock(return_value="final")
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [_sub_evidence("Q1"), _sub_evidence("Q2")])

        sub_answers_arg = port.synthesize_final.call_args.args[1]
        answers = [sa.answer for sa in sub_answers_arg]
        assert answers == ["ans1", "ans2"]

    async def test_sub_answers_in_same_order_as_input(self) -> None:
        port = AsyncMock(spec=MultiHopSynthesisPort)
        port.synthesize_sub_answer = AsyncMock(side_effect=["ans_q1", "ans_q2", "ans_q3"])
        port.synthesize_final = AsyncMock(return_value="final")
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [
            _sub_evidence("Q1"),
            _sub_evidence("Q2"),
            _sub_evidence("Q3"),
        ])

        answers = [sa.answer for sa in result.sub_answers]
        assert answers == ["ans_q1", "ans_q2", "ans_q3"]

    async def test_sub_answers_tuple_has_correct_sub_question_text(self) -> None:
        port = _port(sub_answer="x")
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [
            _sub_evidence("Q1"),
            _sub_evidence("Q2"),
        ])

        texts = [sa.sub_question for sa in result.sub_answers]
        assert texts == ["Question Q1?", "Question Q2?"]

    async def test_coverage_carried_through_to_sub_answers(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [
            _sub_evidence("Q1", CoverageStatus.CONFLICTING),
            _sub_evidence("Q2", CoverageStatus.PARTIALLY_SUPPORTED),
        ])

        assert result.sub_answers[0].coverage is CoverageStatus.CONFLICTING
        assert result.sub_answers[1].coverage is CoverageStatus.PARTIALLY_SUPPORTED

    async def test_all_four_coverage_statuses_passed_to_port(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [
            _sub_evidence("Q1", CoverageStatus.SUPPORTED),
            _sub_evidence("Q2", CoverageStatus.PARTIALLY_SUPPORTED),
            _sub_evidence("Q3", CoverageStatus.CONFLICTING),
            _sub_evidence("Q4", CoverageStatus.UNSUPPORTED),
        ])

        statuses_passed = [
            call.args[2]
            for call in port.synthesize_sub_answer.call_args_list
        ]
        assert CoverageStatus.SUPPORTED in statuses_passed
        assert CoverageStatus.PARTIALLY_SUPPORTED in statuses_passed
        assert CoverageStatus.CONFLICTING in statuses_passed
        assert CoverageStatus.UNSUPPORTED in statuses_passed


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_empty_sub_evidences_no_sub_answer_calls(self) -> None:
        port = _port(final_answer="nothing to say")
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [])

        port.synthesize_sub_answer.assert_not_awaited()
        port.synthesize_final.assert_awaited_once()
        assert result.sub_answers == ()

    async def test_empty_sub_evidences_final_called_with_empty_list(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        await synth.synthesize("query", [])

        sub_answers_arg = port.synthesize_final.call_args.args[1]
        assert list(sub_answers_arg) == []

    async def test_result_sub_answers_is_tuple(self) -> None:
        port = _port()
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [_sub_evidence("Q1")])

        assert isinstance(result.sub_answers, tuple)

    async def test_final_answer_from_port_is_answer_field(self) -> None:
        port = _port(final_answer="the synthesized answer text")
        synth = HierarchicalSynthesizer(port)

        result = await synth.synthesize("query", [_sub_evidence("Q1")])

        assert result.answer == "the synthesized answer text"
