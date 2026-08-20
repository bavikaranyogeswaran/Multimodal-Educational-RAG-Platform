"""Port for checking an answer against the claims it was built from."""

from __future__ import annotations

from typing import Protocol

from app.domain.enums import AnswerFidelity
from app.domain.models.generation import GeneratedAnswer


class AnswerFaithfulnessPort(Protocol):
    """Check whether the prose shown to the student says only what its claims carry.

    Separate from `ClaimEntailmentPort`, which asks whether a claim is supported by the
    passage it cites. This asks the question that remains once every claim has passed:
    the student reads the `answer` field, not the claims, and an answer can assert
    something in prose that none of its claims established while every claim-level check
    still passes.

    The comparison is deliberately answer-against-claims rather than answer-against-
    passages. The claims have already been checked against the passages, so an answer
    covered by its claims is covered by the evidence through them — and checking whole
    prose against one passage at a time would flag ordinary connective writing as
    unsupported.
    """

    async def check_answer(self, answer: GeneratedAnswer) -> AnswerFidelity: ...
