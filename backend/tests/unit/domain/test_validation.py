"""Unit tests for citation existence validation and semantic entailment helpers."""

from __future__ import annotations

import pytest

from app.domain.enums import AnswerFidelity, ClaimStatus, ValidationDecision
from app.domain.errors import GenerationParseError
from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import Claim, GeneratedAnswer
from app.domain.models.validation import (
    CitationCheckResult,
    EntailmentResult,
    aggregate_claim_status,
    build_fidelity_query,
    build_repair_instructions,
    check_citation_existence,
    decide,
    parse_entailment_status,
    parse_fidelity,
)
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _passage(label: str, text: str = "Some passage text.") -> LabeledPassage:
    return LabeledPassage(label=label, text=UntrustedText(text))


def _claim(text: str = "A fact.", citations: tuple[str, ...] = ("[S1]",)) -> Claim:
    return Claim(text=text, citations=citations)


def _answer(
    *claims: Claim,
    insufficient_evidence: bool = False,
    answer_text: str = "An answer.",
) -> GeneratedAnswer:
    if insufficient_evidence:
        return GeneratedAnswer(
            answer=answer_text, claims=(), insufficient_evidence=True
        )
    return GeneratedAnswer(answer=answer_text, claims=claims, insufficient_evidence=False)


# ---------------------------------------------------------------------------
# CitationCheckResult
# ---------------------------------------------------------------------------


class TestCitationCheckResult:
    def test_no_fabricated_citations(self) -> None:
        result = CitationCheckResult(claim=_claim(), fabricated_labels=frozenset())
        assert not result.has_fabricated_citations

    def test_with_fabricated_citations(self) -> None:
        result = CitationCheckResult(
            claim=_claim(), fabricated_labels=frozenset({"[X99]"})
        )
        assert result.has_fabricated_citations

    def test_frozen(self) -> None:
        result = CitationCheckResult(claim=_claim(), fabricated_labels=frozenset())
        with pytest.raises(AttributeError):
            result.fabricated_labels = frozenset({"[X1]"})  # type: ignore[misc]


# ---------------------------------------------------------------------------
# check_citation_existence — basic cases
# ---------------------------------------------------------------------------


