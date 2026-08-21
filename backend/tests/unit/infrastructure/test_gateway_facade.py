"""Unit tests for ModelGatewayFacade.

The façade selects the first provider whose profile supports the requested task.
Tests use lightweight stub providers rather than mocking real adapters, so the
routing logic is verified against the same Protocol surface the real adapters expose.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import DataBoundaryViolationError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile, TokenStream
from app.domain.values import UntrustedText
from app.infrastructure.models.gateway import ModelGatewayFacade


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _profile(
    *,
    key: str = "test-model",
    tasks: frozenset[ModelTask] | None = None,
    supports_images: bool = False,
    boundary: DataBoundary = DataBoundary.LOCAL,
) -> ModelProfile:
    return ModelProfile(
        model_key=key,
        provider="test",
        tasks=tasks or frozenset({ModelTask.ANSWER_GENERATION}),
        data_boundary=boundary,
        context_tokens=4096,
        max_output_tokens=512,
        supports_images=supports_images,
    )


def _response(content: str = "ok") -> ModelResponse:
    return ModelResponse(
        model_task=ModelTask.ANSWER_GENERATION,
        model_id="test-model",
        content=UntrustedText(content),
        prompt_tokens=10,
        completion_tokens=5,
        finish_reason="stop",
        latency_ms=1,
    )


def _request(task: ModelTask = ModelTask.ANSWER_GENERATION) -> ModelRequest:
    return ModelRequest(
        model_task=task,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is osmosis?",
    )


class _StubTextProvider:
    """Minimal text provider stub with configurable profile and response."""

    def __init__(
        self,
        profile: ModelProfile,
        response: ModelResponse | None = None,
    ) -> None:
        self._profile = profile
        self._response = response or _response()
        self.generate = AsyncMock(return_value=self._response)
        self._stream: TokenStream = MagicMock(spec=TokenStream)
        self.generate_stream = MagicMock(return_value=self._stream)

    @property
    def profile(self) -> ModelProfile:
        return self._profile


class _StubImageProvider(_StubTextProvider):
    """Stub that also supports image inference."""

    def __init__(self, profile: ModelProfile, response: ModelResponse | None = None) -> None:
        super().__init__(profile, response)
        self.generate_with_image = AsyncMock(return_value=self._response)


# ---------------------------------------------------------------------------
# Construction guard
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_providers_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one provider"):
            ModelGatewayFacade([])


# ---------------------------------------------------------------------------
# Task routing — generate
# ---------------------------------------------------------------------------


class TestTaskRouting:
    async def test_routes_to_first_capable_provider(self) -> None:
        provider = _StubTextProvider(_profile(key="p1"))
        facade = ModelGatewayFacade([provider])
        await facade.generate(_request())
        provider.generate.assert_awaited_once()

    async def test_raises_unsupported_when_no_provider_handles_task(self) -> None:
        provider = _StubTextProvider(
            _profile(tasks=frozenset({ModelTask.QUERY_REWRITE}))
        )
        facade = ModelGatewayFacade([provider])
        with pytest.raises(UnsupportedCapabilityError):
            await facade.generate(_request(ModelTask.ANSWER_GENERATION))

    async def test_skips_incapable_providers_and_picks_first_capable(self) -> None:
        wrong = _StubTextProvider(_profile(key="wrong", tasks=frozenset({ModelTask.QUERY_REWRITE})))
        right = _StubTextProvider(_profile(key="right", tasks=frozenset({ModelTask.ANSWER_GENERATION})))
        facade = ModelGatewayFacade([wrong, right])
        await facade.generate(_request(ModelTask.ANSWER_GENERATION))
        wrong.generate.assert_not_awaited()
        right.generate.assert_awaited_once()

    async def test_first_capable_wins_when_multiple_support_same_task(self) -> None:
        first = _StubTextProvider(_profile(key="first"))
        second = _StubTextProvider(_profile(key="second"))
        facade = ModelGatewayFacade([first, second])
        await facade.generate(_request())
        first.generate.assert_awaited_once()
        second.generate.assert_not_awaited()

    async def test_response_from_selected_provider_is_returned(self) -> None:
        expected = _response("the answer")
        provider = _StubTextProvider(_profile(), response=expected)
        result = await ModelGatewayFacade([provider]).generate(_request())
        assert result.content.value == "the answer"


# ---------------------------------------------------------------------------
# Task routing — profile_for
# ---------------------------------------------------------------------------


class TestProfileFor:
    def test_returns_profile_of_first_capable_provider(self) -> None:
        p1 = _StubTextProvider(_profile(key="p1", tasks=frozenset({ModelTask.QUERY_REWRITE})))
        p2 = _StubTextProvider(_profile(key="p2"))
        facade = ModelGatewayFacade([p1, p2])
        profile = facade.profile_for(ModelTask.ANSWER_GENERATION)
        assert profile.model_key == "p2"

    def test_raises_unsupported_when_no_provider_handles_task(self) -> None:
        provider = _StubTextProvider(_profile(tasks=frozenset({ModelTask.QUERY_REWRITE})))
        facade = ModelGatewayFacade([provider])
        with pytest.raises(UnsupportedCapabilityError):
            facade.profile_for(ModelTask.ANSWER_GENERATION)

    def test_profile_key_matches_selected_provider(self) -> None:
        provider = _StubTextProvider(_profile(key="gemma3:4b"))
        facade = ModelGatewayFacade([provider])
        assert facade.profile_for(ModelTask.ANSWER_GENERATION).model_key == "gemma3:4b"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreamRouting:
    def test_generate_stream_delegates_to_selected_provider(self) -> None:
        provider = _StubTextProvider(_profile())
        facade = ModelGatewayFacade([provider])
        result = facade.generate_stream(_request())
        provider.generate_stream.assert_called_once()
        assert result is provider._stream

    def test_raises_unsupported_when_no_provider_handles_streaming_task(self) -> None:
        provider = _StubTextProvider(_profile(tasks=frozenset({ModelTask.QUERY_REWRITE})))
        facade = ModelGatewayFacade([provider])
        with pytest.raises(UnsupportedCapabilityError):
            facade.generate_stream(_request(ModelTask.ANSWER_GENERATION))


# ---------------------------------------------------------------------------
# Multimodal routing
# ---------------------------------------------------------------------------


class TestMultimodalRouting:
    async def test_routes_image_to_image_capable_provider(self) -> None:
        image_profile = _profile(
            key="vision",
            tasks=frozenset({ModelTask.VISUAL_QUESTION}),
            supports_images=True,
        )
        provider = _StubImageProvider(image_profile)
        facade = ModelGatewayFacade([provider])
        await facade.generate_with_image(_request(ModelTask.VISUAL_QUESTION), b"\x89PNG")
        provider.generate_with_image.assert_awaited_once()

    async def test_raises_unsupported_when_no_provider_supports_images(self) -> None:
        text_only = _StubTextProvider(_profile())
        facade = ModelGatewayFacade([text_only])
        with pytest.raises(UnsupportedCapabilityError):
            await facade.generate_with_image(_request(), b"\x89PNG")

    async def test_text_provider_not_called_for_image_request(self) -> None:
        text_only = _StubTextProvider(_profile(key="text"))
        image_provider = _StubImageProvider(
            _profile(
                key="vision",
                tasks=frozenset({ModelTask.VISUAL_QUESTION}),
                supports_images=True,
            )
        )
        facade = ModelGatewayFacade([text_only, image_provider])
        await facade.generate_with_image(_request(ModelTask.VISUAL_QUESTION), b"\x89PNG")
        text_only.generate.assert_not_awaited()
        image_provider.generate_with_image.assert_awaited_once()

    async def test_image_response_from_provider_is_returned(self) -> None:
        expected = _response("the visual answer")
        image_profile = _profile(
            key="vision",
            tasks=frozenset({ModelTask.VISUAL_QUESTION}),
            supports_images=True,
        )
        provider = _StubImageProvider(image_profile, response=expected)
        result = await ModelGatewayFacade([provider]).generate_with_image(
            _request(ModelTask.VISUAL_QUESTION), b"\x89PNG"
        )
        assert result.content.value == "the visual answer"

    async def test_provider_without_visual_question_task_not_selected_for_image(self) -> None:
        # supports_images=True but VISUAL_QUESTION not in tasks — profile is valid, gateway
        # still skips it because the task check also fails.
        image_only_profile = ModelProfile(
            model_key="image-encoder",
            provider="test",
            tasks=frozenset({ModelTask.ANSWER_GENERATION}),
            data_boundary=DataBoundary.LOCAL,
            context_tokens=4096,
            max_output_tokens=512,
            supports_images=True,
        )
        provider = _StubImageProvider(image_only_profile)
        facade = ModelGatewayFacade([provider])
        with pytest.raises(UnsupportedCapabilityError):
            await facade.generate_with_image(_request(), b"\x89PNG")


# ---------------------------------------------------------------------------
# Privacy pre-flight (§52)
# ---------------------------------------------------------------------------


def _private_request(task: ModelTask = ModelTask.ANSWER_GENERATION) -> ModelRequest:
    """A request that carries student-identifiable content (evidence)."""
    from app.domain.models.entities import LabeledPassage
    from app.domain.values import UntrustedText as _UT
    return ModelRequest(
        model_task=task,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is osmosis?",
        evidence=(LabeledPassage(label="[S1]", text=_UT("Osmosis is...")),),
    )


def _third_party_provider(
    task: ModelTask = ModelTask.ANSWER_GENERATION,
) -> _StubTextProvider:
    return _StubTextProvider(
        ModelProfile(
            model_key="gpt-4o",
            provider="openai",
            tasks=frozenset({task}),
            data_boundary=DataBoundary.THIRD_PARTY,
            context_tokens=128_000,
            max_output_tokens=4_096,
            supports_images=False,
        )
    )


class TestPrivacyPreFlight:
    async def test_private_request_to_local_provider_passes(self) -> None:
        provider = _StubTextProvider(_profile())  # LOCAL by default
        facade = ModelGatewayFacade([provider])
        await facade.generate(_private_request())  # must not raise
        provider.generate.assert_awaited_once()

    async def test_private_request_to_third_party_raises(self) -> None:
        facade = ModelGatewayFacade([_third_party_provider()])
        with pytest.raises(DataBoundaryViolationError):
            await facade.generate(_private_request())

    async def test_non_private_request_to_third_party_passes(self) -> None:
        provider = _third_party_provider()
        facade = ModelGatewayFacade([provider])
        # No evidence, memory or history — not privacy_sensitive
        await facade.generate(_request())
        provider.generate.assert_awaited_once()

    async def test_stream_private_request_to_third_party_raises(self) -> None:
        facade = ModelGatewayFacade([_third_party_provider()])
        with pytest.raises(DataBoundaryViolationError):
            facade.generate_stream(_private_request())

    async def test_stream_private_request_to_local_provider_passes(self) -> None:
        provider = _StubTextProvider(_profile())
        facade = ModelGatewayFacade([provider])
        facade.generate_stream(_private_request())  # must not raise
        provider.generate_stream.assert_called_once()

    async def test_image_request_private_to_third_party_raises(self) -> None:
        image_profile = ModelProfile(
            model_key="gpt-4o",
            provider="openai",
            tasks=frozenset({ModelTask.VISUAL_QUESTION}),
            data_boundary=DataBoundary.THIRD_PARTY,
            context_tokens=128_000,
            max_output_tokens=4_096,
            supports_images=True,
        )
        provider = _StubImageProvider(image_profile)
        facade = ModelGatewayFacade([provider])
        with pytest.raises(DataBoundaryViolationError):
            await facade.generate_with_image(
                _private_request(ModelTask.VISUAL_QUESTION), b"\x89PNG"
            )

    def test_request_with_no_private_slots_is_not_sensitive(self) -> None:
        req = _request()
        assert req.privacy_sensitive is False

    def test_request_with_evidence_is_sensitive(self) -> None:
        assert _private_request().privacy_sensitive is True

    def test_request_with_memory_is_sensitive(self) -> None:
        req = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="You are a tutor.",
            safety_rules=(),
            task_instructions="Answer.",
            query="What is osmosis?",
            pinned_memory=("Student prefers examples.",),
        )
        assert req.privacy_sensitive is True

    def test_request_with_conversation_history_is_sensitive(self) -> None:
        from app.domain.enums import MessageRole
        from app.domain.models.entities import ConversationTurn
        from app.domain.values import UntrustedText as _UT
        req = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="You are a tutor.",
            safety_rules=(),
            task_instructions="Answer.",
            query="What is osmosis?",
            conversation_history=(
                ConversationTurn(role=MessageRole.USER, content=_UT("Earlier.")),
            ),
        )
        assert req.privacy_sensitive is True

    async def test_error_carries_provider_name_and_boundary(self) -> None:
        facade = ModelGatewayFacade([_third_party_provider()])
        with pytest.raises(DataBoundaryViolationError) as exc_info:
            await facade.generate(_private_request())
        assert exc_info.value.provider == "openai"
        assert "third_party" in exc_info.value.boundary
