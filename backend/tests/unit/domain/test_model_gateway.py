"""Model gateway port tests.

Covers:
  1. ModelProfile construction — all invariants
  2. ModelProfile helper methods
  3. Typed stubs satisfying all three protocols — verified by mypy at type-check time
"""

from __future__ import annotations

import pytest

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import InvariantViolationError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.models.entities import GenerationUsage
from app.domain.ports.model_gateway import (
    ModelGatewayPort,
    ModelProfile,
    MultimodalCapability,
    TextGenerationCapability,
    TokenStream,
)


def _profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = {
        "model_key": "ollama/gemma3:4b-instruct-q4_K_M",
        "provider": "ollama",
        "tasks": frozenset({ModelTask.ANSWER_GENERATION, ModelTask.QUERY_REWRITE}),
        "data_boundary": DataBoundary.LOCAL,
        "context_tokens": 8192,
        "max_output_tokens": 2048,
    }
    return ModelProfile(**{**defaults, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ModelProfile — construction invariants
# ---------------------------------------------------------------------------


class TestModelProfileConstruction:
    def test_valid_profile_builds_without_error(self) -> None:
        p = _profile()
        assert p.model_key == "ollama/gemma3:4b-instruct-q4_K_M"
        assert p.provider == "ollama"
        assert p.supports_images is False

    def test_blank_model_key_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="model_key"):
            _profile(model_key="   ")

    def test_empty_model_key_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="model_key"):
            _profile(model_key="")

    def test_blank_provider_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="provider"):
            _profile(provider="  ")

    def test_empty_tasks_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="at least one"):
            _profile(tasks=frozenset())

    def test_context_tokens_zero_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="context_tokens"):
            _profile(context_tokens=0)

    def test_context_tokens_negative_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="context_tokens"):
            _profile(context_tokens=-1)

    def test_max_output_tokens_zero_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="max_output_tokens"):
            _profile(max_output_tokens=0)

    def test_visual_question_without_supports_images_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="VISUAL_QUESTION"):
            _profile(
                tasks=frozenset({ModelTask.VISUAL_QUESTION}),
                supports_images=False,
            )

    def test_visual_question_with_supports_images_is_accepted(self) -> None:
        p = _profile(
            tasks=frozenset({ModelTask.VISUAL_QUESTION, ModelTask.ANSWER_GENERATION}),
            supports_images=True,
        )
        assert p.supports_images is True

    def test_supports_images_without_visual_question_is_allowed(self) -> None:
        # The invariant only enforces VISUAL_QUESTION → supports_images, not the reverse.
        p = _profile(supports_images=True)
        assert p.supports_images is True


# ---------------------------------------------------------------------------
# ModelProfile — helper methods
# ---------------------------------------------------------------------------


class TestModelProfileMethods:
    def test_supports_task_true_for_declared_task(self) -> None:
        p = _profile(tasks=frozenset({ModelTask.ANSWER_GENERATION}))
        assert p.supports_task(ModelTask.ANSWER_GENERATION) is True

    def test_supports_task_false_for_undeclared_task(self) -> None:
        p = _profile(tasks=frozenset({ModelTask.ANSWER_GENERATION}))
        assert p.supports_task(ModelTask.QUIZ_GENERATION) is False

    def test_local_boundary_accepts_private_content(self) -> None:
        p = _profile(data_boundary=DataBoundary.LOCAL)
        assert p.can_accept_private_content() is True

    def test_third_party_boundary_does_not_accept_private_content(self) -> None:
        p = _profile(data_boundary=DataBoundary.THIRD_PARTY)
        assert p.can_accept_private_content() is False

    def test_profile_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        p = _profile()
        with pytest.raises(FrozenInstanceError):
            p.provider = "openai"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Typed stubs — mypy verifies protocol satisfaction at type-check time.
# ---------------------------------------------------------------------------

_TEXT_PROFILE = _profile()
_MULTIMODAL_PROFILE = _profile(
    tasks=frozenset({ModelTask.VISUAL_QUESTION, ModelTask.ANSWER_GENERATION}),
    supports_images=True,
)


class _StubTokenStream:
    def __aiter__(self) -> "_StubTokenStream":
        return self

    async def __anext__(self) -> str:
        raise StopAsyncIteration

    @property
    def usage(self) -> GenerationUsage | None:
        return None


class _StubTextGenerationCapability:
    @property
    def profile(self) -> ModelProfile:
        return _TEXT_PROFILE

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        return _StubTokenStream()  # type: ignore[return-value]


class _StubMultimodalCapability:
    @property
    def profile(self) -> ModelProfile:
        return _MULTIMODAL_PROFILE

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        return _StubTokenStream()  # type: ignore[return-value]

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        raise NotImplementedError


class _StubModelGatewayPort:
    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        raise NotImplementedError

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        return _StubTokenStream()  # type: ignore[return-value]

    def profile_for(self, task: ModelTask) -> ModelProfile:
        raise NotImplementedError


# Mypy-checked assignments — fail at type-check time if a stub is incomplete.
_text_gen: TextGenerationCapability = _StubTextGenerationCapability()
_multimodal: MultimodalCapability = _StubMultimodalCapability()
_gateway: ModelGatewayPort = _StubModelGatewayPort()


class TestCapabilityProtocolCompliance:
    @pytest.mark.parametrize("stub", [
        _StubTextGenerationCapability,
        _StubMultimodalCapability,
        _StubModelGatewayPort,
    ])
    def test_stub_is_instantiable(self, stub: type) -> None:
        assert stub() is not None
