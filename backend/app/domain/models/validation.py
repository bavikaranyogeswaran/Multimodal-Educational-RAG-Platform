"""Validators for grounded model responses.

The deterministic layer runs first — no model call, no database access — checking facts
that can be established by inspection of the response and the evidence set that was sent.
The semantic layer follows: it calls the model once per (claim, cited passage) pair to
judge whether the passage actually supports what the claim asserts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.enums import ClaimStatus, ValidationDecision
from app.domain.errors import GenerationParseError
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


@dataclass(frozen=True, slots=True)
class EntailmentResult:
    """Outcome of checking one (claim, passage) pair for semantic support.

    The claim's text was checked against the single passage named by `passage_label`.
    A claim with multiple citations produces one EntailmentResult per citation, and
    `aggregate_claim_status` collapses them into a single ClaimStatus.
    """

    claim: Claim
    passage_label: str
    status: ClaimStatus


#: System preamble for the entailment check prompt. Kept here so the port and the
#: infrastructure adapter share the same text without either importing the other.
ENTAILMENT_PREAMBLE = (
    "You are a precise fact-checker. Given a factual claim and a single reference "
    "passage, judge whether the passage supports, contradicts, or does not address "
    "the claim."
)

#: Output schema for the entailment check — one word from a closed set.
ENTAILMENT_SCHEMA = """\
Respond with exactly one word: ENTAILED, CONTRADICTED, or NOT_SUPPORTED.

- ENTAILED: the passage directly states or clearly implies the claim is true.
- CONTRADICTED: the passage directly states or clearly implies the claim is false.
- NOT_SUPPORTED: the passage does not address the claim at all.

No explanation, no punctuation, no extra words — only the single word."""


def parse_entailment_status(raw: str) -> ClaimStatus:
    """Map the model's one-word response to a ClaimStatus.

    Strips whitespace and normalises case so minor formatting variations do not
    cause parse failures. Raises GenerationParseError for any unrecognised value.
    """
    normalised = raw.strip().upper()
    _map: dict[str, ClaimStatus] = {
        "ENTAILED": ClaimStatus.ENTAILED,
        "CONTRADICTED": ClaimStatus.CONTRADICTED,
        "NOT_SUPPORTED": ClaimStatus.NOT_SUPPORTED,
    }
    status = _map.get(normalised)
    if status is None:
        raise GenerationParseError(
            f"expected ENTAILED, CONTRADICTED, or NOT_SUPPORTED; got {raw!r}"
        )
    return status


def aggregate_claim_status(results: Sequence[EntailmentResult]) -> ClaimStatus:
    """Collapse per-passage results for one claim into a single ClaimStatus.

    ENTAILED when at least one cited passage directly supports the claim. Without
    any support, CONTRADICTED when at least one cited passage directly opposes it.
    NOT_SUPPORTED when nothing cited addresses the claim at all.

    An empty sequence — which arises when the citation existence check removed
    all passages before the semantic check ran — returns NOT_SUPPORTED.
    """
    if not results:
        return ClaimStatus.NOT_SUPPORTED
    statuses = {r.status for r in results}
    if ClaimStatus.ENTAILED in statuses:
        return ClaimStatus.ENTAILED
    if ClaimStatus.CONTRADICTED in statuses:
        return ClaimStatus.CONTRADICTED
    return ClaimStatus.NOT_SUPPORTED


def decide(
    answer: GeneratedAnswer,
    citation_results: tuple[CitationCheckResult, ...],
    entailment_by_claim: Sequence[Sequence[EntailmentResult]],
) -> ValidationDecision:
    """Collapse citation and entailment results into a single action for the answer.

    Pairs each CitationCheckResult with the entailment results for the same claim
    (by position). A claim is rejected when all its citations are fabricated — there
    is no real evidence to point to — or when the evidence actively contradicts it.
    A claim is repairable when some citations are fabricated but real ones remain, or
    when the evidence does not address it but does not refute it either.
    """
    if answer.insufficient_evidence:
        return ValidationDecision.INSUFFICIENT_EVIDENCE

    rejected = False
    repairable = False

    for check, ent_results in zip(citation_results, entailment_by_claim, strict=True):
        real_citations = frozenset(check.claim.citations) - check.fabricated_labels
        if not real_citations:
            rejected = True
            continue

        if check.has_fabricated_citations:
            repairable = True

        status = aggregate_claim_status(ent_results)
        if status is ClaimStatus.CONTRADICTED:
            rejected = True
        elif status is ClaimStatus.NOT_SUPPORTED:
            repairable = True

    if rejected:
        return ValidationDecision.REJECTED
    if repairable:
        return ValidationDecision.REPAIRABLE
    return ValidationDecision.VALID


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
