"""Document-level scoring and selection for multi-hop retrieval.

After the first retrieval pass, evidence is distributed across documents unevenly.
DocumentSelector identifies which documents actually cover the sub-questions and
picks the most relevant ones. Subsequent retrieval rounds are restricted to that
selected set via RetrievalFilters(document_ids=selection.selected_ids), keeping
later passes focused rather than re-searching the whole corpus.

Scoring is a two-key sort:
  1. sub_questions_covered — how many distinct sub-questions have any evidence
     from this document. A document that contributes to three sub-questions is
     categorically more valuable than one that contributes to one.
  2. total_rerank_score — sum of rerank_score for all evidence chunks from this
     document. Breaks ties when two documents cover the same number of sub-questions.
     Evidence with rerank_score=None (not yet reranked) contributes 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.queries.sub_question_pipeline import SubQuestionResult


@dataclass(frozen=True, slots=True)
class DocumentScore:
    """Coverage metrics for one document across all sub-questions."""

    document_id: UUID
    sub_questions_covered: int
    total_rerank_score: float


@dataclass(frozen=True, slots=True)
class DocumentSelection:
    """The outcome of a document selection pass.

    `selected_ids` is the working set for the next retrieval round.
    `scores` holds the full ranking (not just the selected top-N) so callers
    can inspect why documents were included or excluded without re-computing.
    """

    selected_ids: frozenset[UUID]
    scores: tuple[DocumentScore, ...]


class DocumentSelector:
    """Score every document that appeared in any sub-question result and keep the best.

    `max_documents` caps how many are selected. The cap is applied after sorting,
    so the N documents with the broadest sub-question coverage (and highest rerank
    scores as a tiebreaker) always win.
    """

    def __init__(self, max_documents: int) -> None:
        if max_documents < 1:
            raise ValueError(f"max_documents must be at least 1, got {max_documents}")
        self._max_documents = max_documents

    def select(self, results: list[SubQuestionResult]) -> DocumentSelection:
        """Aggregate evidence by document and return the top-N by coverage score."""
        doc_sub_questions: dict[UUID, set[str]] = {}
        doc_total_score: dict[UUID, float] = {}

        for sq_result in results:
            sq_id = sq_result.sub_question.id
            for ev in sq_result.evidence:
                doc_id = ev.document_id
                doc_sub_questions.setdefault(doc_id, set()).add(sq_id)
                doc_total_score[doc_id] = (
                    doc_total_score.get(doc_id, 0.0) + (ev.rerank_score or 0.0)
                )

        all_scores = [
            DocumentScore(
                document_id=doc_id,
                sub_questions_covered=len(sq_ids),
                total_rerank_score=doc_total_score[doc_id],
            )
            for doc_id, sq_ids in doc_sub_questions.items()
        ]

        ranked = sorted(
            all_scores,
            key=lambda s: (-s.sub_questions_covered, -s.total_rerank_score),
        )

        selected = ranked[: self._max_documents]
        return DocumentSelection(
            selected_ids=frozenset(s.document_id for s in selected),
            scores=tuple(ranked),
        )
