"""Unit tests for the grounded-answer domain types and parser."""

from __future__ import annotations

import json

import pytest

from app.domain.errors import GenerationParseError, InvariantViolationError
from app.domain.models.generation import Claim, GeneratedAnswer, parse_generated_answer

# ---------------------------------------------------------------------------
# Claim construction
# ---------------------------------------------------------------------------


class TestClaim:
    def test_valid_claim(self) -> None:
        c = Claim(text="Backpropagation computes gradients.", citations=("S1",))
        assert c.text == "Backpropagation computes gradients."
        assert c.citations == ("S1",)

    def test_multiple_citations(self) -> None:
        c = Claim(text="It is used in deep learning.", citations=("S1", "S2", "S3"))
        assert len(c.citations) == 3

    def test_blank_text_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="text"):
            Claim(text="   ", citations=("S1",))

    def test_empty_text_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="text"):
            Claim(text="", citations=("S1",))

    def test_no_citations_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="citations"):
            Claim(text="Some fact.", citations=())

    def test_blank_citation_label_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="citation"):
            Claim(text="Some fact.", citations=("S1", "   "))

    def test_frozen(self) -> None:
        c = Claim(text="Fact.", citations=("S1",))
        with pytest.raises(AttributeError):
            c.text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GeneratedAnswer construction
# ---------------------------------------------------------------------------


class TestGeneratedAnswer:
    def test_valid_answer_with_claims(self) -> None:
        claims = (Claim(text="Fact.", citations=("S1",)),)
        a = GeneratedAnswer(answer="Some explanation.", claims=claims)
        assert a.answer == "Some explanation."
        assert a.insufficient_evidence is False

    def test_insufficient_evidence_with_empty_claims(self) -> None:
        a = GeneratedAnswer(
            answer="The passages do not cover this.",
            claims=(),
            insufficient_evidence=True,
        )
        assert a.claims == ()
        assert a.insufficient_evidence is True

    def test_blank_answer_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="answer"):
            GeneratedAnswer(answer="  ", claims=(Claim(text="Fact.", citations=("S1",)),))

    def test_empty_answer_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="answer"):
            GeneratedAnswer(answer="", claims=(Claim(text="Fact.", citations=("S1",)),))

    def test_empty_claims_without_insufficient_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="claims"):
            GeneratedAnswer(answer="An answer.", claims=(), insufficient_evidence=False)

    def test_frozen(self) -> None:
        a = GeneratedAnswer(
            answer="Answer.", claims=(Claim(text="Fact.", citations=("S1",)),)
        )
        with pytest.raises(AttributeError):
            a.answer = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(**overrides: object) -> str:
    base: dict[str, object] = {
        "answer": "Backpropagation computes the gradient of the loss function.",
        "claims": [{"text": "Backpropagation computes gradients.", "citations": ["S1"]}],
        "insufficient_evidence": False,
    }
    base.update(overrides)
    return json.dumps(base)


def _claim_raw(
    *, text: str = "Some fact.", citations: list[str] | None = None
) -> dict[str, object]:
    return {"text": text, "citations": citations if citations is not None else ["S1"]}


# ---------------------------------------------------------------------------
# parse_generated_answer — valid inputs
# ---------------------------------------------------------------------------


class TestParseGeneratedAnswerValid:
    def test_full_valid_response(self) -> None:
        ga = parse_generated_answer(_raw())
        assert ga.answer == "Backpropagation computes the gradient of the loss function."
        assert len(ga.claims) == 1
        assert ga.claims[0].text == "Backpropagation computes gradients."
        assert ga.claims[0].citations == ("S1",)
        assert ga.insufficient_evidence is False

    def test_insufficient_evidence_response(self) -> None:
        raw = json.dumps({
            "answer": "The provided material does not discuss this topic.",
            "claims": [],
            "insufficient_evidence": True,
        })
        ga = parse_generated_answer(raw)
        assert ga.insufficient_evidence is True
        assert ga.claims == ()

    def test_multiple_claims_and_citations(self) -> None:
        raw = json.dumps({
            "answer": "An answer with multiple claims.",
            "claims": [
                {"text": "First fact.", "citations": ["S1", "S2"]},
                {"text": "Second fact.", "citations": ["S3"]},
            ],
            "insufficient_evidence": False,
        })
        ga = parse_generated_answer(raw)
        assert len(ga.claims) == 2
        assert ga.claims[0].citations == ("S1", "S2")
        assert ga.claims[1].citations == ("S3",)

    def test_extra_top_level_keys_tolerated(self) -> None:
        raw = json.dumps({
            "answer": "An answer.",
            "claims": [{"text": "Fact.", "citations": ["S1"]}],
            "insufficient_evidence": False,
            "chain_of_thought": "I thought about this...",
            "confidence": 0.9,
        })
        ga = parse_generated_answer(raw)
        assert ga.answer == "An answer."

    def test_extra_keys_inside_claim_tolerated(self) -> None:
        raw = json.dumps({
            "answer": "An answer.",
            "claims": [{"text": "Fact.", "citations": ["S1"], "reasoning": "step 1"}],
            "insufficient_evidence": False,
        })
        ga = parse_generated_answer(raw)
        assert ga.claims[0].text == "Fact."

    def test_whitespace_stripped_from_answer(self) -> None:
        raw = json.dumps({
            "answer": "  An answer.  ",
            "claims": [{"text": "Fact.", "citations": ["S1"]}],
            "insufficient_evidence": False,
        })
        ga = parse_generated_answer(raw)
        assert ga.answer == "An answer."

    def test_whitespace_stripped_from_claim_text(self) -> None:
        raw = json.dumps({
            "answer": "An answer.",
            "claims": [{"text": "  A claim.  ", "citations": ["S1"]}],
            "insufficient_evidence": False,
        })
        ga = parse_generated_answer(raw)
        assert ga.claims[0].text == "A claim."

    def test_whitespace_stripped_from_citation_label(self) -> None:
        raw = json.dumps({
            "answer": "An answer.",
            "claims": [{"text": "A claim.", "citations": [" S1 "]}],
            "insufficient_evidence": False,
        })
        ga = parse_generated_answer(raw)
        assert ga.claims[0].citations == ("S1",)

    def test_missing_claims_key_defaults_to_empty_when_insufficient(self) -> None:
        raw = json.dumps({
            "answer": "The material does not discuss this.",
            "insufficient_evidence": True,
        })
        ga = parse_generated_answer(raw)
        assert ga.claims == ()
        assert ga.insufficient_evidence is True

    def test_missing_insufficient_evidence_defaults_to_false(self) -> None:
        raw = json.dumps({
            "answer": "An answer.",
            "claims": [{"text": "Fact.", "citations": ["S1"]}],
        })
        ga = parse_generated_answer(raw)
        assert ga.insufficient_evidence is False


