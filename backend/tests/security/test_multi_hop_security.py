"""Security tests: scope isolation invariants for the multi-hop retrieval pipeline.

Verifies two invariants that must hold throughout the multi-hop pipeline:

  1. Scope forwarding — the scope passed into IterativeRetrievalLoop.run() is
     forwarded unchanged to every SubQuestionPipeline.run_all() call, including
     retry rounds. The scope must never be dropped, substituted, or derived from
     the retry filters.

  2. End-to-end scope thread — the scope in MultiHopAnswerCommand reaches every
     stage: decomposer and iterative retrieval loop. A silently swapped scope at
     any stage would retrieve evidence from the wrong knowledge base without
     raising any error.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.multi_hop_answer import MultiHopAnswerCommand, MultiHopAnswerUseCase
from app.application.queries.coverage_classifier import CoverageClassifier, SubQuestionCoverage
from app.application.queries.document_selection import DocumentSelection, DocumentSelector
from app.application.queries.evidence_selector import EvidenceSelector, SubQuestionEvidence
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer, MultiHopAnswer
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop, IterativeRetrievalResult
from app.application.queries.sub_question_pipeline import SubQuestionPipeline, SubQuestionResult
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.scope import ScopeContext


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _sq(sq_id: str) -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _plan(*ids: str) -> DecompositionPlan:
    return DecompositionPlan.build("original query", [_sq(q) for q in ids])


def _sq_result(sq: SubQuestion) -> SubQuestionResult:
    return SubQuestionResult(sub_question=sq, evidence=[], standalone_query=sq.text)


def _coverage(sq: SubQuestion, status: CoverageStatus) -> SubQuestionCoverage:
    return SubQuestionCoverage(sub_question=sq, evidence=[], coverage=status)


def _make_loop(
    *,
    round1_coverages: list[SubQuestionCoverage],
    round2_coverages: list[SubQuestionCoverage] | None = None,
) -> tuple[IterativeRetrievalLoop, AsyncMock, MagicMock]:
    plan_sqs = [c.sub_question for c in round1_coverages]
    round1_results = [_sq_result(sq) for sq in plan_sqs]

    pipeline = MagicMock(spec=SubQuestionPipeline)
    classifier = MagicMock(spec=CoverageClassifier)
    selector = MagicMock(spec=DocumentSelector)

    if round2_coverages is not None:
        round2_sqs = [c.sub_question for c in round2_coverages]
        round2_results = [_sq_result(sq) for sq in round2_sqs]
        pipeline.run_all = AsyncMock(side_effect=[round1_results, round2_results])
        classifier.classify_all = AsyncMock(side_effect=[round1_coverages, round2_coverages])
    else:
        pipeline.run_all = AsyncMock(return_value=round1_results)
        classifier.classify_all = AsyncMock(return_value=round1_coverages)

    selector.select = MagicMock(
        return_value=DocumentSelection(selected_ids=frozenset({uuid.uuid4()}), scores=())
    )

    loop = IterativeRetrievalLoop(pipeline=pipeline, classifier=classifier, selector=selector)
    return loop, pipeline, selector


# ---------------------------------------------------------------------------
# 1. IterativeRetrievalLoop — scope forwarded in round 1
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_loop_round1_pipeline_receives_original_scope() -> None:
    """The scope passed to run() must reach SubQuestionPipeline.run_all() in round 1.

    A missing or substituted scope would retrieve evidence from the wrong knowledge
    base without raising any error.
    """
    sq = _sq("Q1")
    scope = _scope()
    plan = _plan("Q1")
    loop, pipeline, _ = _make_loop(
        round1_coverages=[_coverage(sq, CoverageStatus.SUPPORTED)]
    )

    await loop.run(plan, scope, max_rounds=1)

    call_scope = pipeline.run_all.call_args_list[0].args[1]
    assert call_scope is scope


# ---------------------------------------------------------------------------
# 2. IterativeRetrievalLoop — scope forwarded unchanged in retry rounds
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_loop_retry_round_pipeline_receives_original_scope() -> None:
    """The retry round must forward the same scope object — not drop or substitute it.

    The retry filters narrow the document set (from evidence gathered in the same
    KB), but the scope argument to run_all() must remain the original scope so the
    underlying retriever still applies its user_id / knowledge_base_id gate.
    """
    sq = _sq("Q1")
    scope = _scope()
    plan = _plan("Q1")
    loop, pipeline, _ = _make_loop(
        round1_coverages=[_coverage(sq, CoverageStatus.UNSUPPORTED)],
        round2_coverages=[_coverage(sq, CoverageStatus.SUPPORTED)],
    )

    await loop.run(plan, scope, max_rounds=2)

    assert pipeline.run_all.await_count == 2
    retry_scope = pipeline.run_all.call_args_list[1].args[1]
    assert retry_scope is scope


@pytest.mark.security
@pytest.mark.gate
async def test_loop_retry_scope_is_not_derived_from_filters() -> None:
    """The retry-round scope must be the same object as the round-1 scope.

    If the loop derived a new scope from the retry filters (document IDs), it
    would lose the user_id and knowledge_base_id bindings, opening the possibility
    of cross-KB access in later retriever calls.
    """
    sq = _sq("Q1")
    scope_a = _scope()
    scope_b = _scope()
    plan = _plan("Q1")
    loop, pipeline, _ = _make_loop(
        round1_coverages=[_coverage(sq, CoverageStatus.UNSUPPORTED)],
        round2_coverages=[_coverage(sq, CoverageStatus.SUPPORTED)],
    )

    await loop.run(plan, scope_a, max_rounds=2)

    for i, call in enumerate(pipeline.run_all.call_args_list):
        actual_scope = call.args[1]
        assert actual_scope is not scope_b, f"run_all call {i} used the wrong scope"
        assert actual_scope is scope_a, f"run_all call {i} dropped the original scope"


# ---------------------------------------------------------------------------
# 3. MultiHopAnswerUseCase — scope threads through to every stage
# ---------------------------------------------------------------------------


def _make_answer_uc() -> tuple[MultiHopAnswerUseCase, AsyncMock, AsyncMock]:
    """Build a MultiHopAnswerUseCase with mocks; the scope comes from the command at call time."""
    plan = _plan("Q1")

    decompose = AsyncMock()
    decompose.execute = AsyncMock(return_value=plan)

    loop = AsyncMock(spec=IterativeRetrievalLoop)
    loop.run = AsyncMock(
        return_value=IterativeRetrievalResult(
            coverages=[_coverage(_sq("Q1"), CoverageStatus.SUPPORTED)],
            rounds_run=1,
        )
    )

    selector = MagicMock(spec=EvidenceSelector)
    selector.select = MagicMock(return_value=[
        SubQuestionEvidence(
            sub_question=_sq("Q1"), evidence=(), coverage=CoverageStatus.SUPPORTED
        )
    ])

    synthesizer = AsyncMock(spec=HierarchicalSynthesizer)
    synthesizer.synthesize = AsyncMock(
        return_value=MultiHopAnswer(answer="answer", sub_answers=())
    )

    uc = MultiHopAnswerUseCase(
        decompose=decompose,
        loop=loop,
        selector=selector,
        synthesizer=synthesizer,
    )
    return uc, decompose, loop


@pytest.mark.security
@pytest.mark.gate
async def test_answer_uc_scope_reaches_decomposer() -> None:
    """The scope from MultiHopAnswerCommand must reach the decomposer.

    A hardcoded or dropped scope here would decompose the query using the wrong
    knowledge base's context, then retrieve evidence from the wrong KB.
    """
    uc, decompose, _ = _make_answer_uc()
    scope = _scope()

    await uc.execute(MultiHopAnswerCommand(scope=scope, query="q"))

    call_cmd = decompose.execute.call_args.args[0]
    assert call_cmd.scope is scope


@pytest.mark.security
@pytest.mark.gate
async def test_answer_uc_scope_reaches_iterative_loop() -> None:
    """The scope from MultiHopAnswerCommand must reach the iterative retrieval loop.

    The loop's scope is the outermost gate: if it is wrong, every sub-question
    pipeline call — and the underlying SQL retrievers — would use the wrong scope.
    """
    uc, _, loop = _make_answer_uc()
    scope = _scope()

    await uc.execute(MultiHopAnswerCommand(scope=scope, query="q"))

    loop_scope = loop.run.call_args.args[1]
    assert loop_scope is scope


@pytest.mark.security
@pytest.mark.gate
async def test_answer_uc_different_scopes_produce_different_loop_calls() -> None:
    """The scope must not be hardcoded or cached inside MultiHopAnswerUseCase.

    Two commands with distinct scopes must each produce a loop.run() call with
    their own scope — verifying the use case threads the scope from the command
    rather than storing or defaulting it.
    """
    uc, _, loop = _make_answer_uc()
    scope_a = _scope()
    scope_b = _scope()

    await uc.execute(MultiHopAnswerCommand(scope=scope_a, query="q"))
    await uc.execute(MultiHopAnswerCommand(scope=scope_b, query="q"))

    first_scope = loop.run.call_args_list[0].args[1]
    second_scope = loop.run.call_args_list[1].args[1]
    assert first_scope is scope_a
    assert second_scope is scope_b
    assert first_scope is not second_scope
