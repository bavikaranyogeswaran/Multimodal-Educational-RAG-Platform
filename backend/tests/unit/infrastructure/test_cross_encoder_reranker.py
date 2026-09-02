"""Tests for CrossEncoderReranker.

sentence-transformers is an optional ML dependency not installed in the test
environment. Every test uses sys.modules injection to supply a mock
CrossEncoder so the lazy import inside __init__ resolves without the real
package. numpy is also absent, so predict's return value is a MagicMock whose
.tolist() method returns the desired float list.

Coverage:
  - CrossEncoder is constructed with model_id and device
  - rerank() with empty candidates returns [] without calling predict
  - predict receives [[query, candidate], ...] pairs for each candidate
  - batch_size is forwarded to predict
  - show_progress_bar=False is always passed
  - scores are returned in the same order as candidates
  - result is a sequence of floats matching candidate count
  - ImportError on construction gives an actionable install hint
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.reranking.cross_encoder import CrossEncoderReranker

_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
_DEVICE = "cpu"
_BATCH = 4


def _mock_predict(scores: list[float]) -> MagicMock:
    """Simulate a numpy ndarray whose .tolist() returns `scores`."""
    result = MagicMock()
    result.tolist.return_value = scores
    return result


def _build_reranker(
    scores: list[float],
    *,
    model_id: str = _MODEL_ID,
    device: str = _DEVICE,
    batch_size: int = _BATCH,
) -> tuple[CrossEncoderReranker, MagicMock]:
    """Construct CrossEncoderReranker with sentence_transformers mocked."""
    mock_model = MagicMock()
    mock_model.predict.return_value = _mock_predict(scores)

    mock_st = MagicMock()
    mock_st.CrossEncoder.return_value = mock_model

    sys.modules["sentence_transformers"] = mock_st
    try:
        reranker = CrossEncoderReranker(model_id=model_id, device=device, batch_size=batch_size)
    finally:
        del sys.modules["sentence_transformers"]

    return reranker, mock_model


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_cross_encoder_constructed_with_model_id(self) -> None:
        mock_model = MagicMock()
        mock_st = MagicMock()
        mock_st.CrossEncoder.return_value = mock_model

        sys.modules["sentence_transformers"] = mock_st
        try:
            CrossEncoderReranker(model_id=_MODEL_ID, device=_DEVICE, batch_size=4)
        finally:
            del sys.modules["sentence_transformers"]

        mock_st.CrossEncoder.assert_called_once_with(_MODEL_ID, device=_DEVICE)

    def test_import_error_raises_with_install_hint(self) -> None:
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="uv sync --group ml"):
                CrossEncoderReranker(model_id=_MODEL_ID, device=_DEVICE, batch_size=4)


# ---------------------------------------------------------------------------
# Empty candidates
# ---------------------------------------------------------------------------


class TestEmptyCandidates:
    async def test_returns_empty_list_immediately(self) -> None:
        reranker, mock_model = _build_reranker([])
        result = await reranker.rerank("what is entropy?", [])
        assert list(result) == []

    async def test_predict_not_called_for_empty_candidates(self) -> None:
        reranker, mock_model = _build_reranker([])
        await reranker.rerank("what is entropy?", [])
        mock_model.predict.assert_not_called()


# ---------------------------------------------------------------------------
# Predict call arguments
# ---------------------------------------------------------------------------


class TestPredictArguments:
    async def test_pairs_are_query_candidate_tuples(self) -> None:
        reranker, mock_model = _build_reranker([0.9, 0.3])
        mock_model.predict.return_value = _mock_predict([0.9, 0.3])

        await reranker.rerank("gradient descent", ["passage A", "passage B"])

        pairs = mock_model.predict.call_args[0][0]
        assert pairs == [["gradient descent", "passage A"], ["gradient descent", "passage B"]]

    async def test_batch_size_forwarded_to_predict(self) -> None:
        reranker, mock_model = _build_reranker([0.5], batch_size=16)
        mock_model.predict.return_value = _mock_predict([0.5])

        await reranker.rerank("q", ["c"])

        kwargs = mock_model.predict.call_args[1]
        assert kwargs["batch_size"] == 16

    async def test_progress_bar_disabled(self) -> None:
        reranker, mock_model = _build_reranker([0.5])
        mock_model.predict.return_value = _mock_predict([0.5])

        await reranker.rerank("q", ["c"])

        kwargs = mock_model.predict.call_args[1]
        assert kwargs["show_progress_bar"] is False

    async def test_query_is_always_first_element_of_pair(self) -> None:
        reranker, mock_model = _build_reranker([0.7, 0.4, 0.1])
        mock_model.predict.return_value = _mock_predict([0.7, 0.4, 0.1])

        query = "explain backpropagation"
        await reranker.rerank(query, ["A", "B", "C"])

        pairs = mock_model.predict.call_args[0][0]
        assert all(pair[0] == query for pair in pairs)


# ---------------------------------------------------------------------------
# Return values
# ---------------------------------------------------------------------------


class TestReturnValues:
    async def test_scores_returned_in_candidate_order(self) -> None:
        reranker, mock_model = _build_reranker([0.9, 0.1, 0.5])
        mock_model.predict.return_value = _mock_predict([0.9, 0.1, 0.5])

        result = await reranker.rerank("q", ["high", "low", "mid"])

        assert list(result) == [0.9, 0.1, 0.5]

    async def test_result_length_matches_candidate_count(self) -> None:
        reranker, mock_model = _build_reranker([0.1, 0.2, 0.3, 0.4])
        mock_model.predict.return_value = _mock_predict([0.1, 0.2, 0.3, 0.4])

        result = await reranker.rerank("q", ["a", "b", "c", "d"])

        assert len(list(result)) == 4

    async def test_single_candidate_returns_single_score(self) -> None:
        reranker, mock_model = _build_reranker([0.75])
        mock_model.predict.return_value = _mock_predict([0.75])

        result = await reranker.rerank("q", ["only passage"])

        assert list(result) == [0.75]
