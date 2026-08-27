"""Validators for grounded model responses.

The deterministic layer runs first — no model call, no database access — checking facts
that can be established by inspection of the response and the evidence set that was sent.
The semantic layer follows: it calls the model once per (claim, cited passage) pair to
judge whether the passage actually supports what the claim asserts.
"""

from __future__ import annotations

import re
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
class NumericCheckResult:
    """Outcome of checking one claim's figures against the passages it cites.

    A number in `unsupported_numbers` appears in the claim but in none of the passages the
    claim rests on. It was invented, rounded, converted or computed — all four are the same
    failure from here, because the requirement is that a figure survives into the answer as
    the source wrote it.

    Entailment does not catch this. A model that reads "rose from 100 to 150" and writes
    "rose by 50%" is saying something the passage supports, so the claim is entailed; the
    figure is still one the student cannot find when they follow the citation.
    """

    claim: Claim
    unsupported_numbers: tuple[str, ...]

    @property
    def has_unsupported_numbers(self) -> bool:
        return bool(self.unsupported_numbers)


@dataclass(frozen=True, slots=True)
class LengthCheckResult:
    """Outcome of checking the answer prose length against configured limits.

    Uses a character-based token estimate (character count // 4) rather than a tokenizer,
    keeping the check purely deterministic and free of model calls or external weights.
    """

    word_count: int
    estimated_tokens: int
    max_words: int
    max_tokens: int

    @property
    def exceeds_word_limit(self) -> bool:
        return self.word_count > self.max_words

    @property
    def exceeds_token_limit(self) -> bool:
        return self.estimated_tokens > self.max_tokens

    @property
    def is_too_long(self) -> bool:
        return self.exceeds_word_limit or self.exceeds_token_limit


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
    numeric_results: Sequence[NumericCheckResult] = (),
    length_result: LengthCheckResult | None = None,
) -> ValidationDecision:
    """Collapse citation, entailment, faithfulness and figure results into one action.

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
    # A figure the passages do not contain is repairable for the same reason — the right
    # number is sitting in the evidence, and the model can be told to use it.
    repairable = (
        (length_result is not None and length_result.is_too_long)
        or fidelity is AnswerFidelity.OVERSTATED
        or any(result.has_unsupported_numbers for result in numeric_results)
    )

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


def build_partial_answer(
    citation_results: Sequence[CitationCheckResult],
    entailment_by_claim: Sequence[Sequence[EntailmentResult]],
    numeric_results: Sequence[NumericCheckResult],
) -> GeneratedAnswer | None:
    """Keep the part of an answer the evidence carries, and say what was dropped.

    Called when a repair has already been spent and claims are still unsupported. The
    alternative at that point is refusing the whole answer, which is the worse outcome for
    a student who asked something the material half covers: they learn nothing, including
    the fact that half of it was answerable.

    The prose is rebuilt from the surviving claims rather than kept from the model, because
    the model wrote it to carry every claim it made. Dropping claims underneath it would
    leave prose asserting what no longer stands — which is exactly what the faithfulness
    check exists to catch, and it would be this function that introduced it. The original
    answer is therefore not a parameter: nothing in it survives.

    A claim survives only if it passes everything: entailed by a passage it cites, citing
    nothing invented, and quoting no figure the passages do not contain. Salvage is the one
    path that returns an answer nobody re-validated, so it has to apply the same bar the
    validators did rather than a looser one — a claim let through here is a claim shown to
    a student without a check behind it.

    A fabricated citation disqualifies its claim even when another passage happens to
    support it. The model invented a source; keeping the claim would ship something built
    on that invention, and the gate on fabricated citations is meant to hold at zero.

    Returns `None` when there is nothing to salvage: no claim survived, or the evidence
    actively contradicted one. A contradiction is not a gap. It means the model misread
    the material, and answering around it would present the rest as though the misreading
    had not happened.
    """
    kept: list[Claim] = []
    dropped: list[str] = []

    for check, ent_results, numeric in zip(
        citation_results, entailment_by_claim, numeric_results, strict=True
    ):
        status = aggregate_claim_status(ent_results)
        if status is ClaimStatus.CONTRADICTED:
            return None
        if (
            status is not ClaimStatus.ENTAILED
            or check.has_fabricated_citations
            or numeric.has_unsupported_numbers
        ):
            dropped.append(check.claim.text)
            continue
        kept.append(check.claim)

    if not kept:
        return None

    return GeneratedAnswer(
        answer=_partial_prose(kept, dropped),
        claims=tuple(kept),
        insufficient_evidence=False,
    )


def _partial_prose(kept: Sequence[Claim], dropped: Sequence[str]) -> str:
    """The answer text for a partial response: what stands, then what did not.

    What was dropped is named, because a student who is not told what is missing cannot
    tell a partial answer from a complete one. It is framed as something that could not be
    supported rather than restated as fact — the text came from a model and failed
    validation, and repeating it plainly would hand the student the very assertion the
    evidence declined to back.
    """
    body = " ".join(claim.text for claim in kept)
    if not dropped:
        return body

    missing = " ".join(dropped)
    return (
        f"{body}\n\n"
        "There is more to your question that your material does not appear to cover. "
        f"I could not find support for this, so I have left it out: {missing} "
        "If you expected that to be covered, the relevant pages may not have been "
        "uploaded yet."
    )


def build_repair_instructions(
    citation_results: tuple[CitationCheckResult, ...],
    entailment_by_claim: Sequence[Sequence[EntailmentResult]],
    fidelity: AnswerFidelity | None = None,
    numeric_results: Sequence[NumericCheckResult] = (),
    length_result: LengthCheckResult | None = None,
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

    for numeric in numeric_results:
        if numeric.has_unsupported_numbers:
            figures = ", ".join(numeric.unsupported_numbers)
            verb = "do" if len(numeric.unsupported_numbers) > 1 else "does"
            bullets.append(
                f'Claim "{numeric.claim.text}" uses {figures}, which {verb} not appear in '
                "any passage it cites. Use the figures exactly as the passages write them, "
                "without rounding or converting, or drop the statement."
            )

    if fidelity is AnswerFidelity.OVERSTATED:
        bullets.append(
            "Your answer states something none of your claims covers. Either rewrite the "
            "answer so it says only what the claims establish, or add a claim — with "
            "citations — for the statement you want to keep."
        )

    if length_result is not None and length_result.is_too_long:
        actual = (
            f"{length_result.word_count} words"
            if length_result.exceeds_word_limit
            else f"approximately {length_result.estimated_tokens} tokens"
        )
        limit = (
            f"{length_result.max_words} words"
            if length_result.exceeds_word_limit
            else f"{length_result.max_tokens} estimated tokens"
        )
        bullets.append(
            f"Your answer ({actual}) exceeds the {limit} limit. Rewrite it more concisely "
            "while keeping every citation and all factual claims intact."
        )

    if not bullets:
        return ""

    return (
        "Your previous answer requires correction. "
        "Revise it to address all of the following:\n"
        + "\n".join(f"- {b}" for b in bullets)
    )


#: Digits, optionally with thousands separators and a decimal part. Deliberately does not
#: match numbers written as words: "three stages" is prose, and a model that writes it where
#: the passage wrote "3 stages" has not changed the quantity.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Citation labels are full of digits and are not quantities. Removed before any number is
#: read out of a claim, or every `[S1]` would look like the figure 1.
_LABEL = re.compile(r"\[[^\]]*\]")


def _numbers_in(text: str) -> list[tuple[str, float]]:
    """Every numeric literal in the text, as written and as a value.

    Both forms are kept because they answer different questions: the value decides whether
    the figure is present in a passage, and the original spelling is what a repair
    instruction has to quote back so the model can find what it wrote.
    """
    found: list[tuple[str, float]] = []
    for match in _NUMBER.finditer(_LABEL.sub(" ", text)):
        raw = match.group()
        try:
            found.append((raw, float(raw.replace(",", ""))))
        except ValueError:  # pragma: no cover — the pattern cannot produce this
            continue
    return found


def check_numeric_fidelity(
    citation_results: Sequence[CitationCheckResult],
    evidence: Sequence[LabeledPassage],
) -> tuple[NumericCheckResult, ...]:
    """Return one result per claim, naming figures that appear in no passage it cites.

    Compared by value rather than by spelling, so `1,000` in a passage carries `1000` in a
    claim and `0.50` carries `0.5`. What it will not carry is a different number: rounding
    `3.14159` to `3.14` produces a figure the source does not contain, which is the case
    this exists to catch.

    Checked only against the passages that claim actually cites, and only the real ones —
    a fabricated label has no passage to compare against, and the citation existence check
    has already flagged it.
    """
    by_label = {p.label: p for p in evidence}
    results: list[NumericCheckResult] = []

    for check in citation_results:
        cited = [
            by_label[label]
            for label in check.claim.citations
            if label not in check.fabricated_labels and label in by_label
        ]
        available = {value for p in cited for _, value in _numbers_in(p.text.value)}
        unsupported = tuple(
            raw for raw, value in _numbers_in(check.claim.text) if value not in available
        )
        results.append(
            NumericCheckResult(claim=check.claim, unsupported_numbers=unsupported)
        )

    return tuple(results)


def check_length_limits(
    answer: GeneratedAnswer,
    max_words: int,
    max_tokens: int,
) -> LengthCheckResult:
    """Check that the answer prose fits within configured word and token limits.

    An answer that exceeds either limit is REPAIRABLE — the model is asked to condense it
    before the answer reaches the student. Runs deterministically on the prose text alone.
    """
    text = answer.answer
    word_count = len(text.split())
    estimated_tokens = len(text) // 4
    return LengthCheckResult(
        word_count=word_count,
        estimated_tokens=estimated_tokens,
        max_words=max_words,
        max_tokens=max_tokens,
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
