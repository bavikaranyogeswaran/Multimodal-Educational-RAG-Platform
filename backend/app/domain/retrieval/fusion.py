"""Reciprocal Rank Fusion over Evidence lists from independent retrievers.

RRF score for a chunk: Σ 1 / (k + rank_i) for every ranked list in which it
appears, where k=60 is the smoothing constant that suppresses variance at the
very top of each list. Chunks found by more than one retriever benefit from
multiple additive contributions; the merged Evidence records the union of the
retriever kinds so provenance stays complete.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.domain.retrieval.entities import Evidence, EvidenceLabel

_K = 60


class RRFusion:
    """Merge and re-rank Evidence from multiple retrievers with Reciprocal Rank Fusion.

    Accepts any number of pre-ranked lists. Each list must already be sorted in
    retriever-preference order with 0-based `rank` values (best rank = 0).
    Returns a single list sorted by fusion score descending, with labels and
    ranks re-assigned from position zero.
    """

    def fuse(self, *ranked_lists: Sequence[Evidence]) -> list[Evidence]:
        scores: dict[UUID, float] = {}
        merged: dict[UUID, Evidence] = {}

        for ranked_list in ranked_lists:
            for evidence in ranked_list:
                chunk_id = evidence.chunk.id
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_K + evidence.rank)
                if chunk_id in merged:
                    existing = merged[chunk_id]
                    merged[chunk_id] = replace(
                        existing,
                        retrievers=existing.retrievers | evidence.retrievers,
                    )
                else:
                    merged[chunk_id] = evidence

        ordered = sorted(merged, key=lambda cid: scores[cid], reverse=True)

        return [
            replace(
                merged[cid],
                label=EvidenceLabel(rank + 1),
                rank=rank,
                fusion_score=scores[cid],
            )
            for rank, cid in enumerate(ordered)
        ]