class TestCheckCitationExistence:
    def test_single_claim_with_known_label(self) -> None:
        answer = _answer(_claim(citations=("[S1]",)))
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert len(results) == 1
        assert not results[0].has_fabricated_citations
        assert results[0].fabricated_labels == frozenset()

    def test_single_claim_with_fabricated_label(self) -> None:
        answer = _answer(_claim(citations=("[X99]",)))
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert len(results) == 1
        assert results[0].has_fabricated_citations
        assert results[0].fabricated_labels == frozenset({"[X99]"})

    def test_claim_with_mixed_labels(self) -> None:
        answer = _answer(_claim(citations=("[S1]", "[X99]")))
        evidence = [_passage("[S1]"), _passage("[S2]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].fabricated_labels == frozenset({"[X99]"})

    def test_claim_with_all_labels_known(self) -> None:
        answer = _answer(_claim(citations=("[S1]", "[S2]")))
        evidence = [_passage("[S1]"), _passage("[S2]"), _passage("[S3]")]
        results = check_citation_existence(answer, evidence)
        assert not results[0].has_fabricated_citations

    def test_multiple_claims_each_checked_independently(self) -> None:
        claim_good = _claim(text="Good fact.", citations=("[S1]",))
        claim_bad = _claim(text="Bad fact.", citations=("[FAKE]",))
        answer = _answer(claim_good, claim_bad)
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert len(results) == 2
        assert not results[0].has_fabricated_citations
        assert results[1].has_fabricated_citations
        assert results[1].fabricated_labels == frozenset({"[FAKE]"})

    def test_returns_one_result_per_claim(self) -> None:
        claims = [_claim(text=f"Fact {i}.", citations=(f"[S{i}]",)) for i in range(1, 5)]
        answer = _answer(*claims)
        evidence = [_passage(f"[S{i}]") for i in range(1, 5)]
        results = check_citation_existence(answer, evidence)
        assert len(results) == 4

    def test_result_carries_the_claim(self) -> None:
        claim = _claim(text="Specific claim.", citations=("[S1]",))
        answer = _answer(claim)
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].claim is claim

    def test_result_order_matches_claim_order(self) -> None:
        claim_a = _claim(text="Claim A.", citations=("[S1]",))
        claim_b = _claim(text="Claim B.", citations=("[S2]",))
        answer = _answer(claim_a, claim_b)
        evidence = [_passage("[S1]"), _passage("[S2]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].claim is claim_a
        assert results[1].claim is claim_b


# ---------------------------------------------------------------------------
# check_citation_existence — empty / edge cases
# ---------------------------------------------------------------------------


class TestCheckCitationExistenceEdgeCases:
    def test_insufficient_evidence_answer_returns_empty_tuple(self) -> None:
        answer = _answer(insufficient_evidence=True, answer_text="No relevant material.")
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert results == ()

    def test_empty_evidence_set_makes_all_labels_fabricated(self) -> None:
        answer = _answer(_claim(citations=("[S1]",)))
        results = check_citation_existence(answer, [])
        assert results[0].has_fabricated_citations
        assert results[0].fabricated_labels == frozenset({"[S1]"})

    def test_labels_are_case_sensitive(self) -> None:
        answer = _answer(_claim(citations=("[s1]",)))
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].has_fabricated_citations
        assert "[s1]" in results[0].fabricated_labels

    def test_label_must_match_exactly_no_bracket_normalization(self) -> None:
        answer = _answer(_claim(citations=("S1",)))
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].has_fabricated_citations

    def test_multiple_fabricated_labels_in_one_claim(self) -> None:
        answer = _answer(_claim(citations=("[A]", "[B]", "[C]")))
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].fabricated_labels == frozenset({"[A]", "[B]", "[C]"})

    def test_returns_tuple_not_list(self) -> None:
        answer = _answer(_claim())
        evidence = [_passage("[S1]")]
        results = check_citation_existence(answer, evidence)
        assert isinstance(results, tuple)

    def test_no_claims_no_evidence_returns_empty_tuple(self) -> None:
        answer = _answer(insufficient_evidence=True, answer_text="Nothing available.")
        results = check_citation_existence(answer, [])
        assert results == ()

    def test_duplicate_labels_in_evidence_do_not_cause_errors(self) -> None:
        answer = _answer(_claim(citations=("[S1]",)))
        evidence = [_passage("[S1]"), _passage("[S1]", text="Another passage.")]
        results = check_citation_existence(answer, evidence)
        assert not results[0].has_fabricated_citations

    def test_evidence_label_substring_does_not_match(self) -> None:
        answer = _answer(_claim(citations=("[S1]",)))
        evidence = [_passage("[S10]")]
        results = check_citation_existence(answer, evidence)
        assert results[0].has_fabricated_citations


# ---------------------------------------------------------------------------
# EntailmentResult
# ---------------------------------------------------------------------------


class TestEntailmentResult:
    def test_stores_claim_label_and_status(self) -> None:
        claim = _claim()
        result = EntailmentResult(
            claim=claim, passage_label="[S1]", status=ClaimStatus.ENTAILED
        )
        assert result.claim is claim
        assert result.passage_label == "[S1]"
        assert result.status is ClaimStatus.ENTAILED

    def test_frozen(self) -> None:
        result = EntailmentResult(
            claim=_claim(), passage_label="[S1]", status=ClaimStatus.ENTAILED
        )
        with pytest.raises(AttributeError):
            result.status = ClaimStatus.CONTRADICTED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_entailment_status
# ---------------------------------------------------------------------------


