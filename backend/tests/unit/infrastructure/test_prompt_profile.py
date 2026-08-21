"""Unit tests for PromptProfile and build_chat_messages rendering.

Verifies that the profile abstraction correctly controls acknowledged-exchange
formatting for memory and evidence slots, and that adapters wire the profile
through to the rendering function.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.domain.enums import ModelTask
from app.domain.models.entities import LabeledPassage, ModelRequest
from app.domain.values import UntrustedText
from app.infrastructure.models.providers.prompt import (
    DEFAULT_PROMPT_PROFILE,
    PromptProfile,
    build_chat_messages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_request() -> ModelRequest:
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is osmosis?",
    )


def _request_with_memory() -> ModelRequest:
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is osmosis?",
        pinned_memory=("Student prefers examples.",),
    )


def _request_with_evidence() -> ModelRequest:
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer the question.",
        query="What is osmosis?",
        evidence=(LabeledPassage(label="[S1]", text=UntrustedText("Osmosis is …")),),
    )


# ---------------------------------------------------------------------------
# PromptProfile defaults
# ---------------------------------------------------------------------------


class TestPromptProfileDefaults:
    def test_default_profile_enables_acknowledged_exchange(self) -> None:
        assert PromptProfile().use_acknowledged_exchange is True

    def test_default_prompt_profile_constant_is_default_profile(self) -> None:
        assert DEFAULT_PROMPT_PROFILE == PromptProfile()

    def test_profile_is_frozen(self) -> None:
        profile = PromptProfile()
        with pytest.raises((AttributeError, TypeError)):
            profile.use_acknowledged_exchange = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Memory slot rendering
# ---------------------------------------------------------------------------


class TestMemoryRendering:
    def test_memory_with_exchange_produces_user_then_assistant(self) -> None:
        messages = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=True))
        roles = [m["role"] for m in messages]
        # system + user(memory) + assistant(ack) + user(query)
        assert roles == ["system", "user", "assistant", "user"]

    def test_memory_with_exchange_assistant_message_acknowledges(self) -> None:
        messages = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=True))
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "noted" in assistant_msgs[0]["content"].lower()

    def test_memory_without_exchange_produces_only_user_message(self) -> None:
        messages = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=False))
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "user"]

    def test_memory_without_exchange_no_assistant_message(self) -> None:
        messages = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=False))
        assert not any(m["role"] == "assistant" for m in messages)

    def test_memory_content_present_regardless_of_exchange(self) -> None:
        with_exchange = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=True))
        without_exchange = build_chat_messages(_request_with_memory(), PromptProfile(use_acknowledged_exchange=False))
        memory_text = "Student prefers examples."
        assert any(memory_text in m["content"] for m in with_exchange)
        assert any(memory_text in m["content"] for m in without_exchange)


# ---------------------------------------------------------------------------
# Evidence slot rendering
# ---------------------------------------------------------------------------


class TestEvidenceRendering:
    def test_evidence_with_exchange_produces_user_then_assistant(self) -> None:
        messages = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=True))
        roles = [m["role"] for m in messages]
        # system + user(evidence) + assistant(ack) + user(query)
        assert roles == ["system", "user", "assistant", "user"]

    def test_evidence_with_exchange_assistant_message_confirms_review(self) -> None:
        messages = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=True))
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "reviewed" in assistant_msgs[0]["content"].lower()

    def test_evidence_without_exchange_produces_only_user_message(self) -> None:
        messages = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=False))
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "user"]

    def test_evidence_without_exchange_no_assistant_message(self) -> None:
        messages = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=False))
        assert not any(m["role"] == "assistant" for m in messages)

    def test_evidence_text_present_regardless_of_exchange(self) -> None:
        with_exchange = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=True))
        without_exchange = build_chat_messages(_request_with_evidence(), PromptProfile(use_acknowledged_exchange=False))
        assert any("Osmosis is" in m["content"] for m in with_exchange)
        assert any("Osmosis is" in m["content"] for m in without_exchange)


# ---------------------------------------------------------------------------
# Slots unaffected by the profile
# ---------------------------------------------------------------------------


class TestProfileNeutralSlots:
    def test_system_message_unaffected_by_exchange_flag(self) -> None:
        with_exchange = build_chat_messages(_bare_request(), PromptProfile(use_acknowledged_exchange=True))
        without_exchange = build_chat_messages(_bare_request(), PromptProfile(use_acknowledged_exchange=False))
        assert with_exchange[0]["role"] == "system"
        assert without_exchange[0]["role"] == "system"
        assert with_exchange[0]["content"] == without_exchange[0]["content"]

    def test_query_always_last_user_message(self) -> None:
        for flag in (True, False):
            messages = build_chat_messages(_bare_request(), PromptProfile(use_acknowledged_exchange=flag))
            assert messages[-1]["role"] == "user"
            assert "osmosis" in messages[-1]["content"].lower()

    def test_default_profile_produces_same_output_as_no_profile_arg(self) -> None:
        req = _request_with_memory()
        with_default = build_chat_messages(req, DEFAULT_PROMPT_PROFILE)
        without_arg = build_chat_messages(req)
        assert with_default == without_arg


# ---------------------------------------------------------------------------
# Profile wired into OllamaModelGateway
# ---------------------------------------------------------------------------


class TestOllamaPromptProfileWiring:
    def test_ollama_uses_default_profile_when_none_passed(self) -> None:
        from app.infrastructure.models.providers.ollama import OllamaModelGateway

        gw = OllamaModelGateway(
            http_client=MagicMock(spec=httpx.AsyncClient),
            model_id="gemma3:4b",
            timeout_seconds=30,
        )
        assert gw._prompt_profile == DEFAULT_PROMPT_PROFILE

    async def test_ollama_custom_profile_changes_message_count(self) -> None:
        from app.infrastructure.models.providers.ollama import OllamaModelGateway

        captured: list[list[dict]] = []

        resp_data = {
            "message": {"content": "ok"},
            "prompt_eval_count": 5,
            "eval_count": 3,
            "done_reason": "stop",
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=resp_data)
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_resp)

        def _capture_and_return(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("json", {}).get("messages", []))
            return mock_resp

        client.post = AsyncMock(side_effect=_capture_and_return)

        profile_no_exchange = PromptProfile(use_acknowledged_exchange=False)
        gw = OllamaModelGateway(
            http_client=client,
            model_id="gemma3:4b",
            timeout_seconds=30,
            prompt_profile=profile_no_exchange,
        )
        req = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="sys",
            safety_rules=(),
            task_instructions="task",
            query="q",
            pinned_memory=("fact",),
        )
        await gw.generate(req)

        # Without exchange: system + user(memory) + user(query) = 3
        # With exchange (default): system + user + assistant(ack) + user(query) = 4
        assert len(captured[0]) == 3


# ---------------------------------------------------------------------------
# Profile wired into OpenAICompatibleGateway
# ---------------------------------------------------------------------------


class TestOpenAICompatPromptProfileWiring:
    def test_openai_compat_uses_default_profile_when_none_passed(self) -> None:
        from app.infrastructure.models.providers.openai_compat import OpenAICompatibleGateway

        gw = OpenAICompatibleGateway(
            http_client=MagicMock(spec=httpx.AsyncClient),
            model_id="gpt-4o",
            timeout_seconds=30,
        )
        assert gw._prompt_profile == DEFAULT_PROMPT_PROFILE

    async def test_openai_compat_custom_profile_changes_message_count(self) -> None:
        from app.infrastructure.models.providers.openai_compat import OpenAICompatibleGateway

        captured: list[list[dict]] = []

        ok_resp = MagicMock(spec=httpx.Response)
        ok_resp.raise_for_status = MagicMock()
        ok_resp.json = MagicMock(return_value={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        })

        client = MagicMock(spec=httpx.AsyncClient)

        async def _capture(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("json", {}).get("messages", []))
            return ok_resp

        client.post = AsyncMock(side_effect=_capture)

        profile_no_exchange = PromptProfile(use_acknowledged_exchange=False)
        gw = OpenAICompatibleGateway(
            http_client=client,
            model_id="gpt-4o",
            timeout_seconds=30,
            prompt_profile=profile_no_exchange,
        )
        req = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="sys",
            safety_rules=(),
            task_instructions="task",
            query="q",
            pinned_memory=("fact",),
        )
        await gw.generate(req)

        # Without exchange: system + user(memory) + user(query) = 3
        assert len(captured[0]) == 3
