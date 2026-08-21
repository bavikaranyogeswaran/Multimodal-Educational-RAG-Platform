"""Security gate: private student data must never reach a THIRD_PARTY provider.

The data boundary is the gateway's first line of defence. Before any call is
dispatched, the gateway checks whether the request carries student-identifiable
content — evidence from their documents, personal memory facts, conversation
history — and whether the selected provider is permitted to receive it. If the
provider's data boundary is THIRD_PARTY, the gateway must raise
DataBoundaryViolationError unconditionally.

Three failure modes are gated here:

  1. Evidence (document passages) sent to a THIRD_PARTY provider.
  2. Memory or conversation history sent to a THIRD_PARTY provider.
  3. The fallback chain silently rerouting a private request to a THIRD_PARTY
     provider when the primary provider fails.

Run with: uv run pytest -m "security and gate"
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import DataBoundaryViolationError
from app.domain.models.entities import LabeledPassage, ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile, TokenStream
from app.domain.values import UntrustedText
from app.infrastructure.models.gateway import ModelGatewayFacade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _third_party_profile(
    *,
    key: str = "gpt-4o",
    provider: str = "openai",
    task: ModelTask = ModelTask.ANSWER_GENERATION,
    supports_images: bool = False,
) -> ModelProfile:
    return ModelProfile(
        model_key=key,
        provider=provider,
        tasks=frozenset({task}),
        data_boundary=DataBoundary.THIRD_PARTY,
        context_tokens=128_000,
        max_output_tokens=4_096,
        supports_images=supports_images,
    )


def _local_profile(*, key: str = "gemma3:4b") -> ModelProfile:
    return ModelProfile(
        model_key=key,
        provider="ollama",
        tasks=frozenset({ModelTask.ANSWER_GENERATION}),
        data_boundary=DataBoundary.LOCAL,
        context_tokens=128_000,
        max_output_tokens=4_096,
        supports_images=False,
    )


def _stub_provider(profile: ModelProfile) -> MagicMock:
    response = ModelResponse(
        model_task=ModelTask.ANSWER_GENERATION,
        model_id=profile.model_key,
        content=UntrustedText("ok"),
        prompt_tokens=5,
        completion_tokens=3,
        finish_reason="stop",
        latency_ms=1,
    )
    provider = MagicMock()
    provider.profile = profile
    provider.generate = AsyncMock(return_value=response)
    provider.generate_with_image = AsyncMock(return_value=response)
    provider.generate_stream = MagicMock(return_value=MagicMock(spec=TokenStream))
    return provider


def _request_with_evidence() -> ModelRequest:
    """A request that carries student document passages (evidence)."""
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is photosynthesis?",
        evidence=(LabeledPassage(label="[S1]", text=UntrustedText("Photosynthesis …")),),
    )


def _request_with_memory() -> ModelRequest:
    """A request that carries personal memory facts about the student."""
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is photosynthesis?",
        pinned_memory=("Student is in year 10.",),
    )


def _non_private_request() -> ModelRequest:
    """A request that carries no student-identifiable content."""
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is photosynthesis?",
    )


# ---------------------------------------------------------------------------
# Gate: evidence must not reach a THIRD_PARTY provider
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_evidence_to_third_party_provider_raises_data_boundary_violation() -> None:
    """Document passages may not be forwarded to a provider outside the trust boundary.

    Evidence is drawn from the student's uploaded documents. Sending it to a
    THIRD_PARTY provider would disclose private academic material to an external
    service. The gateway must raise DataBoundaryViolationError before making any
    network call.
    """
    provider = _stub_provider(_third_party_profile())
    facade = ModelGatewayFacade([provider])

    with pytest.raises(DataBoundaryViolationError):
        await facade.generate(_request_with_evidence())

    provider.generate.assert_not_awaited()


@pytest.mark.security
@pytest.mark.gate
async def test_memory_to_third_party_provider_raises_data_boundary_violation() -> None:
    """Personal memory facts may not be forwarded to a provider outside the trust boundary.

    Pinned memory and retrieved memory contain identifiable facts about the
    student — preferences, prior knowledge gaps, academic history. Sending them to
    a THIRD_PARTY provider discloses personal information. The gate must hold
    regardless of which private field triggers the check.
    """
    provider = _stub_provider(_third_party_profile())
    facade = ModelGatewayFacade([provider])

    with pytest.raises(DataBoundaryViolationError):
        await facade.generate(_request_with_memory())

    provider.generate.assert_not_awaited()


@pytest.mark.security
@pytest.mark.gate
async def test_private_streaming_request_to_third_party_raises_data_boundary_violation() -> None:
    """The streaming path enforces the data boundary gate identically to the generate path.

    Streaming returns a token iterator before the request completes. If the gate
    were absent on the streaming path, the caller would not know that private
    content had been sent until after tokens began arriving — at which point
    disclosure has already occurred.
    """
    provider = _stub_provider(_third_party_profile())
    facade = ModelGatewayFacade([provider])

    with pytest.raises(DataBoundaryViolationError):
        facade.generate_stream(_request_with_evidence())

    provider.generate_stream.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_private_image_request_to_third_party_raises_data_boundary_violation() -> None:
    """The multimodal path enforces the data boundary gate identically to the text path."""
    profile = _third_party_profile(
        task=ModelTask.VISUAL_QUESTION, supports_images=True
    )
    provider = _stub_provider(profile)
    facade = ModelGatewayFacade([provider])

    with pytest.raises(DataBoundaryViolationError):
        await facade.generate_with_image(
            _request_with_evidence(), b"\x89PNG"
        )

    provider.generate_with_image.assert_not_awaited()


# ---------------------------------------------------------------------------
# Gate: the fallback chain must not silently reroute private requests
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_privacy_violation_during_fallback_is_fatal_not_rerouted() -> None:
    """A data boundary violation during the fallback chain must not be swallowed.

    When the primary provider fails with a retryable error, the gateway falls
    through to the next capable provider. If that provider is THIRD_PARTY and the
    request is private, raising DataBoundaryViolationError is the only correct
    behaviour — silently rerouting would defeat the purpose of the gate.
    """
    from app.domain.errors import ProviderError

    local_provider = _stub_provider(_local_profile())
    local_provider.generate = AsyncMock(
        side_effect=ProviderError("ollama", "service unavailable", retryable=True)
    )

    third_party_provider = _stub_provider(_third_party_profile())
    facade = ModelGatewayFacade([local_provider, third_party_provider])

    with pytest.raises(DataBoundaryViolationError):
        await facade.generate(_request_with_evidence())

    third_party_provider.generate.assert_not_awaited()


# ---------------------------------------------------------------------------
# Correctness: the gate must not over-block non-private requests
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_non_private_request_to_third_party_is_allowed() -> None:
    """A gate that over-blocks is as dangerous as one that under-blocks.

    System prompts, task instructions, and the raw query contain no student-
    identifiable content. Blocking them would prevent legitimate use of external
    providers for tasks that carry no privacy risk.
    """
    provider = _stub_provider(_third_party_profile())
    facade = ModelGatewayFacade([provider])

    await facade.generate(_non_private_request())

    provider.generate.assert_awaited_once()