class TestParseEntailmentStatus:
    def test_entailed(self) -> None:
        assert parse_entailment_status("ENTAILED") is ClaimStatus.ENTAILED

    def test_contradicted(self) -> None:
        assert parse_entailment_status("CONTRADICTED") is ClaimStatus.CONTRADICTED

    def test_not_supported(self) -> None:
        assert parse_entailment_status("NOT_SUPPORTED") is ClaimStatus.NOT_SUPPORTED

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert parse_entailment_status("  ENTAILED\n") is ClaimStatus.ENTAILED

    def test_case_insensitive(self) -> None:
        assert parse_entailment_status("entailed") is ClaimStatus.ENTAILED
        assert parse_entailment_status("Contradicted") is ClaimStatus.CONTRADICTED
        assert parse_entailment_status("not_supported") is ClaimStatus.NOT_SUPPORTED

    def test_unrecognised_value_raises(self) -> None:
        with pytest.raises(GenerationParseError, match="NOT_SUPPORTED"):
            parse_entailment_status("MAYBE")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(GenerationParseError):
            parse_entailment_status("")

    def test_partial_match_raises(self) -> None:
        with pytest.raises(GenerationParseError):
            parse_entailment_status("ENTAIL")


# ---------------------------------------------------------------------------
# aggregate_claim_status
# ---------------------------------------------------------------------------


class TestAggregateClaimStatus:
    def _result(self, status: ClaimStatus, label: str = "[S1]") -> EntailmentResult:
        return EntailmentResult(claim=_claim(), passage_label=label, status=status)

    def test_empty_results_returns_not_supported(self) -> None:
        assert aggregate_claim_status([]) is ClaimStatus.NOT_SUPPORTED

    def test_single_entailed(self) -> None:
        assert aggregate_claim_status([self._result(ClaimStatus.ENTAILED)]) is (
            ClaimStatus.ENTAILED
        )

    def test_single_contradicted(self) -> None:
        assert aggregate_claim_status([self._result(ClaimStatus.CONTRADICTED)]) is (
            ClaimStatus.CONTRADICTED
        )

    def test_single_not_supported(self) -> None:
        assert aggregate_claim_status([self._result(ClaimStatus.NOT_SUPPORTED)]) is (
            ClaimStatus.NOT_SUPPORTED
        )

    def test_entailed_beats_not_supported(self) -> None:
        results = [
            self._result(ClaimStatus.ENTAILED, "[S1]"),
            self._result(ClaimStatus.NOT_SUPPORTED, "[S2]"),
        ]
        assert aggregate_claim_status(results) is ClaimStatus.ENTAILED

    def test_entailed_beats_contradicted(self) -> None:
        results = [
            self._result(ClaimStatus.ENTAILED, "[S1]"),
            self._result(ClaimStatus.CONTRADICTED, "[S2]"),
        ]
        assert aggregate_claim_status(results) is ClaimStatus.ENTAILED

    def test_contradicted_beats_not_supported(self) -> None:
        results = [
            self._result(ClaimStatus.NOT_SUPPORTED, "[S1]"),
            self._result(ClaimStatus.CONTRADICTED, "[S2]"),
        ]
        assert aggregate_claim_status(results) is ClaimStatus.CONTRADICTED

    def test_all_not_supported(self) -> None:
        results = [
            self._result(ClaimStatus.NOT_SUPPORTED, "[S1]"),
            self._result(ClaimStatus.NOT_SUPPORTED, "[S2]"),
        ]
        assert aggregate_claim_status(results) is ClaimStatus.NOT_SUPPORTED


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


