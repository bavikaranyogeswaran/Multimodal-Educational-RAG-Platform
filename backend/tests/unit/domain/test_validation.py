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
    LengthCheckResult,
    NumericCheckResult,
    aggregate_claim_status,
    build_fidelity_query,
    build_partial_answer,
    build_repair_instructions,
    check_citation_existence,
    check_length_limits,
    check_numeric_fidelity,
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


class TestCheckNumericFidelity:
    """Figures have to survive into the answer as the source wrote them."""

    @staticmethod
    def _checked(claim_text: str, passage_text: str) -> tuple[str, ...]:
        claim = _claim(text=claim_text, citations=("[S1]",))
        checks = (CitationCheckResult(claim=claim, fabricated_labels=frozenset()),)
        results = check_numeric_fidelity(checks, [_passage("[S1]", passage_text)])
        return results[0].unsupported_numbers

    def test_a_figure_the_passage_contains_is_supported(self) -> None:
        assert self._checked("Training ran for 9 epochs.", "It ran for 9 epochs.") == ()

    def test_a_figure_no_passage_contains_is_flagged(self) -> None:
        assert self._checked("Training ran for 9 epochs.", "It ran for 12 epochs.") == ("9",)

    def test_thousands_separators_do_not_make_a_figure_look_invented(self) -> None:
        assert self._checked("The set has 1000 items.", "The set has 1,000 items.") == ()

    def test_trailing_zeros_do_not_make_a_figure_look_invented(self) -> None:
        assert self._checked("Accuracy was 0.5.", "Accuracy was 0.50.") == ()

    def test_a_rounded_figure_is_flagged(self) -> None:
        """Rounding produces a number the source does not contain, which is the case this
        check exists to catch — and one entailment would happily pass."""
        assert self._checked("Pi is 3.14.", "Pi is 3.14159.") == ("3.14",)

    def test_a_computed_figure_is_flagged(self) -> None:
        """The passage supports the statement, so the claim entails. The student still
        cannot find the figure when they follow the citation."""
        assert self._checked("It rose by 50%.", "It rose from 100 to 150.") == ("50",)

    def test_citation_labels_are_not_read_as_figures(self) -> None:
        """Every label is full of digits and none of them is a quantity."""
        assert self._checked("As [S1] shows, there are 5 stages.", "There are 5 stages.") == ()

    def test_numbers_written_as_words_are_left_alone(self) -> None:
        """Writing "three" where the passage wrote "3" has not changed the quantity, and
        matching prose against digits would flag every well-written answer."""
        assert self._checked("There are three stages.", "There are 3 stages.") == ()

    def test_reports_the_figure_as_the_claim_wrote_it(self) -> None:
        """A repair instruction has to quote back what the model wrote, or it cannot find
        the thing it is being asked to change."""
        assert self._checked("The set has 1,500 items.", "The set has 900 items.") == ("1,500",)

    def test_only_the_passages_a_claim_cites_are_consulted(self) -> None:
        claim = _claim(text="It ran for 9 epochs.", citations=("[S1]",))
        checks = (CitationCheckResult(claim=claim, fabricated_labels=frozenset()),)
        evidence = [_passage("[S1]", "No figures here."), _passage("[S2]", "It ran for 9.")]

        results = check_numeric_fidelity(checks, evidence)

        assert results[0].unsupported_numbers == ("9",)

    def test_a_fabricated_label_supplies_no_figures(self) -> None:
        claim = _claim(text="It ran for 9 epochs.", citations=("[S1]", "[S99]"))
        checks = (CitationCheckResult(claim=claim, fabricated_labels=frozenset({"[S99]"})),)

        results = check_numeric_fidelity(checks, [_passage("[S1]", "No figures here.")])

        assert results[0].unsupported_numbers == ("9",)

    def test_returns_one_result_per_claim_in_order(self) -> None:
        first = _claim(text="It ran for 9 epochs.", citations=("[S1]",))
        second = _claim(text="Accuracy was 0.5.", citations=("[S1]",))
        checks = tuple(
            CitationCheckResult(claim=c, fabricated_labels=frozenset()) for c in (first, second)
        )

        results = check_numeric_fidelity(checks, [_passage("[S1]", "It ran for 9 epochs.")])

        assert len(results) == 2
        assert results[0].unsupported_numbers == ()
        assert results[1].unsupported_numbers == ("0.5",)

    def test_a_claim_with_no_figures_is_never_flagged(self) -> None:
        assert self._checked("Gradients flow backwards.", "Something else entirely.") == ()


