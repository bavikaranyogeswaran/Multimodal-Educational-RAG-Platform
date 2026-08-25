"""What a retrieval run scored against the pages that answer the question.

Four numbers, because they fail differently and a single one hides which happened:

  - **Page recall** asks whether retrieval reached everywhere the answer lives. A
    procedure spread over three pages that returns two of them produces an answer that
    is right about the beginning and silent about the end.
  - **Precision** asks how much of what came back was worth the room it took. Every
    irrelevant passage in the prompt is one the model may answer from, and evidence is
    budgeted — a wrong passage displaces a right one.
  - **Reciprocal rank** asks how far down the first useful result was. The selector stops
    at a score margin, so a relevant passage ranked eighth is often a passage that never
    reaches the prompt at all.
  - **NDCG** asks whether the ordering was any good, which the other three do not: two
    runs returning the same passages in opposite orders score identically on recall and
    precision.

Relevance is judged per retrieved passage, by whether its page range touches a gold
page. Recall is measured over pages rather than passages, because what matters is
whether every part of the answer was reached, not how many passages did the reaching —
one chunk covering three gold pages has found the whole answer, and three chunks
covering one page between them have not.

Everything here takes plain page numbers. Nothing imports a chunk, an Evidence or a
repository, so these can be checked against values worked out by hand.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import log2

from app.domain.errors import InvariantViolationError

#: One retrieved passage, as the pages it covers. A passage spanning a page break covers
#: both; a figure covers the one it was cropped from.
RetrievedPages = Collection[int]


def _require_k(k: int) -> None:
    if k < 1:
        raise InvariantViolationError(f"k must be at least 1, got {k}")


def _is_relevant(pages: RetrievedPages, gold: Collection[int]) -> bool:
    return bool(set(pages) & set(gold))


def page_recall_at_k(
    retrieved: Sequence[RetrievedPages], gold: Collection[int], *, k: int
) -> float:
    """Fraction of the gold pages the top k passages reached between them.

    1.0 means every page the answer needs was in front of the model. Anything less is a
    partial answer waiting to happen, and the model will not say which part is missing.
    """
    _require_k(k)
    if not gold:
        raise InvariantViolationError("page recall is undefined with no gold pages")
    reached: set[int] = set()
    for pages in retrieved[:k]:
        reached |= set(pages)
    return len(reached & set(gold)) / len(set(gold))


def precision_at_k(retrieved: Sequence[RetrievedPages], gold: Collection[int], *, k: int) -> float:
    """Fraction of the top k passages that touched a gold page.

    Divided by k rather than by how many passages came back, which is the standard
    definition and the one that matters here: retrieval asked for k slots, and the ones
    it left empty are as much a part of the result as the ones it filled.
    """
    _require_k(k)
    window = retrieved[:k]
    if not window:
        return 0.0
    return sum(1 for pages in window if _is_relevant(pages, gold)) / k


def reciprocal_rank(retrieved: Sequence[RetrievedPages], gold: Collection[int]) -> float:
    """One over the position of the first relevant passage, or zero if there is none.

    Ranks count from one, so a relevant passage at the top scores 1.0 and one in fifth
    place scores 0.2. Averaged over a set this is MRR.
    """
    for position, pages in enumerate(retrieved, start=1):
        if _is_relevant(pages, gold):
            return 1.0 / position
    return 0.0


def ndcg_at_k(retrieved: Sequence[RetrievedPages], gold: Collection[int], *, k: int) -> float:
    """Ranking quality against the best ordering the same results could have had.

    Relevance is binary — a passage either touches a gold page or does not — so the ideal
    ordering is every relevant passage first. Normalised against that rather than against
    a perfect run, which is what makes it comparable between questions that have
    different numbers of right answers.

    Zero relevant passages scores 0.0 rather than dividing by zero: nothing was found, and
    no ordering of nothing is better than another.
    """
    _require_k(k)
    window = retrieved[:k]
    gains = [1.0 if _is_relevant(pages, gold) else 0.0 for pages in window]
    ideal = sorted(gains, reverse=True)

    def _dcg(values: Sequence[float]) -> float:
        # Positions are 1-based and the discount is log2(position + 1), so the first
        # result is undiscounted and each one after it counts for less.
        return sum(gain / log2(position + 1) for position, gain in enumerate(values, start=1))

    best = _dcg(ideal)
    return _dcg(gains) / best if best else 0.0


def phrases_found(retrieved_text: Sequence[str], must_contain: Collection[str]) -> float:
    """Fraction of the required phrases appearing anywhere in the retrieved text.

    Pages say where to look; this says whether the particular thing worth finding was
    actually there. A page holding both a definition and an example satisfies a page
    check either way, and only this can tell the two apart.

    Matched case-insensitively and without regard to which passage carried it, because
    the question is whether the model saw the phrase, not how it was delivered.
    """
    if not must_contain:
        return 1.0
    haystack = "\n".join(retrieved_text).lower()
    return sum(1 for phrase in must_contain if phrase.lower() in haystack) / len(must_contain)


@dataclass(frozen=True)
class RetrievalScores:
    """One question's scores, kept together so a run can be compared line by line."""

    k: int
    page_recall: float
    precision: float
    reciprocal_rank: float
    ndcg: float
    phrases: float

    #: How many passages actually came back, which is the context the rest needs: a
    #: precision of 0.2 over five slots and over fifty are different results.
    returned: int


def score(
    retrieved: Sequence[RetrievedPages],
    gold: Collection[int],
    *,
    k: int,
    retrieved_text: Sequence[str] = (),
    must_contain: Collection[str] = (),
) -> RetrievalScores:
    """Every metric for one question, from one retrieval run."""
    return RetrievalScores(
        k=k,
        page_recall=page_recall_at_k(retrieved, gold, k=k),
        precision=precision_at_k(retrieved, gold, k=k),
        reciprocal_rank=reciprocal_rank(retrieved, gold),
        ndcg=ndcg_at_k(retrieved, gold, k=k),
        phrases=phrases_found(retrieved_text, must_contain),
        returned=len(retrieved),
    )