class TestDecide:
    def _check(
        self, claim: Claim, fabricated: frozenset[str] = frozenset()
    ) -> CitationCheckResult:
        return CitationCheckResult(claim=claim, fabricated_labels=fabricated)

    def _ent(self, claim: Claim, label: str, status: ClaimStatus) -> EntailmentResult:
        return EntailmentResult(claim=claim, passage_label=label, status=status)

    def test_insufficient_evidence_returns_insufficient_evidence(self) -> None:
        answer = _answer(insufficient_evidence=True, answer_text="No relevant material.")
        result = decide(answer, (), [])
        assert result is ValidationDecision.INSUFFICIENT_EVIDENCE

    def test_all_claims_entailed_no_fabricated_returns_valid(self) -> None:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        assert decide(answer, checks, ents) is ValidationDecision.VALID

    def test_all_fabricated_citations_returns_rejected(self) -> None:
        claim = _claim(citations=("[FAKE]",))
        answer = _answer(claim)
        checks = (self._check(claim, fabricated=frozenset({"[FAKE]"})),)
        ents: list[list[EntailmentResult]] = [[]]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED

    def test_contradicted_returns_rejected(self) -> None:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.CONTRADICTED)]]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED

    def test_not_supported_returns_repairable(self) -> None:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.NOT_SUPPORTED)]]
        assert decide(answer, checks, ents) is ValidationDecision.REPAIRABLE

    def test_some_fabricated_citations_returns_repairable(self) -> None:
        claim = _claim(citations=("[S1]", "[FAKE]"))
        answer = _answer(claim)
        checks = (self._check(claim, fabricated=frozenset({"[FAKE]"})),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        assert decide(answer, checks, ents) is ValidationDecision.REPAIRABLE

    def test_rejected_beats_repairable(self) -> None:
        good = _claim(text="Good fact.", citations=("[S1]",))
        bad = _claim(text="Bad fact.", citations=("[FAKE]",))
        answer = _answer(good, bad)
        checks = (
            self._check(good),
            self._check(bad, fabricated=frozenset({"[FAKE]"})),
        )
        ents: list[list[EntailmentResult]] = [
            [self._ent(good, "[S1]", ClaimStatus.NOT_SUPPORTED)],
            [],
        ]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED

    def test_multiple_claims_all_valid(self) -> None:
        c1 = _claim(text="Fact one.", citations=("[S1]",))
        c2 = _claim(text="Fact two.", citations=("[S2]",))
        answer = _answer(c1, c2)
        checks = (self._check(c1), self._check(c2))
        ents = [
            [self._ent(c1, "[S1]", ClaimStatus.ENTAILED)],
            [self._ent(c2, "[S2]", ClaimStatus.ENTAILED)],
        ]
        assert decide(answer, checks, ents) is ValidationDecision.VALID

    def test_one_repairable_claim_makes_overall_repairable(self) -> None:
        c1 = _claim(text="Fact one.", citations=("[S1]",))
        c2 = _claim(text="Fact two.", citations=("[S2]",))
        answer = _answer(c1, c2)
        checks = (self._check(c1), self._check(c2))
        ents = [
            [self._ent(c1, "[S1]", ClaimStatus.ENTAILED)],
            [self._ent(c2, "[S2]", ClaimStatus.NOT_SUPPORTED)],
        ]
        assert decide(answer, checks, ents) is ValidationDecision.REPAIRABLE

    def test_contradicted_and_not_supported_returns_rejected(self) -> None:
        c1 = _claim(text="Contradicted.", citations=("[S1]",))
        c2 = _claim(text="Not supported.", citations=("[S2]",))
        answer = _answer(c1, c2)
        checks = (self._check(c1), self._check(c2))
        ents = [
            [self._ent(c1, "[S1]", ClaimStatus.CONTRADICTED)],
            [self._ent(c2, "[S2]", ClaimStatus.NOT_SUPPORTED)],
        ]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED

    def test_some_fabricated_with_contradiction_returns_rejected(self) -> None:
        claim = _claim(citations=("[S1]", "[FAKE]"))
        answer = _answer(claim)
        checks = (self._check(claim, fabricated=frozenset({"[FAKE]"})),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.CONTRADICTED)]]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED

    def test_all_fabricated_with_entailed_still_rejected(self) -> None:
        claim = _claim(citations=("[FAKE1]", "[FAKE2]"))
        answer = _answer(claim)
        checks = (self._check(claim, fabricated=frozenset({"[FAKE1]", "[FAKE2]"})),)
        ents: list[list[EntailmentResult]] = [[]]
        assert decide(answer, checks, ents) is ValidationDecision.REJECTED