class TestDecideWithNumericFidelity:
    def _setup(self, unsupported: tuple[str, ...]) -> tuple:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (CitationCheckResult(claim=claim, fabricated_labels=frozenset()),)
        ents = [[EntailmentResult(claim=claim, passage_label="[S1]", status=ClaimStatus.ENTAILED)]]
        numeric = (NumericCheckResult(claim=claim, unsupported_numbers=unsupported),)
        return answer, checks, ents, numeric

    def test_an_invented_figure_makes_an_otherwise_valid_answer_repairable(self) -> None:
        """Every claim is entailed, so nothing else objects."""
        answer, checks, ents, numeric = self._setup(("9",))

        result = decide(answer, checks, ents, None, numeric)

        assert result is ValidationDecision.REPAIRABLE

    def test_an_answer_whose_figures_all_check_out_stays_valid(self) -> None:
        answer, checks, ents, numeric = self._setup(())
        assert decide(answer, checks, ents, None, numeric) is ValidationDecision.VALID

    def test_rejection_still_outranks_an_invented_figure(self) -> None:
        claim = _claim(citations=("[S1]",))
        answer = _answer(claim)
        checks = (CitationCheckResult(claim=claim, fabricated_labels=frozenset()),)
        ents = [
            [EntailmentResult(claim=claim, passage_label="[S1]", status=ClaimStatus.CONTRADICTED)]
        ]
        numeric = (NumericCheckResult(claim=claim, unsupported_numbers=("9",)),)

        assert decide(answer, checks, ents, None, numeric) is ValidationDecision.REJECTED

    def test_repair_instructions_quote_the_figure_back(self) -> None:
        _, checks, ents, numeric = self._setup(("1,500",))

        result = build_repair_instructions(checks, ents, None, numeric)

        assert "1,500" in result
        assert "does not appear in any passage it cites" in result

    def test_multiple_figures_are_listed_together(self) -> None:
        _, checks, ents, numeric = self._setup(("9", "0.5"))

        result = build_repair_instructions(checks, ents, None, numeric)

        assert "9, 0.5" in result
        assert "do not appear" in result


class TestBuildPartialAnswer:
    """Salvaging the part of an answer the evidence carries, once a repair has been spent."""

    @staticmethod
    def _inputs(
        *specs: tuple[Claim, ClaimStatus, frozenset[str], tuple[str, ...]],
    ) -> tuple[tuple, tuple, tuple]:
        checks = tuple(
            CitationCheckResult(claim=c, fabricated_labels=fab) for c, _, fab, _ in specs
        )
        ents = tuple(
            (EntailmentResult(claim=c, passage_label=c.citations[0], status=st),)
            for c, st, _, _ in specs
        )
        numeric = tuple(
            NumericCheckResult(claim=c, unsupported_numbers=nums) for c, _, _, nums in specs
        )
        return checks, ents, numeric

    def _build(
        self, *specs: tuple[Claim, ClaimStatus, frozenset[str], tuple[str, ...]]
    ) -> GeneratedAnswer | None:
        return build_partial_answer(*self._inputs(*specs))

    def test_keeps_the_supported_claim_and_drops_the_unsupported_one(self) -> None:
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))
        bad = _claim(text="Training takes nine epochs.", citations=("[S2]",))

        result = self._build(
            (good, ClaimStatus.ENTAILED, frozenset(), ()),
            (bad, ClaimStatus.NOT_SUPPORTED, frozenset(), ()),
        )

        assert result is not None
        assert result.claims == (good,)

    def test_names_what_was_left_out(self) -> None:
        """A student not told what is missing cannot tell a partial answer from a whole one."""
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))
        bad = _claim(text="Training takes nine epochs.", citations=("[S2]",))

        result = self._build(
            (good, ClaimStatus.ENTAILED, frozenset(), ()),
            (bad, ClaimStatus.NOT_SUPPORTED, frozenset(), ()),
        )

        assert result is not None
        assert "Training takes nine epochs." in result.answer
        assert "could not find support" in result.answer

    def test_the_prose_is_rebuilt_from_the_claims(self) -> None:
        """The model wrote its prose to carry every claim it made. Keeping that prose over
        a reduced set of claims would leave it asserting what no longer stands."""
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))

        result = self._build((good, ClaimStatus.ENTAILED, frozenset(), ()))

        assert result is not None
        assert result.answer.startswith("Gradients flow backwards.")

    def test_a_wholly_supported_answer_needs_no_gap_notice(self) -> None:
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))

        result = self._build((good, ClaimStatus.ENTAILED, frozenset(), ()))

        assert result is not None
        assert "could not find support" not in result.answer

    def test_the_result_does_not_claim_insufficient_evidence(self) -> None:
        """Something was answered. Abstention is a different outcome from a partial answer."""
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))

        result = self._build((good, ClaimStatus.ENTAILED, frozenset(), ()))

        assert result is not None
        assert result.insufficient_evidence is False

    def test_nothing_survives_when_every_claim_is_unsupported(self) -> None:
        bad = _claim(text="Training takes nine epochs.", citations=("[S1]",))
        assert self._build((bad, ClaimStatus.NOT_SUPPORTED, frozenset(), ())) is None

    def test_a_contradiction_stops_salvage_entirely(self) -> None:
        """A contradiction is not a gap. It means the model misread the material, and
        answering around it would present the rest as though it had not."""
        good = _claim(text="Gradients flow backwards.", citations=("[S1]",))
        wrong = _claim(text="Gradients flow forwards.", citations=("[S2]",))

        result = self._build(
            (good, ClaimStatus.ENTAILED, frozenset(), ()),
            (wrong, ClaimStatus.CONTRADICTED, frozenset(), ()),
        )

        assert result is None

    def test_a_claim_with_an_invented_citation_is_not_salvaged(self) -> None:
        """Even entailed by a real passage. The model invented a source, and keeping the
        claim would ship something built on that invention."""
        claim = _claim(text="Gradients flow backwards.", citations=("[S1]", "[S99]"))

        result = self._build((claim, ClaimStatus.ENTAILED, frozenset({"[S99]"}), ()))

        assert result is None

    def test_a_claim_with_an_invented_figure_is_not_salvaged(self) -> None:
        """Salvage is the one path returning an answer nobody re-validated, so it applies
        the same bar the validators did rather than a looser one."""
        claim = _claim(text="Training takes 9 epochs.", citations=("[S1]",))

        result = self._build((claim, ClaimStatus.ENTAILED, frozenset(), ("9",)))

        assert result is None

    def test_surviving_claims_keep_their_order(self) -> None:
        first = _claim(text="First fact.", citations=("[S1]",))
        skipped = _claim(text="Unsupported.", citations=("[S2]",))
        last = _claim(text="Second fact.", citations=("[S3]",))

        result = self._build(
            (first, ClaimStatus.ENTAILED, frozenset(), ()),
            (skipped, ClaimStatus.NOT_SUPPORTED, frozenset(), ()),
            (last, ClaimStatus.ENTAILED, frozenset(), ()),
        )

        assert result is not None
        assert [c.text for c in result.claims] == ["First fact.", "Second fact."]


