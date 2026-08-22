"""Tests for RetrievalOrchestrator.

All collaborators are mocked. Tests verify the delegation contract at each stage:
classify → rewrite → plan → expand → embed + search concurrently → fuse → rerank.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing

from app.application.queries.retrieve_evidence import RetrievalOrchestrator, RetrieveEvidenceQuery
from app.domain.enums import MessageRole, QueryClass, RetrieverKind
from app.domain.models.entities import ConversationTurn
from app.domain.retrieval.entities import Evidence, EvidenceLabel, RetrievalFilters
from app.domain.retrieval.compression import EvidenceCompressor
from app.domain.retrieval.expansion import ExpansionRules
from app.domain.retrieval.pruning import EvidencePruner
from app.domain.retrieval.selector import EvidenceSelector
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_VECTOR = [0.1] * 384


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _evidence(rank: int = 0, text: str = "passage text") -> Evidence:
    chunk = MagicMock()
    chunk.text.value = text
    chunk.id = uuid.uuid4()
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=chunk,
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=rank,
    )


def _query(
    *,
    scope: ScopeContext | None = None,
    text: str = "what is photosynthesis",
    filters: RetrievalFilters | None = None,
    history: tuple[ConversationTurn, ...] = (),
) -> RetrieveEvidenceQuery:
    return RetrieveEvidenceQuery(
        scope=scope if scope is not None else _scope(),
        query=text,
        filters=filters if filters is not None else RetrievalFilters(),
        history=history,
    )


def _make_orchestrator(
    *,
    classify_return: QueryClass = QueryClass.DIRECT,
    rewrite_text: str = "the query",
    expand_return: list[str] | None = None,
    embed_return: list[float] | None = None,
    dense_results: list[Evidence] | None = None,
    keyword_results: list[Evidence] | None = None,
    fused_results: list[Evidence] | None = None,
    rerank_scores: list[float] | None = None,
    dense_top_k: int = 30,
    keyword_top_k: int = 30,
    candidate_pool_size: int = 50,
    max_rerank_candidates: int = 40,
    relative_score_margin: float = 0.35,
    max_items: int = 8,
    parents: list[object] | None = None,
) -> tuple[RetrievalOrchestrator, dict[str, MagicMock]]:
    classifier = MagicMock()
    classifier.classify.return_value = classify_return

    rewriter = MagicMock()
    rewriter.rewrite = AsyncMock(return_value=(rewrite_text, False))

    expander = MagicMock()
    expander.expand = AsyncMock(return_value=expand_return if expand_return is not None else [rewrite_text])

    embedder = MagicMock()
    embedder.embed_query = AsyncMock(return_value=embed_return or _VECTOR)

    dense_retriever = MagicMock()
    dense_retriever.search = AsyncMock(return_value=dense_results or [])

    keyword_retriever = MagicMock()
    keyword_retriever.search = AsyncMock(return_value=keyword_results or [])

    fuser = MagicMock()
    fuser.fuse.return_value = fused_results or []

    reranker = MagicMock()
    reranker.rerank = AsyncMock(return_value=rerank_scores or [])

    chunks = MagicMock()
    chunks.get_many = AsyncMock(return_value=parents or [])

    mocks: dict[str, MagicMock] = {
        "classifier": classifier,
        "rewriter": rewriter,
        "expander": expander,
        "embedder": embedder,
        "dense_retriever": dense_retriever,
        "keyword_retriever": keyword_retriever,
        "fuser": fuser,
        "reranker": reranker,
        "chunks": chunks,
    }

    orc = RetrievalOrchestrator(
        classifier=classifier,
        rewriter=rewriter,
        expander=expander,
        embedder=embedder,
        dense_retriever=dense_retriever,
        keyword_retriever=keyword_retriever,
        fuser=fuser,
        reranker=reranker,
        dense_top_k=dense_top_k,
        keyword_top_k=keyword_top_k,
        candidate_pool_size=candidate_pool_size,
        max_rerank_candidates=max_rerank_candidates,
        expansion_rules=ExpansionRules(),
        chunks=chunks,
        pruner=EvidencePruner(
            overlap_threshold=0.8,
            max_children_per_parent=99,
            max_chunks_per_page=99,
            max_chunks_per_document=99,
        ),
        compressor=EvidenceCompressor(
            lambda text: len(text.split()),
            token_budget=100_000,
        ),
        selector=EvidenceSelector(
            lambda text: len(text.split()),
            min_items=1,
            max_items=max_items,
            relative_score_margin=relative_score_margin,
            token_budget=10_000,
        ),
    )

    return orc, mocks


# ---------------------------------------------------------------------------
# Classify and rewrite
# ---------------------------------------------------------------------------


class TestClassifyAndRewrite:
    async def test_classifies_query_text(self) -> None:
        orc, mocks = _make_orchestrator()
        await orc.execute(_query(text="what is gradient descent"))
        mocks["classifier"].classify.assert_called_once_with("what is gradient descent")

    async def test_rewriter_receives_original_query_and_history(self) -> None:
        history = (ConversationTurn(role=MessageRole.USER, content=UntrustedText("prior")),)
        orc, mocks = _make_orchestrator()
        await orc.execute(_query(text="follow-up question", history=history))
        mocks["rewriter"].rewrite.assert_called_once_with("follow-up question", history)

    async def test_expander_receives_standalone_query_from_rewriter(self) -> None:
        orc, mocks = _make_orchestrator(rewrite_text="rewritten standalone")
        await orc.execute(_query(text="follow-up"))
        call_args = mocks["expander"].expand.call_args
        assert call_args.args[0] == "rewritten standalone"

    async def test_empty_history_passed_through_to_rewriter(self) -> None:
        orc, mocks = _make_orchestrator()
        await orc.execute(_query())
        mocks["rewriter"].rewrite.assert_called_once()
        assert mocks["rewriter"].rewrite.call_args.args[1] == ()


# ---------------------------------------------------------------------------
# Embed and search
# ---------------------------------------------------------------------------


class TestEmbedAndSearch:
    async def test_embed_called_once_for_single_query(self) -> None:
        orc, mocks = _make_orchestrator(expand_return=["q"])
        await orc.execute(_query())
        assert mocks["embedder"].embed_query.call_count == 1

    async def test_embed_called_for_each_expanded_query(self) -> None:
        orc, mocks = _make_orchestrator(expand_return=["q1", "q2"])
        await orc.execute(_query())
        assert mocks["embedder"].embed_query.call_count == 2
        queried = [c.args[0] for c in mocks["embedder"].embed_query.call_args_list]
        assert "q1" in queried
        assert "q2" in queried

    async def test_dense_search_called_once_per_expanded_query(self) -> None:
        orc, mocks = _make_orchestrator(expand_return=["q1", "q2"])
        await orc.execute(_query())
        assert mocks["dense_retriever"].search.call_count == 2

    async def test_keyword_search_called_once_per_expanded_query(self) -> None:
        orc, mocks = _make_orchestrator(expand_return=["q1", "q2"])
        await orc.execute(_query())
        assert mocks["keyword_retriever"].search.call_count == 2

    async def test_search_uses_scope_from_query(self) -> None:
        scope = _scope()
        orc, mocks = _make_orchestrator()
        await orc.execute(_query(scope=scope))
        assert mocks["dense_retriever"].search.call_args.args[0] is scope

    async def test_dense_search_uses_dense_top_k(self) -> None:
        orc, mocks = _make_orchestrator(dense_top_k=15)
        await orc.execute(_query())
        assert mocks["dense_retriever"].search.call_args.kwargs["top_k"] == 15

    async def test_keyword_search_uses_keyword_top_k(self) -> None:
        orc, mocks = _make_orchestrator(keyword_top_k=20)
        await orc.execute(_query())
        assert mocks["keyword_retriever"].search.call_args.kwargs["top_k"] == 20

    async def test_keyword_search_receives_expanded_query_text(self) -> None:
        orc, mocks = _make_orchestrator(expand_return=["expanded q"])
        await orc.execute(_query())
        assert mocks["keyword_retriever"].search.call_args.args[1] == "expanded q"


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


class TestFusion:
    async def test_fuser_receives_dense_and_keyword_results(self) -> None:
        dense_r = [_evidence(0)]
        kw_r = [_evidence(1)]
        orc, mocks = _make_orchestrator(
            expand_return=["q"],
            dense_results=dense_r,
            keyword_results=kw_r,
        )
        await orc.execute(_query())
        mocks["fuser"].fuse.assert_called_once_with(dense_r, kw_r)

    async def test_fuser_receives_results_for_each_expanded_query(self) -> None:
        dense_r = [_evidence(0)]
        kw_r = [_evidence(1)]
        orc, mocks = _make_orchestrator(
            expand_return=["q1", "q2"],
            dense_results=dense_r,
            keyword_results=kw_r,
        )
        await orc.execute(_query())
        call_args = mocks["fuser"].fuse.call_args
        # 2 expanded queries → 4 results: dense_0, kw_0, dense_1, kw_1
        assert len(call_args.args) == 4

    async def test_candidate_pool_cap_applied_after_fusion(self) -> None:
        # fuser returns 5 items, pool cap is 3 → only 3 reach the reranker
        fused = [_evidence(i, text=f"p{i}") for i in range(5)]
        scores = [0.9, 0.8, 0.7]
        orc, mocks = _make_orchestrator(
            fused_results=fused,
            rerank_scores=scores,
            candidate_pool_size=3,
            max_rerank_candidates=40,
        )
        await orc.execute(_query())
        texts_sent = [c.chunk.text.value for c in fused[:3]]
        rerank_texts = mocks["reranker"].rerank.call_args.args[1]
        assert list(rerank_texts) == texts_sent

    async def test_max_rerank_cap_applied_after_pool_cap(self) -> None:
        # pool=5, max_rerank=2 → only 2 reach the reranker
        fused = [_evidence(i, text=f"p{i}") for i in range(5)]
        orc, mocks = _make_orchestrator(
            fused_results=fused,
            rerank_scores=[0.9, 0.8],
            candidate_pool_size=50,
            max_rerank_candidates=2,
        )
        await orc.execute(_query())
        rerank_texts = mocks["reranker"].rerank.call_args.args[1]
        assert len(rerank_texts) == 2

    async def test_returns_empty_when_fuser_produces_no_candidates(self) -> None:
        orc, mocks = _make_orchestrator(fused_results=[])
        result = (await orc.execute(_query())).evidence
        assert list(result) == []
        mocks["reranker"].rerank.assert_not_called()


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


class TestReranking:
    async def test_reranker_called_with_standalone_query(self) -> None:
        ev = _evidence(0, text="passage")
        orc, mocks = _make_orchestrator(
            rewrite_text="standalone query",
            fused_results=[ev],
            rerank_scores=[0.9],
        )
        await orc.execute(_query())
        assert mocks["reranker"].rerank.call_args.args[0] == "standalone query"

    async def test_reranker_called_with_candidate_texts(self) -> None:
        ev1 = _evidence(0, text="passage A")
        ev2 = _evidence(1, text="passage B")
        orc, mocks = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[0.9, 0.6],
        )
        await orc.execute(_query())
        texts = mocks["reranker"].rerank.call_args.args[1]
        assert list(texts) == ["passage A", "passage B"]


# ---------------------------------------------------------------------------
# Scoring, filtering, and relabelling
# ---------------------------------------------------------------------------


class TestScoringAndFiltering:
    async def test_results_sorted_by_rerank_score_descending(self) -> None:
        ev1 = _evidence(0, text="A")
        ev2 = _evidence(1, text="B")
        ev3 = _evidence(2, text="C")
        # fused order: ev1, ev2, ev3; scores: 0.3, 0.9, 0.5 → sorted: ev2, ev3, ev1
        # margin=1.0 → threshold=0.0, so all positive scores pass. Classified broad,
        # because a direct question is deliberately answered with fewer passages than
        # this asserts the order of.
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2, ev3],
            rerank_scores=[0.3, 0.9, 0.5],
            relative_score_margin=1.0,
            classify_return=QueryClass.SUMMARY,
        )
        result = (await orc.execute(_query())).evidence
        assert result[0].rerank_score == pytest.approx(0.9)
        assert result[1].rerank_score == pytest.approx(0.5)
        assert result[2].rerank_score == pytest.approx(0.3)

    async def test_relative_margin_keeps_close_scores(self) -> None:
        ev1 = _evidence(0, text="top")
        ev2 = _evidence(1, text="close")
        # top=1.0, margin=0.5 → threshold=0.5; 0.6 >= 0.5 → kept
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[1.0, 0.6],
            relative_score_margin=0.5,
        )
        result = (await orc.execute(_query())).evidence
        assert len(result) == 2

    async def test_relative_margin_drops_distant_scores(self) -> None:
        ev1 = _evidence(0, text="top")
        ev2 = _evidence(1, text="distant")
        # top=1.0, margin=0.5 → threshold=0.5; 0.3 < 0.5 → dropped
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[1.0, 0.3],
            relative_score_margin=0.5,
        )
        result = (await orc.execute(_query())).evidence
        assert len(result) == 1
        assert result[0].rerank_score == pytest.approx(1.0)

    async def test_results_capped_by_the_selector(self) -> None:
        """The ceiling belongs to the selector now. The caller used to pass a count,
        which made every question the same size whatever it was asking for."""
        fused = [_evidence(i, text=f"p{i}") for i in range(5)]
        scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        orc, _ = _make_orchestrator(
            fused_results=fused,
            rerank_scores=scores,
            relative_score_margin=1.0,
            classify_return=QueryClass.SUMMARY,
            max_items=3,
        )
        result = (await orc.execute(_query())).evidence
        assert len(result) == 3

    async def test_results_relabelled_from_s1(self) -> None:
        ev1 = _evidence(0, text="top")
        ev2 = _evidence(1, text="second")
        # margin=1.0 → threshold=0.0, both pass
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[0.9, 0.7],
            relative_score_margin=1.0,
        )
        result = (await orc.execute(_query())).evidence
        assert result[0].label == EvidenceLabel(1)
        assert result[1].label == EvidenceLabel(2)

    async def test_rank_matches_position_in_output(self) -> None:
        ev1 = _evidence(0, text="top")
        ev2 = _evidence(1, text="second")
        # margin=1.0 → threshold=0.0, both pass
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[0.9, 0.7],
            relative_score_margin=1.0,
        )
        result = (await orc.execute(_query())).evidence
        assert result[0].rank == 0
        assert result[1].rank == 1

    async def test_rerank_score_set_on_returned_evidence(self) -> None:
        ev = _evidence(0, text="passage")
        orc, _ = _make_orchestrator(
            fused_results=[ev],
            rerank_scores=[0.75],
        )
        result = (await orc.execute(_query())).evidence
        assert result[0].rerank_score == pytest.approx(0.75)

    async def test_negative_scores_use_absolute_value_for_margin(self) -> None:
        ev1 = _evidence(0, text="top")
        ev2 = _evidence(1, text="close enough")
        # top=-10.0, margin=0.35 → threshold=-10.0 - 3.5 = -13.5
        # -12.0 >= -13.5 → kept
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[-10.0, -12.0],
            relative_score_margin=0.35,
        )
        result = (await orc.execute(_query())).evidence
        assert len(result) == 2

    async def test_single_candidate_always_passes_margin_filter(self) -> None:
        ev = _evidence(0, text="only passage")
        orc, _ = _make_orchestrator(
            fused_results=[ev],
            rerank_scores=[0.5],
            relative_score_margin=0.99,
        )
        result = (await orc.execute(_query())).evidence
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Stage timing logs
# ---------------------------------------------------------------------------


class TestStageTimingLogs:
    _STAGES = (
        "classify",
        "rewrite",
        "plan_expand",
        "embed",
        "search",
        "fuse",
        "rerank",
        "prune",
        "expand_parents",
        "select",
        "compress",
    )

    async def test_every_stage_emits_a_retrieval_stage_event(self) -> None:
        ev = _evidence(0, text="passage")
        orc, _ = _make_orchestrator(fused_results=[ev], rerank_scores=[0.9])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        stage_names = {e["stage"] for e in logs if e.get("event") == "retrieval_stage"}
        assert stage_names == set(self._STAGES)

    async def test_each_event_carries_elapsed_ms_as_int(self) -> None:
        ev = _evidence(0, text="passage")
        orc, _ = _make_orchestrator(fused_results=[ev], rerank_scores=[0.9])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        timing_events = [e for e in logs if e.get("event") == "retrieval_stage"]
        for event in timing_events:
            assert isinstance(event["elapsed_ms"], int), f"stage={event['stage']}"

    async def test_each_elapsed_ms_is_non_negative(self) -> None:
        ev = _evidence(0, text="passage")
        orc, _ = _make_orchestrator(fused_results=[ev], rerank_scores=[0.9])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        timing_events = [e for e in logs if e.get("event") == "retrieval_stage"]
        for event in timing_events:
            assert event["elapsed_ms"] >= 0, f"stage={event['stage']}"

    async def test_no_rerank_event_when_candidates_empty(self) -> None:
        orc, _ = _make_orchestrator(fused_results=[])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        stage_names = {e["stage"] for e in logs if e.get("event") == "retrieval_stage"}
        assert "rerank" not in stage_names

    async def test_fuse_event_includes_candidate_count(self) -> None:
        ev1 = _evidence(0, text="a")
        ev2 = _evidence(1, text="b")
        orc, _ = _make_orchestrator(fused_results=[ev1, ev2], rerank_scores=[0.9, 0.7])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        fuse_event = next(
            e for e in logs if e.get("event") == "retrieval_stage" and e["stage"] == "fuse"
        )
        assert fuse_event["candidates"] == 2

    async def test_plan_expand_event_includes_query_count(self) -> None:
        orc, _ = _make_orchestrator(expand_return=["q1", "q2"])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        event = next(
            e
            for e in logs
            if e.get("event") == "retrieval_stage" and e["stage"] == "plan_expand"
        )
        assert event["queries"] == 2

    async def test_search_event_includes_searcher_count(self) -> None:
        # 2 expanded queries → 4 search tasks (2 dense + 2 keyword)
        orc, _ = _make_orchestrator(expand_return=["q1", "q2"])
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        event = next(
            e for e in logs if e.get("event") == "retrieval_stage" and e["stage"] == "search"
        )
        assert event["searchers"] == 4

    async def test_rerank_event_includes_results_count(self) -> None:
        ev1 = _evidence(0, text="a")
        ev2 = _evidence(1, text="b")
        orc, _ = _make_orchestrator(
            fused_results=[ev1, ev2],
            rerank_scores=[0.9, 0.7],
            relative_score_margin=1.0,
        )
        with structlog.testing.capture_logs() as logs:
            await orc.execute(_query())
        event = next(
            e for e in logs if e.get("event") == "retrieval_stage" and e["stage"] == "rerank"
        )
        assert event["results"] == 2


# ---------------------------------------------------------------------------
# Parent expansion
# ---------------------------------------------------------------------------


def _real_chunk(text: str, *, parent_id: uuid.UUID | None, chunk_id: uuid.UUID | None = None):
    from datetime import UTC, datetime

    from app.domain.documents.chunks import Chunk
    from app.domain.enums import ChunkType

    return Chunk(
        id=chunk_id if chunk_id is not None else uuid.uuid4(),
        user_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        parent_chunk_id=parent_id,
        chunk_type=ChunkType.TEXT,
        text=UntrustedText(text),
        token_count=max(1, len(text.split())),
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
    )


def _real_evidence(text: str, *, parent_id: uuid.UUID | None, rank: int = 0) -> Evidence:
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=_real_chunk(text, parent_id=parent_id),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=rank,
    )


_NEEDS_ITS_SECTION = "This means the gradient vanishes before it reaches the input layer."
_STANDS_ALONE = "Backpropagation computes the gradient of the loss for every weight."


class TestParentExpansion:
    async def test_an_incomplete_fragment_is_replaced_by_its_section(self) -> None:
        """The fragment matched the query and cannot be read on its own, because what it
        points at was cut into a different chunk."""
        parent_id = uuid.uuid4()
        parent = _real_chunk("The whole section, several paragraphs of it.",
                             parent_id=None, chunk_id=parent_id)
        orc, _mocks = _make_orchestrator(
            fused_results=[_real_evidence(_NEEDS_ITS_SECTION, parent_id=parent_id)],
            rerank_scores=[0.9],
            parents=[parent],
        )
        result = (await orc.execute(_query())).evidence

        assert result[0].chunk.id == parent_id
        assert result[0].parent_expanded is True

    async def test_a_self_contained_fragment_is_left_as_it_was(self) -> None:
        """Replacing it would spend several times its size in budget to say the same
        thing less precisely."""
        chunk_id, parent_id = uuid.uuid4(), uuid.uuid4()
        evidence = Evidence(
            label=EvidenceLabel(1),
            chunk=_real_chunk(_STANDS_ALONE, parent_id=parent_id, chunk_id=chunk_id),
            retrievers=frozenset({RetrieverKind.DENSE}),
        )
        # The parent is available, so the fragment surviving means the rules declined
        # to expand it rather than that there was nothing to expand into.
        orc, _mocks = _make_orchestrator(
            fused_results=[evidence],
            rerank_scores=[0.9],
            parents=[_real_chunk("the whole section", parent_id=None, chunk_id=parent_id)],
        )
        result = (await orc.execute(_query())).evidence

        assert result[0].chunk.id == chunk_id
        assert result[0].parent_expanded is False

    async def test_nothing_incomplete_means_no_query_at_all(self) -> None:
        orc, mocks = _make_orchestrator(
            fused_results=[_real_evidence(_STANDS_ALONE, parent_id=uuid.uuid4())],
            rerank_scores=[0.9],
        )
        await orc.execute(_query())
        mocks["chunks"].get_many.assert_not_called()

    async def test_every_parent_is_loaded_in_one_query(self) -> None:
        """This runs while somebody waits, so a round trip per fragment would put the
        database inside that wait once per passage."""
        first, second = uuid.uuid4(), uuid.uuid4()
        orc, mocks = _make_orchestrator(
            classify_return=QueryClass.SUMMARY,
            fused_results=[
                _real_evidence(_NEEDS_ITS_SECTION, parent_id=first, rank=0),
                _real_evidence("However, the loss stops falling entirely.",
                               parent_id=second, rank=1),
            ],
            rerank_scores=[0.9, 0.8],
            relative_score_margin=1.0,
            parents=[
                _real_chunk("first section", parent_id=None, chunk_id=first),
                _real_chunk("second section", parent_id=None, chunk_id=second),
            ],
        )
        await orc.execute(_query())
        mocks["chunks"].get_many.assert_called_once()

    async def test_two_fragments_of_one_section_do_not_both_become_it(self) -> None:
        """The second would be a copy of the first, which is the repetition the step
        before this one exists to remove — arriving after it has finished looking."""
        parent_id = uuid.uuid4()
        orc, _ = _make_orchestrator(
            classify_return=QueryClass.SUMMARY,
            fused_results=[
                _real_evidence(_NEEDS_ITS_SECTION, parent_id=parent_id, rank=0),
                _real_evidence("However, the loss stops falling.", parent_id=parent_id, rank=1),
            ],
            rerank_scores=[0.9, 0.8],
            relative_score_margin=1.0,
            parents=[_real_chunk("the section", parent_id=None, chunk_id=parent_id)],
        )
        result = (await orc.execute(_query())).evidence

        expanded = [e for e in result if e.parent_expanded]
        assert len(expanded) == 1
        assert len({e.chunk.id for e in result}) == len(result)

    async def test_a_missing_parent_leaves_the_fragment_alone(self) -> None:
        """Deleted, or belonging to another scope. Incomplete is better than absent."""
        orc, _ = _make_orchestrator(
            fused_results=[_real_evidence(_NEEDS_ITS_SECTION, parent_id=uuid.uuid4())],
            rerank_scores=[0.9],
            parents=[],
        )
        result = (await orc.execute(_query())).evidence

        assert len(result) == 1
        assert result[0].parent_expanded is False

    async def test_the_load_is_scoped_to_the_caller(self) -> None:
        scope = _scope()
        parent_id = uuid.uuid4()
        orc, mocks = _make_orchestrator(
            fused_results=[_real_evidence(_NEEDS_ITS_SECTION, parent_id=parent_id)],
            rerank_scores=[0.9],
            parents=[_real_chunk("the section", parent_id=None, chunk_id=parent_id)],
        )
        await orc.execute(_query(scope=scope))
        assert mocks["chunks"].get_many.call_args.args[0] == scope