# ---------------------------------------------------------------------------
# build_repair_instructions
# ---------------------------------------------------------------------------


class TestBuildRepairInstructions:
    def _check(
        self, claim: Claim, fabricated: frozenset[str] = frozenset()
    ) -> CitationCheckResult:
        return CitationCheckResult(claim=claim, fabricated_labels=fabricated)

    def _ent(self, claim: Claim, label: str, status: ClaimStatus) -> EntailmentResult:
        return EntailmentResult(claim=claim, passage_label=label, status=status)

    def test_no_issues_returns_empty_string(self) -> None:
        claim = _claim(citations=("[S1]",))
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        assert build_repair_instructions(checks, ents) == ""

    def test_fabricated_label_included_in_output(self) -> None:
        claim = _claim(citations=("[S1]", "[FAKE]"))
        checks = (self._check(claim, fabricated=frozenset({"[FAKE]"})),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        result = build_repair_instructions(checks, ents)
        assert "[FAKE]" in result
        assert claim.text in result

    def test_not_supported_mentioned_in_output(self) -> None:
        claim = _claim(citations=("[S1]",))
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.NOT_SUPPORTED)]]
        result = build_repair_instructions(checks, ents)
        assert claim.text in result
        assert "not supported" in result.lower()

    def test_fabricated_and_not_supported_both_reported(self) -> None:
        claim = _claim(citations=("[S1]", "[FAKE]"))
        checks = (self._check(claim, fabricated=frozenset({"[FAKE]"})),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.NOT_SUPPORTED)]]
        result = build_repair_instructions(checks, ents)
        assert "[FAKE]" in result
        assert "not supported" in result.lower()

    def test_multiple_fabricated_labels_all_listed(self) -> None:
        claim = _claim(citations=("[S1]", "[A]", "[B]"))
        checks = (self._check(claim, fabricated=frozenset({"[A]", "[B]"})),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        result = build_repair_instructions(checks, ents)
        assert "[A]" in result
        assert "[B]" in result

    def test_multiple_claims_all_issues_listed(self) -> None:
        c1 = _claim(text="First fact.", citations=("[S1]", "[FAKE]"))
        c2 = _claim(text="Second fact.", citations=("[S2]",))
        checks = (
            self._check(c1, fabricated=frozenset({"[FAKE]"})),
            self._check(c2),
        )
        ents = [
            [self._ent(c1, "[S1]", ClaimStatus.ENTAILED)],
            [self._ent(c2, "[S2]", ClaimStatus.NOT_SUPPORTED)],
        ]
        result = build_repair_instructions(checks, ents)
        assert "First fact." in result
        assert "Second fact." in result
        assert "[FAKE]" in result
        assert "not supported" in result.lower()

    def test_entailed_claim_without_fabrication_not_mentioned(self) -> None:
        c1 = _claim(text="Clean fact.", citations=("[S1]",))
        c2 = _claim(text="Bad fact.", citations=("[S2]",))
        checks = (self._check(c1), self._check(c2))
        ents = [
            [self._ent(c1, "[S1]", ClaimStatus.ENTAILED)],
            [self._ent(c2, "[S2]", ClaimStatus.NOT_SUPPORTED)],
        ]
        result = build_repair_instructions(checks, ents)
        assert "Clean fact." not in result
        assert "Bad fact." in result

    def test_result_starts_with_correction_preamble(self) -> None:
        claim = _claim(citations=("[S1]",))
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.NOT_SUPPORTED)]]
        result = build_repair_instructions(checks, ents)
        assert result.startswith("Your previous answer requires correction.")


