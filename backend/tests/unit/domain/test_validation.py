"""Unit tests for the deterministic citation existence validator."""

from __future__ import annotations

import pytest

from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import Claim, GeneratedAnswer
from app.domain.models.validation import CitationCheckResult, check_citation_existence
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
