"""Configuration loads, and its invariants are enforced rather than documented.

Several settings encode a rule that would otherwise be a comment. These tests assert the
rule fails loudly, because a misconfiguration that starts successfully is the one that
reaches production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.configuration.settings import (
    AppSettings,
    ChunkingSettings,
    Environment,
    EvidenceSettings,
    JobSettings,
    ObservabilitySettings,
    RerankerSettings,
    RetrievalSettings,
    Settings,
    StorageSettings,
)

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

SENTINEL = "sentinel-secret-value-must-never-appear"


def _declared_keys(path: Path) -> set[str]:
    """Environment variable names actually assigned in an env file, ignoring prose."""
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=")
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if (match := pattern.match(line.strip()))
    }


def test_settings_load_with_defaults() -> None:
    settings = Settings()

    assert settings.app.environment is Environment.LOCAL
    assert settings.retrieval.rrf_k == 60
    assert settings.embedding.dimension == 384
    assert settings.evidence.max_items == 8
    assert settings.ocr.device == "cpu"


def test_secret_values_never_surface_in_repr_or_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secrets must not surface in logs, tracebacks or serialisation.

    Injects a recognisable value into every secret field and asserts it appears nowhere a
    log line, exception or debug dump could pick it up.
    """
    for var in (
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "DATABASE_URL",
        "STORAGE_ACCESS_KEY_ID",
        "STORAGE_SECRET_ACCESS_KEY",
        "MODEL_OPENAI_COMPATIBLE_API_KEY",
    ):
        monkeypatch.setenv(var, SENTINEL)

    settings = Settings()

    # The value is retrievable deliberately, but only via get_secret_value().
    assert settings.database.url.get_secret_value() == SENTINEL

    for rendering in (
        repr(settings),
        str(settings),
        str(settings.model_dump()),
        settings.model_dump_json(),
    ):
        assert SENTINEL not in rendering


class TestEnvExample:
    def test_exists_and_documents_every_setting_group(self) -> None:
        assert ENV_EXAMPLE.is_file()
        content = ENV_EXAMPLE.read_text(encoding="utf-8-sig")

        for prefix in (
            "APP_",
            "SUPABASE_",
            "DATABASE_",
            "STORAGE_",
            "MODEL_",
            "EMBEDDING_",
            "RERANKER_",
            "OCR_",
            "CHUNKING_",
            "RETRIEVAL_",
            "EVIDENCE_",
            "MULTIHOP_",
            "MEMORY_",
            "JOB_",
            "CACHE_",
            "OBSERVABILITY_",
        ):
            assert prefix in content, f"{prefix} settings are undocumented in .env.example"

    def test_declares_no_absolute_reranker_threshold(self) -> None:
        """Raw cross-encoder scores are not a universal threshold.

        Measured scores were -10.58 for a relevant pair and -11.24 for an irrelevant one;
        an absolute cutoff such as "keep scores above zero" would discard every candidate.
        The knob is deliberately absent so it cannot be reintroduced by accident.
        """
        keys = _declared_keys(ENV_EXAMPLE)

        assert "EVIDENCE_RELATIVE_SCORE_MARGIN" in keys
        offenders = [k for k in keys if "SCORE_THRESHOLD" in k or "ABSOLUTE" in k]
        assert not offenders, (
            f"Absolute score threshold reintroduced: {offenders}. Raw reranker scores are "
            "not comparable across queries; select on relative margin instead."
        )

    def test_every_declared_key_maps_to_a_real_setting(self) -> None:
        """A key in .env.example that no setting reads is silently ignored at runtime.

        Which makes it worse than absent: it looks configured and does nothing.
        """
        known: set[str] = set()
        for _, sub in Settings():
            prefix = type(sub).model_config.get("env_prefix", "")
            known.update(f"{prefix}{field}".upper() for field in type(sub).model_fields)

        unknown = sorted(k for k in _declared_keys(ENV_EXAMPLE) if k not in known)
        assert not unknown, f"Declared in .env.example but read by no setting: {unknown}"

    def test_every_credential_setting_is_documented(self) -> None:
        """A credential missing from .env.example is one a fresh clone will not know to set."""
        declared = _declared_keys(ENV_EXAMPLE)

        for required in (
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "DATABASE_URL",
            "STORAGE_ACCOUNT_ID",
            "STORAGE_ACCESS_KEY_ID",
            "STORAGE_SECRET_ACCESS_KEY",
            "MODEL_OLLAMA_BASE_URL",
        ):
            assert required in declared, f"{required} is undocumented in .env.example"


class TestInvariants:
    def test_signed_url_ttl_is_capped_at_one_hour(self) -> None:
        """A signed URL is the only storage-layer boundary, so it must be short-lived."""
        with pytest.raises(ValidationError, match="capped at one hour"):
            StorageSettings(signed_url_ttl_seconds=7200)

    def test_parent_chunks_must_exceed_child_chunks(self) -> None:
        """Loading a parent must restore context the child did not already carry."""
        with pytest.raises(ValidationError, match="parent_target_tokens"):
            ChunkingSettings(child_max_tokens=1500, parent_target_tokens=1200)

    def test_evidence_bounds_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="max_items"):
            EvidenceSettings(min_items=5, max_items=2)

    def test_expansion_must_leave_room_for_the_original_query(self) -> None:
        """The student's own wording always participates in retrieval."""
        with pytest.raises(ValidationError, match="expansion_max_queries"):
            RetrievalSettings(expansion_variants=4, expansion_max_queries=4)

    def test_lease_must_outlast_two_heartbeats(self) -> None:
        """Otherwise a healthy worker loses its job mid-flight."""
        with pytest.raises(ValidationError, match="heartbeat"):
            JobSettings(lease_seconds=60, heartbeat_interval_seconds=30)

    def test_reranker_cannot_exceed_the_candidate_pool(self) -> None:
        """The reranker cannot score candidates the fusion stage never produced."""
        with pytest.raises(ValidationError, match="CANDIDATE_POOL_SIZE"):
            Settings(
                retrieval=RetrievalSettings(candidate_pool_size=20),
                reranker=RerankerSettings(max_candidates=40),
            )

    def test_production_rejects_logging_private_content(self) -> None:
        """Enabling this in production is a configuration error, not a warning."""
        with pytest.raises(ValidationError, match="must not be logged in production"):
            Settings(
                app=AppSettings(environment=Environment.PRODUCTION),
                observability=ObservabilitySettings(log_prompts=True),
            )


class TestChunking:
    def test_overlap_is_smaller_than_the_target(self) -> None:
        with pytest.raises(ValidationError, match="child_overlap_tokens"):
            ChunkingSettings(child_target_tokens=60, child_overlap_tokens=70)

    def test_default_overlap(self) -> None:
        assert ChunkingSettings().child_overlap_tokens == 70
