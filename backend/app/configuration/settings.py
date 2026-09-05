"""Typed application configuration.

Every tuning constant in the retrieval, evidence, chunking, memory and job pipelines lives
here rather than as a literal in application code. Reranker thresholds and evidence limits
have to be calibrated against evaluation data later, and that is impossible if they are
scattered through the codebase.

Configuration is read once at the composition root and injected. Domain and application code
receive values as parameters; they never import this module, or the inward dependency rule
would be violated.

Secrets are `SecretStr` so they cannot leak through logs, tracebacks or `repr`.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILES = (".env", ".env.local")


def _config(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class AppSettings(BaseSettings):
    model_config = _config("APP_")

    environment: Environment = Environment.LOCAL
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    #: Bumped whenever generation or validation policy changes. Participates in the
    #: answer cache key so a policy change cannot serve a stale answer.
    generation_policy_version: int = 1


# ---------------------------------------------------------------------------
# Supabase — authentication
# ---------------------------------------------------------------------------
class SupabaseSettings(BaseSettings):
    model_config = _config("SUPABASE_")

    url: str = ""
    anon_key: SecretStr = SecretStr("")
    service_role_key: SecretStr = SecretStr("")

    #: JWKS endpoint for asymmetric token verification. Tokens are always verified
    #: against this; the user identity is never read from the request itself.
    jwks_url: str = ""
    jwt_audience: str = "authenticated"
    jwks_cache_seconds: int = 600


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
class DatabaseSettings(BaseSettings):
    model_config = _config("DATABASE_")

    url: SecretStr = SecretStr("")
    pool_size: int = 10
    max_overflow: int = 5
    pool_timeout_seconds: int = 30
    statement_timeout_seconds: int = 30
    echo_sql: bool = False


# ---------------------------------------------------------------------------
# Object storage
# ---------------------------------------------------------------------------
class StorageSettings(BaseSettings):
    model_config = _config("STORAGE_")

    account_id: str = ""
    bucket: str = "tutor-rag"
    access_key_id: SecretStr = SecretStr("")
    secret_access_key: SecretStr = SecretStr("")
    region: str = "auto"

    #: A leaked signed URL must have limited value. Capped at one hour; validated below.
    #: Five minutes is long enough for a browser to fetch and open a large PDF, and short
    #: enough that a URL copied out of a network log is stale before it is useful. The
    #: viewer refreshes ahead of expiry rather than holding one URL for a whole session.
    signed_url_ttl_seconds: int = 300

    #: Page renders feed OCR and are regenerable from the original, so they are cached
    #: rather than stored permanently. Crops are not — they are re-sent to the
    #: multimodal model on every visual question.
    page_render_prefix: str = "cache/renders"
    page_render_ttl_seconds: int = 7 * 24 * 3600
    page_render_dpi: int = 200

    # Permanent storage prefix for figure crops. Crops are re-sent to the
    # multimodal model on every visual question and are not regenerable from the
    # original without re-running ingestion, so they live here, not in the cache.
    crops_prefix: str = "figures"

    max_upload_bytes: int = 200 * 1024 * 1024
    max_upload_pages: int = 1500

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @model_validator(mode="after")
    def _signed_urls_expire_within_an_hour(self) -> StorageSettings:
        if not 60 <= self.signed_url_ttl_seconds <= 3600:
            raise ValueError(
                "STORAGE_SIGNED_URL_TTL_SECONDS must be between 60 and 3600 — a signed URL is "
                "the only storage-layer boundary, so its lifetime is capped at one hour; got "
                f"{self.signed_url_ttl_seconds}"
            )
        return self


# ---------------------------------------------------------------------------
# Model gateway
# ---------------------------------------------------------------------------
class ModelSettings(BaseSettings):
    model_config = _config("MODEL_")

    ollama_base_url: str = "http://127.0.0.1:11434"
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: SecretStr = SecretStr("")

    #: Internal model keys. Application code names these, never a provider model
    #: string — provider names exist only here.
    default_text_model: str = "gemma3:4b"
    default_vision_model: str = "gemma3:4b"
    query_rewrite_model: str = "gemma3:4b"
    faithfulness_model: str = "gemma3:4b"

    #: A local-to-external fallback must raise rather than happen silently. Set false
    #: to forbid external providers entirely.
    allow_external_providers: bool = False

    request_timeout_seconds: int = 120
    max_retries: int = 1  # exactly one retry, then an approved fallback
    warm_models_on_startup: bool = True

    #: Backpressure rather than unbounded queueing. Kept low because the GPU is 6 GB
    #: and a second concurrent generation would not fit alongside the retrieval models.
    max_concurrent_generations: int = 2
    max_concurrent_generations_per_user: int = 1
    generation_queue_size: int = 16

    #: Hard wall on how long one generation may run. Protects against a hung provider
    #: holding a semaphore slot indefinitely.
    generation_timeout_seconds: int = 90

    #: Task-specific output caps.
    max_output_tokens_answer: int = 1024
    max_output_tokens_rewrite: int = 128
    max_output_tokens_expansion: int = 256
    max_output_tokens_summary: int = 2048

    #: What the assembled prompt may cost in total, across every slot. Strictly larger
    #: than the evidence budget alone (EVIDENCE_CONTEXT_TOKEN_BUDGET), which sizes only
    #: the passages — the rest of the prompt has to fit in what is left over.
    prompt_token_budget: int = 8000


# ---------------------------------------------------------------------------
# Embeddings and reranking
# ---------------------------------------------------------------------------
class EmbeddingSettings(BaseSettings):
    model_config = _config("EMBEDDING_")

    model_id: str = "BAAI/bge-small-en-v1.5"
    dimension: int = 384
    device: Literal["cuda", "cpu"] = "cuda"
    batch_size: int = 64
    #: The most the embedding model reads before discarding the end. bge-small-en-v1.5
    #: inherits BERT's 512-token window; a chunk larger than this loses its tail
    #: silently, which is where a paragraph usually says what it was getting at.
    max_input_tokens: int = 512

    #: Changing the model requires a new index version, never an in-place swap:
    #: dimensions and similarity distributions differ between models.
    index_version: int = 1


class RerankerSettings(BaseSettings):
    model_config = _config("RERANKER_")

    model_id: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    device: Literal["cuda", "cpu"] = "cuda"
    batch_size: int = 32
    #: 30–50 candidates depending on hardware.
    max_candidates: int = 40


class OcrSettings(BaseSettings):
    model_config = _config("OCR_")

    #: OCR runs on CPU. The 6 GB GPU cannot host it alongside the answer model, and
    #: ingestion is background work while chat latency is not.
    device: Literal["cuda", "cpu"] = "cpu"
    language: str = "en"

    #: The heavier vision-language fallback fires only on difficult pages — dense
    #: tables, formulas, multiple columns, rotated content, low ordinary confidence.
    #: Exceeding the page fraction on a representative document means the page
    #: classifier is miscalibrated, not that the document is unusual.
    vl_fallback_enabled: bool = True
    vl_confidence_threshold: float = 0.65
    vl_max_page_fraction: float = 0.20

    #: Below this, a page is treated as scanned rather than native-text.
    native_text_coverage_threshold: float = 0.10

    #: A text layer has to be substantial as well as widespread before it is trusted:
    #: some scanners emit a layer covering the page that holds almost nothing.
    min_native_characters: int = 50

    #: Images covering at least this share of a page are large enough to be carrying
    #: text the layer does not have. Below it they are decoration — logos, rules,
    #: bullets — and recognising them costs more than they return.
    image_coverage_threshold: float = 0.15

    #: Vector line work dense enough that the text layer holds the labels and none of
    #: the structure joining them. Placeholder pending calibration against real
    #: material: an ordinary prose page draws almost nothing, a ruled table draws
    #: tens, a schematic draws thousands, and where between those the expensive path
    #: starts paying for itself is not yet known.
    complex_vector_drawing_threshold: int = 400

    @model_validator(mode="after")
    def _coverage_thresholds_are_fractions(self) -> OcrSettings:
        for name in ("native_text_coverage_threshold", "image_coverage_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} is a share of a page and must be between 0 and 1")
        return self


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class ParsingSettings(BaseSettings):
    model_config = _config("PARSING_")

    #: Consecutive text lines closer than this multiple of their own height belong to
    #: the same paragraph. Expressed as a multiple rather than in points so it holds
    #: across type sizes: a gap that separates paragraphs in 10pt body text is ordinary
    #: leading in a 24pt heading.
    paragraph_gap_multiplier: float = 1.6

    #: Text shorter than this after stripping is discarded rather than kept as an
    #: element. Page numbers and stray marks would otherwise each become a paragraph.
    min_element_characters: int = 2

    #: How much larger than its page's body text a run has to be set before it reads as
    #: a heading. A ratio rather than a size, so the rule holds on a slide deck and a
    #: large-print edition as well as on a textbook.
    heading_size_ratio: float = 1.15

    #: Headings are short. Beyond this many lines a run is prose however it is set,
    #: which is what stops an emphasised sentence from being promoted to a title.
    heading_max_lines: int = 3

    #: Share of visible characters that must be mathematical symbols before a run is
    #: treated as a formula rather than as a sentence that happens to contain one.
    formula_symbol_ratio: float = 0.25

    #: An empty vertical strip at least this wide separates columns. Narrower gaps
    #: are the ordinary ragged space between words and at line ends.
    min_gutter_width: float = 24.0

    #: Both sides of a gutter must be at least this wide for it to count. Without it,
    #: the space beside a short centred title reads as a gutter and splits the page
    #: into a column and a sliver.
    min_column_width: float = 90.0

    @model_validator(mode="after")
    def _heading_ratio_exceeds_body_text(self) -> ParsingSettings:
        if self.heading_size_ratio <= 1.0:
            raise ValueError(
                "heading_size_ratio must exceed 1.0 — at or below it, body text is the "
                "same size as the threshold and every paragraph reads as a heading"
            )
        return self

    @model_validator(mode="after")
    def _gap_multiplier_exceeds_one_line(self) -> ParsingSettings:
        if self.paragraph_gap_multiplier <= 1.0:
            raise ValueError(
                "paragraph_gap_multiplier must exceed 1.0 — at or below it, ordinary "
                "line spacing reads as a paragraph break and every line becomes its own"
            )
        return self


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
class ChunkingSettings(BaseSettings):
    model_config = _config("CHUNKING_")

    child_target_tokens: int = 400
    child_max_tokens: int = 700
    child_overlap_tokens: int = 70
    parent_target_tokens: int = 1200
    parent_max_tokens: int = 1500

    @model_validator(mode="after")
    def _sizes_are_ordered(self) -> ChunkingSettings:
        if self.child_max_tokens < self.child_target_tokens:
            raise ValueError("child_max_tokens must be >= child_target_tokens")
        if self.parent_target_tokens <= self.child_max_tokens:
            raise ValueError(
                "parent_target_tokens must exceed child_max_tokens — otherwise loading a "
                "parent restores no context the child did not already carry"
            )
        if self.child_overlap_tokens >= self.child_target_tokens:
            raise ValueError("child_overlap_tokens must be smaller than child_target_tokens")
        return self


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
class RetrievalSettings(BaseSettings):
    model_config = _config("RETRIEVAL_")

    #: Two or three variants, four queries in total, at temperature zero so expansion
    #: is reproducible.
    expansion_variants: int = 3
    expansion_max_queries: int = 4
    expansion_temperature: float = 0.0

    #: The first stage optimises recall; precision comes from reranking afterwards.
    dense_top_k: int = 30
    keyword_top_k: int = 30
    candidate_pool_size: int = 50

    #: Reciprocal rank fusion constant. 60 is the published starting value, not a
    #: value derived for this corpus.
    rrf_k: int = 60

    #: One hop initially. Deeper traversal expands combinatorially and mostly surfaces
    #: weak-relevance edges; multi-step reasoning is handled by sub-question
    #: decomposition instead.
    graph_traversal_depth: int = 1
    graph_max_nodes: int = 50

    @model_validator(mode="after")
    def _pool_is_reachable(self) -> RetrievalSettings:
        if self.expansion_max_queries < self.expansion_variants + 1:
            raise ValueError(
                "expansion_max_queries must leave room for the original query plus variants"
            )
        producible = (self.dense_top_k + self.keyword_top_k) * self.expansion_max_queries
        if self.candidate_pool_size > producible:
            raise ValueError("candidate_pool_size exceeds what the retrievers can produce")
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        return self


# ---------------------------------------------------------------------------
# Evidence selection
# ---------------------------------------------------------------------------
class EvidenceSettings(BaseSettings):
    model_config = _config("EVIDENCE_")

    #: The number of retrieved candidates is not the number sent to the model.
    min_items: int = 1
    max_items: int = 8

    #: Measured cross-encoder scores are low and compressed in absolute terms — a
    #: relevant pair scored -10.58 against -11.24 for an irrelevant one. An absolute
    #: cutoff such as "keep scores above zero" would discard every candidate.
    #: Selection therefore uses the margin relative to the top-ranked candidate.
    #: There is deliberately no absolute-threshold setting: omitting the knob is the
    #: most reliable way to prevent its misuse. Calibrated against the gold set.
    relative_score_margin: float = Field(default=0.10, ge=0.0, le=1.0)

    #: How much of the shorter passage has to sit inside the longer one before the two
    #: are the same evidence. Neighbouring child chunks share their overlap by design,
    #: which is a small fraction of either, so this sits well above that: what it is
    #: meant to catch is a passage retrieved twice by two retrievers, or a child and the
    #: parent it was cut from.
    duplicate_overlap_threshold: float = Field(default=0.8, ge=0.0, le=1.0)

    #: Diversity caps, so one verbose page cannot crowd out every other source.
    max_children_per_parent: int = 2
    max_chunks_per_page: int = 3
    max_chunks_per_document: int = 4

    #: Generative compression can distort values and weaken citation alignment;
    #: extractive sentence selection is the default.
    generative_compression_enabled: bool = False

    #: Token budget the context builder allocates against.
    context_token_budget: int = 6000

    @model_validator(mode="after")
    def _bounds_are_ordered(self) -> EvidenceSettings:
        if self.max_items < self.min_items:
            raise ValueError("max_items must be >= min_items")
        return self


class MultiHopSettings(BaseSettings):
    model_config = _config("MULTIHOP_")

    #: Retrieval must terminate regardless of whether coverage was achieved.
    max_rounds: int = 3
    max_sub_questions: int = 8
    max_documents_per_round: int = 6


# ---------------------------------------------------------------------------
# Generation validation
# ---------------------------------------------------------------------------
class GenerationSettings(BaseSettings):
    model_config = _config("GENERATION_")

    #: Answers longer than this are REPAIRABLE — the model is asked to condense before
    #: the answer reaches the student.
    answer_max_words: int = 400

    #: Character-based token ceiling (length // 4 heuristic). Larger than answer_max_words
    #: to accommodate punctuation-heavy and technical text.
    answer_max_tokens: int = 600

    @model_validator(mode="after")
    def _token_limit_exceeds_word_limit(self) -> GenerationSettings:
        if self.answer_max_tokens < self.answer_max_words:
            raise ValueError(
                "GENERATION_ANSWER_MAX_TOKENS must be >= GENERATION_ANSWER_MAX_WORDS — "
                "tokens are always more numerous than words under sub-word tokenization"
            )
        return self


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class MemorySettings(BaseSettings):
    model_config = _config("MEMORY_")

    #: Compaction runs when a threshold is crossed, never after every message.
    compaction_unsummarized_messages: int = 20
    compaction_unsummarized_tokens: int = 8000
    compaction_active_context_tokens: int = 12000
    compaction_inactivity_hours: int = 24

    #: How much of each memory tier reaches the prompt. History lives in the database
    #: and is queried; it is not pasted in wholesale.
    recent_raw_turns: int = 6
    retrieved_episodes: int = 3
    retrieved_durable_facts: int = 8


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
class JobSettings(BaseSettings):
    model_config = _config("JOB_")

    poll_interval_seconds: float = 2.0
    batch_size: int = 1
    lease_seconds: int = 300
    heartbeat_interval_seconds: int = 30
    max_attempts: int = 3
    backoff_base_seconds: int = 10
    backoff_max_seconds: int = 900

    @model_validator(mode="after")
    def _heartbeat_beats_lease(self) -> JobSettings:
        if self.heartbeat_interval_seconds * 2 >= self.lease_seconds:
            raise ValueError(
                "lease_seconds must be comfortably longer than two heartbeat intervals, "
                "or a healthy worker will have its job reclaimed mid-flight"
            )
        return self


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class CacheSettings(BaseSettings):
    model_config = _config("CACHE_")

    enabled: bool = True
    answer_ttl_seconds: int = 24 * 3600
    retrieval_ttl_seconds: int = 3600
    query_rewrite_ttl_seconds: int = 24 * 3600
    ocr_ttl_seconds: int = 30 * 24 * 3600
    sweep_interval_seconds: int = 3600

    #: Semantic answer caching is explicitly out of the initial version — near-miss
    #: matches would serve an answer built from different evidence.
    semantic_matching_enabled: Literal[False] = False

    #: Bumped when a prompt template changes; participates in the answer cache key.
    prompt_version: int = 1


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
class ObservabilitySettings(BaseSettings):
    model_config = _config("OBSERVABILITY_")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    #: Document text, prompts and model outputs are excluded from logs by default.
    #: Enabling capture must be a deliberate, non-default act, and is refused outright
    #: in production.
    log_prompts: bool = False
    log_document_text: bool = False
    log_model_outputs: bool = False


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore", frozen=True)

    app: Annotated[AppSettings, Field(default_factory=AppSettings)]
    supabase: Annotated[SupabaseSettings, Field(default_factory=SupabaseSettings)]
    database: Annotated[DatabaseSettings, Field(default_factory=DatabaseSettings)]
    storage: Annotated[StorageSettings, Field(default_factory=StorageSettings)]
    model: Annotated[ModelSettings, Field(default_factory=ModelSettings)]
    embedding: Annotated[EmbeddingSettings, Field(default_factory=EmbeddingSettings)]
    reranker: Annotated[RerankerSettings, Field(default_factory=RerankerSettings)]
    ocr: Annotated[OcrSettings, Field(default_factory=OcrSettings)]
    parsing: Annotated[ParsingSettings, Field(default_factory=ParsingSettings)]
    chunking: Annotated[ChunkingSettings, Field(default_factory=ChunkingSettings)]
    retrieval: Annotated[RetrievalSettings, Field(default_factory=RetrievalSettings)]
    evidence: Annotated[EvidenceSettings, Field(default_factory=EvidenceSettings)]
    multihop: Annotated[MultiHopSettings, Field(default_factory=MultiHopSettings)]
    generation: Annotated[GenerationSettings, Field(default_factory=GenerationSettings)]
    memory: Annotated[MemorySettings, Field(default_factory=MemorySettings)]
    job: Annotated[JobSettings, Field(default_factory=JobSettings)]
    cache: Annotated[CacheSettings, Field(default_factory=CacheSettings)]
    observability: Annotated[ObservabilitySettings, Field(default_factory=ObservabilitySettings)]

    @model_validator(mode="after")
    def _prompt_budget_leaves_room_for_more_than_evidence(self) -> Settings:
        if self.model.prompt_token_budget <= self.evidence.context_token_budget:
            raise ValueError(
                "MODEL_PROMPT_TOKEN_BUDGET must exceed EVIDENCE_CONTEXT_TOKEN_BUDGET — "
                "otherwise the passages alone can fill the whole prompt, leaving no room "
                "for the instructions and question the model needs to make sense of them"
            )
        return self

    @model_validator(mode="after")
    def _reranker_pool_is_consistent(self) -> Settings:
        if self.reranker.max_candidates > self.retrieval.candidate_pool_size:
            raise ValueError(
                "RERANKER_MAX_CANDIDATES exceeds RETRIEVAL_CANDIDATE_POOL_SIZE — the "
                "reranker cannot score candidates the fusion stage never produced"
            )
        return self

    @model_validator(mode="after")
    def _production_forbids_verbose_logging(self) -> Settings:
        if self.app.environment is Environment.PRODUCTION:
            obs = self.observability
            if obs.log_prompts or obs.log_document_text or obs.log_model_outputs:
                raise ValueError(
                    "private documents, prompts and model outputs must not be logged in production"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once.

    Injected at the composition root. Domain and application code receive values as
    parameters and never call this.
    """
    return Settings()
