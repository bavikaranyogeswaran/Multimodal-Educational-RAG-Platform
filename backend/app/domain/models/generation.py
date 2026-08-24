"""Structured response from grounded answer generation.

The model is given an output schema instructing it to produce JSON rather than prose.
This module defines the target shape and the parser that converts a raw model response
into a value the validation pipeline can inspect claim by claim. A response that does not
fit the schema is a parse failure, which the caller turns into a repair request or a
rejection — the student never sees a half-formed parse error.

Splitting an answer into claims is what makes validation possible at claim granularity:
an answer can be partially entailed, one claim correct and another not, and only what
the evidence actually supports survives into the final response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.domain.errors import GenerationParseError, InvariantViolationError


@dataclass(frozen=True, slots=True)
class Claim:
    """One factual assertion the model makes, with the passages it rests on.

    A claim without citations is a fabrication: it asserts something but names no source.
    The validator checks every label against the evidence set that was actually sent, so
    an invented label is not merely unhelpful — it is exactly what the fabricated-citation
    gate catches. Both failures begin here, with claims that cannot be constructed without
    at least one label.
    """

    text: str
    citations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvariantViolationError("Claim.text must not be blank")
        if not self.citations:
            raise InvariantViolationError("Claim.citations must contain at least one label")
        if any(not label.strip() for label in self.citations):
            raise InvariantViolationError(
                "every citation label in Claim.citations must not be blank"
            )


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """The model's response to a question, broken into verifiable pieces.

    When the passages do not cover the question, the model sets `insufficient_evidence`
    and leaves `claims` empty. In every other case it must name the source of every fact
    it states, so validation can confirm or deny each one independently.
    """

    answer: str
    claims: tuple[Claim, ...]
    insufficient_evidence: bool = False

    def __post_init__(self) -> None:
        if not self.answer.strip():
            raise InvariantViolationError("GeneratedAnswer.answer must not be blank")
        if not self.insufficient_evidence and not self.claims:
            raise InvariantViolationError(
                "GeneratedAnswer.claims must be non-empty when insufficient_evidence is false"
            )
        if self.insufficient_evidence and self.claims:
            raise InvariantViolationError(
                "GeneratedAnswer.claims must be empty when insufficient_evidence is true"
            )


#: The text that fills the output_schema slot in ModelRequest. Written for the model to
#: read, not for a JSON schema validator — imperative and example-driven. The Ollama
#: adapter renders this under a "[Required output format]" header as a user message, so
#: the model sees it immediately before generating.
OUTPUT_SCHEMA = """\
Respond with a single JSON object only — no text before or after it.

{
  "answer": "Your complete answer in plain prose.",
  "claims": [
    {
      "text": "One factual statement from the answer above.",
      "citations": ["[S1]"]
    }
  ],
  "insufficient_evidence": false
}

- Each claim must cite at least one passage label from the reference material. Use only labels
  that appear beside the passages — no invented or approximated labels.
- Set "insufficient_evidence" to true and "claims" to [] only when the passages do not address
  the question at all. Write what is missing in "answer".
- Do not add, rename, or remove keys."""


def _strip_code_fence(raw: str) -> str:
    """Return the JSON inside a markdown code fence, or the input unchanged.

    Smaller instruction-tuned models wrap JSON in ```json fences however firmly the
    schema asks for a bare object. The fence is a formatting habit, not a malformed
    answer, so it is removed here rather than counted as a parse failure.
    """
    text = raw.strip()
    if not text.startswith("```"):
        return text
    body = text[3:]
    newline = body.find("\n")
    if newline == -1:
        return text
    body = body[newline + 1 :]
    closing = body.rfind("```")
    return body[:closing].strip() if closing != -1 else text


def parse_generated_answer(raw: str) -> GeneratedAnswer:
    """Parse the model's raw string into a GeneratedAnswer.

    Raises GenerationParseError for any failure: malformed JSON, missing or wrongly-typed
    fields, a claim with no citations, or a non-empty claims list paired with
    insufficient_evidence. The caller maps this to a validation decision; it is not
    exposed to the student.

    Extra keys at any level are tolerated — the model may include chain-of-thought fields
    that the schema does not define, and refusing them here would break on every model that
    adds explanatory annotations.
    """
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise GenerationParseError(f"response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise GenerationParseError("response must be a JSON object, not a scalar or array")

    _require_string(data, "answer")
    answer = data["answer"].strip()
    if not answer:
        raise GenerationParseError("'answer' must not be blank")

    claims_raw = data.get("claims", [])
    if not isinstance(claims_raw, list):
        raise GenerationParseError("'claims' must be an array")

    insufficient = data.get("insufficient_evidence", False)
    if not isinstance(insufficient, bool):
        raise GenerationParseError("'insufficient_evidence' must be a boolean")

    claims: list[Claim] = []
    for i, raw_claim in enumerate(claims_raw):
        claims.append(_parse_claim(i, raw_claim))

    try:
        return GeneratedAnswer(
            answer=answer,
            claims=tuple(claims),
            insufficient_evidence=insufficient,
        )
    except InvariantViolationError as exc:
        raise GenerationParseError(str(exc)) from exc


def _parse_claim(i: int, raw_claim: object) -> Claim:
    if not isinstance(raw_claim, dict):
        raise GenerationParseError(f"claim {i} must be a JSON object")
    _require_string(raw_claim, "text", context=f"claim {i}")
    claim_text = raw_claim["text"].strip()
    if not claim_text:
        raise GenerationParseError(f"claim {i}: 'text' must not be blank")

    citations_raw = raw_claim.get("citations", [])
    if not isinstance(citations_raw, list):
        raise GenerationParseError(f"claim {i}: 'citations' must be an array")

    labels: list[str] = []
    for j, label in enumerate(citations_raw):
        if not isinstance(label, str) or not label.strip():
            raise GenerationParseError(
                f"claim {i}, citation {j}: must be a non-empty string"
            )
        labels.append(label.strip())

    try:
        return Claim(text=claim_text, citations=tuple(labels))
    except InvariantViolationError as exc:
        raise GenerationParseError(f"claim {i}: {exc}") from exc


def _require_string(d: dict[str, object], key: str, *, context: str = "") -> None:
    prefix = f"{context}: " if context else ""
    if key not in d:
        raise GenerationParseError(f"{prefix}missing required field '{key}'")
    if not isinstance(d[key], str):
        raise GenerationParseError(f"{prefix}'{key}' must be a string")