# ---------------------------------------------------------------------------
# parse_generated_answer — invalid inputs
# ---------------------------------------------------------------------------


class TestParseGeneratedAnswerInvalid:
    def test_malformed_json_raises(self) -> None:
        with pytest.raises(GenerationParseError, match="not valid JSON"):
            parse_generated_answer("{answer: missing quotes}")

    def test_json_array_raises(self) -> None:
        with pytest.raises(GenerationParseError, match="JSON object"):
            parse_generated_answer("[1, 2, 3]")

    def test_json_string_scalar_raises(self) -> None:
        with pytest.raises(GenerationParseError, match="JSON object"):
            parse_generated_answer('"just a string"')

    def test_missing_answer_field_raises(self) -> None:
        raw = json.dumps({"claims": [], "insufficient_evidence": True})
        with pytest.raises(GenerationParseError, match="answer"):
            parse_generated_answer(raw)

    def test_answer_wrong_type_raises(self) -> None:
        raw = json.dumps({"answer": 42, "claims": [], "insufficient_evidence": True})
        with pytest.raises(GenerationParseError, match="answer"):
            parse_generated_answer(raw)

    def test_blank_answer_raises(self) -> None:
        raw = json.dumps({
            "answer": "   ",
            "claims": [{"text": "Fact.", "citations": ["S1"]}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError, match="answer"):
            parse_generated_answer(raw)

    def test_claims_not_a_list_raises(self) -> None:
        raw = json.dumps(
            {"answer": "Answer.", "claims": "not a list", "insufficient_evidence": True}
        )
        with pytest.raises(GenerationParseError, match="'claims'"):
            parse_generated_answer(raw)

    def test_claim_not_a_dict_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": ["not an object"],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError, match="claim 0"):
            parse_generated_answer(raw)

    def test_claim_missing_text_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"citations": ["S1"]}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError, match="text"):
            parse_generated_answer(raw)

    def test_claim_blank_text_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "  ", "citations": ["S1"]}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError, match="text"):
            parse_generated_answer(raw)

    def test_claim_citations_not_a_list_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "Fact.", "citations": "S1"}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError, match="'citations'"):
            parse_generated_answer(raw)

    def test_claim_empty_citations_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "Fact.", "citations": []}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError):
            parse_generated_answer(raw)

    def test_blank_citation_label_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "Fact.", "citations": [" "]}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError):
            parse_generated_answer(raw)

    def test_citation_label_not_string_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "Fact.", "citations": [1]}],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError):
            parse_generated_answer(raw)

    def test_insufficient_evidence_wrong_type_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [],
            "insufficient_evidence": "yes",
        })
        with pytest.raises(GenerationParseError, match="insufficient_evidence"):
            parse_generated_answer(raw)

    def test_non_empty_claims_with_insufficient_evidence_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [{"text": "Fact.", "citations": ["S1"]}],
            "insufficient_evidence": True,
        })
        with pytest.raises(GenerationParseError):
            parse_generated_answer(raw)

    def test_empty_claims_without_insufficient_raises(self) -> None:
        raw = json.dumps({
            "answer": "Answer.",
            "claims": [],
            "insufficient_evidence": False,
        })
        with pytest.raises(GenerationParseError):
            parse_generated_answer(raw)
