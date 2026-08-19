"""Deterministic validators that check model responses before any semantic pass.

These run without a model call and without database access. They examine facts that can
be established by inspection of the response itself and the evidence set that was sent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import Claim, GeneratedAnswer


@dataclass(frozen=True, slots=True)
class CitationCheckResult:
    """Outcome of checking one claim's citations against the evidence that was sent.

    A label in `fabricated_labels` was cited by the model but was never in the evidence
    sent to it. The model invented that reference — it cannot have read the passage it is
    claiming as a source.
    """

    claim: Claim
    fabricated_labels: frozenset[str]

    @property
    def has_fabricated_citations(self) -> bool:
        return bool(self.fabricated_labels)


def check_citation_existence(
    answer: GeneratedAnswer,
    evidence: Sequence[LabeledPassage],
) -> tuple[CitationCheckResult, ...]:
    """Return one CitationCheckResult per claim, identifying any fabricated labels.

    A label is fabricated if it does not match any passage that was sent to the model.
    The check runs against the evidence set the model actually received, not against the
    full knowledge base — a passage retrieved but then shed by the context builder before
    the prompt was built counts as unseen, because the model could not have read it.

    If the answer flagged insufficient evidence, `answer.claims` is empty and this
    function returns an empty tuple.
    """
    known_labels = frozenset(p.label for p in evidence)
    return tuple(
        CitationCheckResult(
            claim=claim,
            fabricated_labels=frozenset(
                label for label in claim.citations if label not in known_labels
            ),
        )
        for claim in answer.claims
    )