# ---------------------------------------------------------------------------
# check_length_limits
# ---------------------------------------------------------------------------


class TestCheckLengthLimits:
    def _answer(self, text: str) -> GeneratedAnswer:
        claim = _claim(text="A fact.", citations=("[S1]",))
        return GeneratedAnswer(answer=text or "placeholder", claims=(claim,), insufficient_evidence=False)

    def test_within_both_limits_not_too_long(self) -> None:
        answer = self._answer("One two three.")
        result = check_length_limits(answer, max_words=10, max_tokens=50)
        assert not result.is_too_long
        assert not result.exceeds_word_limit
        assert not result.exceeds_token_limit

    def test_word_count_is_exact_split_count(self) -> None:
        answer = self._answer("alpha beta gamma")
        result = check_length_limits(answer, max_words=100, max_tokens=500)
        assert result.word_count == 3

    def test_estimated_tokens_is_char_count_over_four(self) -> None:
        text = "a" * 100
        answer = self._answer(text)
        result = check_length_limits(answer, max_words=1000, max_tokens=10000)
        assert result.estimated_tokens == 25  # 100 // 4

    def test_exceeds_word_limit_flags_repairable(self) -> None:
        answer = self._answer(" ".join(["word"] * 10))
        result = check_length_limits(answer, max_words=5, max_tokens=1000)
        assert result.exceeds_word_limit
        assert result.is_too_long

    def test_exceeds_token_limit_only(self) -> None:
        long_words = " ".join(["a" * 50] * 2)  # 2 words, 101 chars → ~25 estimated tokens
        answer = self._answer(long_words)
        result = check_length_limits(answer, max_words=100, max_tokens=10)
        assert not result.exceeds_word_limit
        assert result.exceeds_token_limit
        assert result.is_too_long

    def test_exactly_at_limit_not_flagged(self) -> None:
        answer = self._answer(" ".join(["word"] * 5))
        result = check_length_limits(answer, max_words=5, max_tokens=1000)
        assert not result.exceeds_word_limit

    def test_limits_stored_on_result(self) -> None:
        answer = self._answer("hello")
        result = check_length_limits(answer, max_words=42, max_tokens=99)
        assert result.max_words == 42
        assert result.max_tokens == 99

    def test_single_word_answer_not_too_long(self) -> None:
        answer = self._answer("Correct.")
        result = check_length_limits(answer, max_words=10, max_tokens=10)
        assert not result.is_too_long
        assert result.word_count == 1


# ---------------------------------------------------------------------------
# decide() with length_result
# ---------------------------------------------------------------------------