class TestParseFidelity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("FAITHFUL", AnswerFidelity.FAITHFUL),
            ("OVERSTATED", AnswerFidelity.OVERSTATED),
            ("  faithful  ", AnswerFidelity.FAITHFUL),
            ("Overstated", AnswerFidelity.OVERSTATED),
        ],
    )
    def test_parses_the_forms_a_model_produces(
        self, raw: str, expected: AnswerFidelity
    ) -> None:
        assert parse_fidelity(raw) is expected

    @pytest.mark.parametrize("raw", ["", "MAYBE", "FAITHFUL.", "yes"])
    def test_an_unrecognised_verdict_is_a_parse_failure_not_a_guess(self, raw: str) -> None:
        with pytest.raises(GenerationParseError):
            parse_fidelity(raw)


class TestBuildFidelityQuery:
    def test_shows_the_answer_and_its_claims(self) -> None:
        claim = _claim(text="Gradients flow backwards.", citations=("[S1]",))
        answer = _answer(claim, answer_text="Gradients flow backwards through the network.")

        query = build_fidelity_query(answer)

        assert "Gradients flow backwards through the network." in query
        assert "Gradients flow backwards." in query

    def test_numbers_the_claims(self) -> None:
        """A numbered list is what the model compares against, rather than a paragraph."""
        first = _claim(text="First fact.", citations=("[S1]",))
        second = _claim(text="Second fact.", citations=("[S2]",))
        query = build_fidelity_query(_answer(first, second))

        assert "1. First fact." in query
        assert "2. Second fact." in query


class TestDecideWithFidelity:
    """The prose the student reads, checked against the claims already verified."""

    def _check(self, claim: Claim) -> CitationCheckResult:
        return CitationCheckResult(claim=claim, fabricated_labels=frozenset())

    def _ent(self, claim: Claim, label: str, status: ClaimStatus) -> EntailmentResult:
        return EntailmentResult(claim=claim, passage_label=label, status=status)

    def _sound_answer(self) -> tuple[GeneratedAnswer, tuple[CitationCheckResult, ...], list]:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]
        return answer, checks, ents

    def test_an_overstated_answer_is_repairable_though_every_claim_holds(self) -> None:
        """The gap this closes: each claim is entailed, so every claim-level check passes,
        and the prose still asserts something none of them established."""
        answer, checks, ents = self._sound_answer()

        result = decide(answer, checks, ents, AnswerFidelity.OVERSTATED)

        assert result is ValidationDecision.REPAIRABLE

    def test_a_faithful_answer_stays_valid(self) -> None:
        answer, checks, ents = self._sound_answer()
        assert decide(answer, checks, ents, AnswerFidelity.FAITHFUL) is ValidationDecision.VALID

    def test_an_unchecked_answer_is_treated_as_unchecked_not_as_passing(self) -> None:
        """None means the check did not run. It must not read as a verdict either way."""
        answer, checks, ents = self._sound_answer()
        assert decide(answer, checks, ents, None) is ValidationDecision.VALID

    def test_rejection_still_outranks_an_overstated_answer(self) -> None:
        """Repairing the prose cannot save an answer whose evidence contradicts it."""
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.CONTRADICTED)]]

        result = decide(answer, checks, ents, AnswerFidelity.OVERSTATED)

        assert result is ValidationDecision.REJECTED

    def test_an_abstaining_answer_is_unaffected(self) -> None:
        answer = _answer(insufficient_evidence=True, answer_text="Not covered.")
        result = decide(answer, (), [], AnswerFidelity.OVERSTATED)
        assert result is ValidationDecision.INSUFFICIENT_EVIDENCE

    def test_repair_instructions_name_the_overstatement(self) -> None:
        claim = _claim(citations=("[S1]",))
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]

        result = build_repair_instructions(checks, ents, AnswerFidelity.OVERSTATED)

        assert "none of your claims covers" in result
        assert result.startswith("Your previous answer requires correction.")

    def test_a_faithful_answer_produces_no_repair_text(self) -> None:
        claim = _claim(citations=("[S1]",))
        checks = (self._check(claim),)
        ents = [[self._ent(claim, "[S1]", ClaimStatus.ENTAILED)]]

        assert build_repair_instructions(checks, ents, AnswerFidelity.FAITHFUL) == ""
