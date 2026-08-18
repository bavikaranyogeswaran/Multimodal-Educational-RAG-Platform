"""Tests for SentenceTransformerEmbedder.

Every other test in this suite embeds with a fake that returns a fixed vector, which
proves the pipeline moves vectors around and nothing about whether the vectors mean
anything. These load the real model, so they are the only place where a claim about
similarity can be made at all.

They run on the CPU rather than the configured CUDA device. What is under test is the
adapter contract — one vector per text, normalised, stable, batched — and none of that
is a property of the hardware. Whether the card is present and usable is the environment
verifier's question, and answering it here would make the suite fail on a machine that is
merely without a GPU.

Where the model cannot be loaded at all these skip rather than fail: an unreachable
download says nothing about whether the adapter is correct.
"""

from __future__ import annotations

import math

import pytest

from app.infrastructure.embeddings.sentence_transformer import SentenceTransformerEmbedder

pytestmark = pytest.mark.slow

_MODEL_ID = "BAAI/bge-small-en-v1.5"
_DIMENSION = 384

#: Passages of the kind the system actually indexes, rather than "hello world" — the
#: similarity claims below only mean something on text that reads like a textbook.
_GRADIENT = (
    "Backpropagation computes the gradient of the loss with respect to each weight by "
    "applying the chain rule backwards through the network."
)
_PHOTOSYNTHESIS = (
    "Photosynthesis converts light energy into chemical energy, storing it in the bonds "
    "of glucose molecules within the chloroplast."
)


@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    try:
        return SentenceTransformerEmbedder(
            model_id=_MODEL_ID, device="cpu", batch_size=8
        )
    except Exception as exc:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"embedding model unavailable: {exc}")


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TestShape:
    def test_the_dimension_matches_what_the_schema_reserves(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """The pgvector column is fixed width. A model of another size cannot be written
        to it at all, so this is the check that a model swap has to pass first."""
        assert embedder.dimension == _DIMENSION

    async def test_one_vector_comes_back_per_text(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        vectors = await embedder.embed_documents([_GRADIENT, _PHOTOSYNTHESIS])
        assert len(vectors) == 2
        assert all(len(vector) == _DIMENSION for vector in vectors)

    async def test_vectors_are_normalised(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """Cosine distance in pgvector assumes it. Un-normalised vectors would rank by
        length as much as by meaning."""
        [vector] = await embedder.embed_documents([_GRADIENT])
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-4)

    async def test_no_texts_means_no_call_and_no_vectors(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        assert await embedder.embed_documents([]) == []


class TestBatching:
    async def test_more_texts_than_the_batch_size_all_come_back(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """The batch size is 8 here and a real ingestion sends hundreds at once. A
        batching bug that dropped the tail would lose the end of every document."""
        texts = [f"{_GRADIENT} Variation number {i}." for i in range(20)]
        vectors = await embedder.embed_documents(texts)
        assert len(vectors) == 20

    async def test_batching_does_not_change_the_vectors(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """A passage means the same thing whoever it was sent alongside."""
        alone = (await embedder.embed_documents([_GRADIENT]))[0]
        crowded = (await embedder.embed_documents([_PHOTOSYNTHESIS, _GRADIENT]))[1]
        assert _cosine(list(alone), list(crowded)) > 0.999


class TestStability:
    async def test_the_same_text_embeds_the_same_way(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """An index built over two runs would otherwise be incoherent with itself."""
        first = (await embedder.embed_documents([_GRADIENT]))[0]
        second = (await embedder.embed_documents([_GRADIENT]))[0]
        assert _cosine(list(first), list(second)) > 0.9999

    async def test_a_query_embeds_as_the_same_vector_as_a_document(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """Queries and passages currently go through one path, so a match is a match in
        one space. Any per-side instruction added later changes exactly this."""
        query = await embedder.embed_query(_GRADIENT)
        [document] = await embedder.embed_documents([_GRADIENT])
        assert _cosine(list(query), list(document)) > 0.9999


class TestMeaning:
    """The only tests here that would notice a model returning confident noise."""

    async def test_a_question_sits_closer_to_its_answer_than_to_another_subject(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        question = await embedder.embed_query("How are gradients computed in a network?")
        related, unrelated = await embedder.embed_documents([_GRADIENT, _PHOTOSYNTHESIS])
        assert _cosine(list(question), list(related)) > _cosine(
            list(question), list(unrelated)
        )

    async def test_a_paraphrase_scores_higher_than_a_different_topic(
        self, embedder: SentenceTransformerEmbedder
    ) -> None:
        """Retrieval depends on wording that does not overlap still matching, which is
        the whole reason for embedding rather than only matching words."""
        original = (await embedder.embed_documents([_GRADIENT]))[0]
        paraphrase, other = await embedder.embed_documents(
            [
                "The chain rule is applied in reverse through the layers to find how each "
                "weight affects the error.",
                _PHOTOSYNTHESIS,
            ]
        )
        assert _cosine(list(original), list(paraphrase)) > _cosine(
            list(original), list(other)
        )