class TestDecideWithLengthResult:
    def _citation(
        self, claim: Claim, fabricated: frozenset[str] = frozenset()
    ) -> CitationCheckResult:
        return CitationCheckResult(claim=claim, fabricated_labels=fabricated)

    def _entailment(
        self, claim: Claim, status: ClaimStatus, label: str = "[S1]"
    ) -> list[EntailmentResult]:
        return [EntailmentResult(claim=claim, passage_label=label, status=status)]

    def test_length_too_long_makes_answer_repairable(self) -> None:
        claim = _claim()
        answer = _answer(claim)
        citation = self._citation(claim)
        ent = self._entailment(claim, ClaimStatus.ENTAILED)
        long_result = LengthCheckResult(
            word_count=500, estimated_tokens=700, max_words=400, max_tokens=600
        )
        decision = decide(answer, (citation,), [ent], length_result=long_result)
        assert decision is ValidationDecision.REPAIRABLE

    def test_length_within_limits_does_not_affect_valid_answer(self) -> None:
        claim = _claim()
        answer = _answer(claim)
        citation = self._citation(claim)
        ent = self._entailment(claim, ClaimStatus.ENTAILED)
        ok_result = LengthCheckResult(
            word_count=100, estimated_tokens=150, max_words=400, max_tokens=600
        )
        decision = decide(answer, (citation,), [ent], length_result=ok_result)
        assert decision is ValidationDecision.VALID

    def test_none_length_result_does_not_affect_decision(self) -> None:
        claim = _claim()
        answer = _answer(claim)
        citation = self._citation(claim)
        ent = self._entailment(claim, ClaimStatus.ENTAILED)
        decision = decide(answer, (citation,), [ent], length_result=None)
        assert decision is ValidationDecision.VALID

    def test_rejected_answer_stays_rejected_even_when_too_long(self) -> None:
        claim = _claim()
        answer = _answer(claim)
        citation = self._citation(claim, fabricated=frozenset({"[S1]"}))
        ent = self._entailment(claim, ClaimStatus.NOT_SUPPORTED)
        long_result = LengthCheckResult(
            word_count=500, estimated_tokens=700, max_words=400, max_tokens=600
        )
        decision = decide(answer, (citation,), [ent], length_result=long_result)
        assert decision is ValidationDecision.REJECTED


# ---------------------------------------------------------------------------
# build_repair_instructions() with length_result
# ---------------------------------------------------------------------------


class TestBuildRepairInstructionsWithLength:
    def _no_issues(self, claim: Claim) -> tuple[tuple[CitationCheckResult, ...], list[list[EntailmentResult]]]:
        citation = CitationCheckResult(claim=claim, fabricated_labels=frozenset())
        ent = [EntailmentResult(claim=claim, passage_label="[S1]", status=ClaimStatus.ENTAILED)]
        return (citation,), [ent]

    def test_length_bullet_added_when_word_limit_exceeded(self) -> None:
        claim = _claim()
        citations, ents = self._no_issues(claim)
        long_result = LengthCheckResult(
            word_count=500, estimated_tokens=600, max_words=400, max_tokens=700
        )
        repair = build_repair_instructions(citations, ents, length_result=long_result)
        assert "500 words" in repair
        assert "400 words" in repair

    def test_length_bullet_added_when_token_limit_exceeded(self) -> None:
        claim = _claim()
        citations, ents = self._no_issues(claim)
        long_result = LengthCheckResult(
            word_count=100, estimated_tokens=700, max_words=400, max_tokens=600
        )
        repair = build_repair_instructions(citations, ents, length_result=long_result)
        assert "700" in repair
        assert "600" in repair

    def test_no_length_bullet_when_within_limits(self) -> None:
        claim = _claim()
        citations, ents = self._no_issues(claim)
        ok_result = LengthCheckResult(
            word_count=100, estimated_tokens=150, max_words=400, max_tokens=600
        )
        repair = build_repair_instructions(citations, ents, length_result=ok_result)
        assert repair == ""

    def test_no_length_bullet_when_result_is_none(self) -> None:
        claim = _claim()
        citations, ents = self._no_issues(claim)
        repair = build_repair_instructions(citations, ents, length_result=None)
        assert repair == ""

    def test_length_bullet_combined_with_other_issues(self) -> None:
        claim = _claim(text="Bad claim.", citations=("[S99]",))
        citation = CitationCheckResult(claim=claim, fabricated_labels=frozenset({"[S99]"}))
        ent = [EntailmentResult(claim=claim, passage_label="[S99]", status=ClaimStatus.NOT_SUPPORTED)]
        long_result = LengthCheckResult(
            word_count=500, estimated_tokens=700, max_words=400, max_tokens=600
        )
        repair = build_repair_instructions(
            (citation,), [ent], length_result=long_result
        )
        assert "[S99]" in repair
        assert "500 words" in repair
