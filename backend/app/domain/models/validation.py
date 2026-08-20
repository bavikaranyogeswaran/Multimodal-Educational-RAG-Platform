"""Validators for grounded model responses.

The deterministic layer runs first — no model call, no database access — checking facts
that can be established by inspection of the response and the evidence set that was sent.
The semantic layer follows: it calls the model once per (claim, cited passage) pair to
judge whether the passage actually supports what the claim asserts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.enums import AnswerFidelity, ClaimStatus, ValidationDecision
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


#: System preamble for the faithfulness check. The comparison is answer-against-claims,
#: never answer-against-passages: the claims have already been checked against the
#: passages one by one, so an answer covered by its claims is covered by the evidence
#: transitively — and asking about whole prose against a single passage would call
#: ordinary connective writing unsupported.
FIDELITY_PREAMBLE = (
    "You are a precise editor. Given an answer and the list of claims it is built from, "
    "judge whether the answer states any fact that none of the claims covers."
)

FIDELITY_SCHEMA = """\
Respond with exactly one word: FAITHFUL or OVERSTATED.

- FAITHFUL: every fact the answer states is covered by at least one claim. Wording may
  differ, and connective or explanatory phrasing that asserts nothing new is fine.
- OVERSTATED: the answer states at least one fact that no claim covers — a figure, a
  name, a mechanism, a consequence, or a qualifier that appears nowhere in the claims.

Judge only what the answer asserts as fact. No explanation, no punctuation, only the
single word."""


def build_fidelity_query(answer: GeneratedAnswer) -> str:
    """The answer and its claims, side by side, for the faithfulness check.

    Claims are numbered so the model is comparing against a list rather than a paragraph,
    which is the same reason the turn's requirements are numbered in the prompt.
    """
    claims = "\n".join(f"{n}. {claim.text}" for n, claim in enumerate(answer.claims, start=1))
    return f"Answer:\n{answer.answer}\n\nClaims:\n{claims}"


def parse_fidelity(raw: str) -> AnswerFidelity:
    """Map the model's one-word response to an AnswerFidelity.

    Strips whitespace and normalises case, as the entailment parser does. An
    unrecognised value is a parse failure rather than a guess.
    """
    normalised = raw.strip().upper()
    _map: dict[str, AnswerFidelity] = {
        "FAITHFUL": AnswerFidelity.FAITHFUL,
        "OVERSTATED": AnswerFidelity.OVERSTATED,
    }
    fidelity = _map.get(normalised)
    if fidelity is None:
        raise GenerationParseError(f"expected FAITHFUL or OVERSTATED; got {raw!r}")
    return fidelity


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
    fidelity: AnswerFidelity | None = None,
) -> ValidationDecision:
    """Collapse citation, entailment and faithfulness results into a single action.

    Pairs each CitationCheckResult with the entailment results for the same claim
    (by position). A claim is rejected when all its citations are fabricated — there
    is no real evidence to point to — or when the evidence actively contradicts it.
    A claim is repairable when some citations are fabricated but real ones remain, or
    when the evidence does not address it but does not refute it either.

    `fidelity` is optional because the check costs a model call and is worth skipping
    once the claims alone have already settled the outcome. `None` means it was not run
    and contributes nothing — never that the answer passed it.
    """
    if answer.insufficient_evidence:
        return ValidationDecision.INSUFFICIENT_EVIDENCE

    rejected = False
    # An answer that overstates its claims is repairable rather than rejected: the
    # evidence is sound and nothing was invented, so the fix is to rewrite the prose to
    # match what was actually established, which is a thing a second attempt can do.
    repairable = fidelity is AnswerFidelity.OVERSTATED

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


def build_repair_instructions(
    citation_results: tuple[CitationCheckResult, ...],
    entailment_by_claim: Sequence[Sequence[EntailmentResult]],
    fidelity: AnswerFidelity | None = None,
) -> str:
    """Return a feedback string the model can act on when revising its answer.

    Called only when the previous decide() returned REPAIRABLE. Each bullet
    names the exact claim and the specific problem so the model can fix it
    rather than guessing. Returns an empty string when there is nothing to
    report, though callers should only invoke this function when issues exist.
    """
    bullets: list[str] = []

    for check, ent_results in zip(citation_results, entailment_by_claim, strict=True):
        if check.has_fabricated_citations:
            labels = ", ".join(sorted(check.fabricated_labels))
            verb = "do" if len(check.fabricated_labels) > 1 else "does"
            bullets.append(
                f'Claim "{check.claim.text}" cited {labels}, which {verb} not appear '
                "in the reference passages. Use only the labels shown beside each passage."
            )

        status = aggregate_claim_status(ent_results)
        if status is ClaimStatus.NOT_SUPPORTED:
            bullets.append(
                f'Claim "{check.claim.text}" is not supported by any passage it cites. '
                "Either cite a passage that actually contains this information, "
                "or remove the claim entirely."
            )

    if fidelity is AnswerFidelity.OVERSTATED:
        bullets.append(
            "Your answer states something none of your claims covers. Either rewrite the "
            "answer so it says only what the claims establish, or add a claim — with "
            "citations — for the statement you want to keep."
        )

    if not bullets:
        return ""

    return (
        "Your previous answer requires correction. "
        "Revise it to address all of the following:\n"
        + "\n".join(f"- {b}" for b in bullets)
    )


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
