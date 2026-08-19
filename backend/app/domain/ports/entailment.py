"""Port for claim-level semantic entailment checking."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import Claim
from app.domain.models.validation import EntailmentResult


class ClaimEntailmentPort(Protocol):
    """Check whether each citation a claim makes is semantically supported by its passage.

    Returns one EntailmentResult per (claim, cited passage) pair. The caller aggregates
    these with `aggregate_claim_status` to get the overall ClaimStatus for the claim.
    Only passages whose labels survived the citation existence check should be passed —
    fabricated labels have no passage to check against.
    """

    async def check_claim(
        self,
        claim: Claim,
        passages: Sequence[LabeledPassage],
    ) -> tuple[EntailmentResult, ...]: ...
