# Implementation Plan

Phased build plan for the Multimodal Educational Tutor RAG platform, derived from the 68-section
system design specification.

## How to use this document

- Phases run in numerical order unless a dependency says otherwise. Within Phase 0, follow the
  **running order** column, not the step numbers.
- Work proceeds **one step at a time**. The next step is never started automatically.
- Every phase ends in something testable and one commit.
- Section references like `§27` point at the source system design specification.
- The **Decisions log** below is authoritative. If this plan and a memory of a conversation
  disagree, the log wins.

## Status

| | |
|---|---|
| Current phase | **0 — Foundation** |
| Steps complete | 8 of 13 |
| Phases complete | 0 of 21 |
| Last updated | 2 August 2026 |

---

## Standing constraints

These apply to every phase and are not revisited.

- **No Docker.** No containers, no compose files, no container-based local services.
- **No CI/CD.** No GitHub Actions, no pipelines, no automated release workflows.
- **No autonomous agents.** Deterministic orchestration only — no planning loops, no tool-calling
  agents, no LangChain, LangGraph or LlamaIndex (§4).
- **Excluded infrastructure** (§4): text-to-speech, multi-user collaboration, public document
  sharing, microservices, Kubernetes, Kafka, Elasticsearch, Redis, global GraphRAG over every
  query, fine-tuning.
- **Knowledge Base isolation is the security boundary.** Every scoped record carries `user_id` and
  `knowledge_base_id`; every query filters on both before ranking or traversal (§5, §10).
- **Library fidelity.** The §65 stack is used exactly as specified. Substitutions require an ADR.

---

## Decisions log

Every decision made before implementation began, with its rationale. Superseded entries are struck
through and point at what replaced them.

### Delivery

| # | Decision | Rationale |
|---|---|---|
| D-01 | Backend first, frontend after the API contract stabilises | Lowest rework. Retrieval and validation logic is where the risk lives; the UI is a consumer of a settled contract. |
| D-02 | 21 phases, medium granularity | Each phase is one coherent capability ending in something testable — roughly one working session. |
| D-03 | One step executed at a time, user selects each | Tightest review loop; one commit per step; any wrong assumption is caught before it propagates. |
| D-04 | Questions asked before every execution | Decisions are made explicitly rather than assumed. |

### Platform and data

| # | Decision | Rationale |
|---|---|---|
| D-05 | Python 3.12 | Broad wheel availability across `paddlepaddle-gpu`, torch, `pypdfium2`; faster than 3.11. Confirmed in step 0.3 before anything depends on it. |
| D-06 | `uv` + `pyproject.toml` | Fast, reproducible, lockfile-backed; matches the §66 repo structure. |
| D-07 | Supabase Cloud for PostgreSQL and Auth | RLS via `auth.uid()` with zero deviation from §10; no local database install. |
| D-08 | **Cloudflare R2 for object storage**, not Supabase Storage | Supabase free storage is 1 GB with 5 GB/month egress — roughly 5–8 textbooks. R2 gives 10 GB free and **zero egress fees**, which matters because PDF.js re-downloads the original document on every open. One adapter behind `StoragePort`. See ADR-013. |
| D-09 | ~~Neo4j AuraDB Free for the graph projection~~ | Superseded by D-10. |
| D-10 | **PostgreSQL graph adapter; Neo4j deferred** | §34 mandates one-hop traversal, §57 caps views at 30–50 nodes, §22 declares Neo4j derived and rebuildable. One hop is a single join. Removes a datastore, the `SYNC_NEO4J` job, a dual-write consistency surface, and AuraDB Free's 72-hour auto-pause. Scope filters come from the same repository base as everything else, making §64's "graph query without scope filters" test structurally hard to fail. Neo4j adapter added later only if evaluation shows one hop is insufficient — exactly what §34 and §67 prescribe. See ADR-012. |
| D-11 | Alembic owns all schema **including RLS policies** | Single source of truth, reproducible from an empty database. |
| D-12 | `rum` indexes instead of GIN for full-text search | RUM stores lexeme positions and ranks inside the index — faster and better-ordered `ts_rank_cd` than GIN, which matters for §27's exact-term, identifier and formula-notation retrieval. Available on Supabase; still "PostgreSQL full-text search" per §65. See ADR-015. |
| D-13 | Page renders are **TTL cache, not permanent storage** | §60 lists them as stored, but they are only needed transiently for OCR — PDF.js renders client-side from the original for viewing. Cuts permanent storage per textbook from ~175 MB to ~50–100 MB. Table and figure crops stay permanent, since §18 requires re-sending the real crop to the multimodal model. See ADR-014. |
| D-14 | `cache_entries` is **UNLOGGED**, swept by `pg_cron` | UNLOGGED skips WAL entirely — much faster writes, contents lost on crash, which is exactly correct for a cache. |
| D-15 | `pg_partman` designated but not enabled | §67 calls for partitioning as conversation storage grows. `messages` and `conversation_retrieval_chunks` are designed partition-ready from Phase 2. |

### Models and retrieval

| # | Decision | Rationale |
|---|---|---|
| D-16 | NVIDIA GPU available — CUDA builds throughout | PaddleOCR GPU, GPU embeddings and reranker, Ollama GPU offload. |
| D-17 | Ollama and OpenAI-compatible adapters implemented; Gemini and Anthropic interface-only | The OpenAI-compatible adapter covers vLLM and llama.cpp servers for free. The gateway, task router, capability registry, privacy policy and fallback logic are built in full regardless (§48–§54). |
| D-18 | English-only content | `bge-small-en-v1.5` as specified. `preferred_language` and `chunk.language` are populated by detection but no multilingual embedding or OCR path is built. Swapping models later is a config change plus reindex, which the versioned-index design already supports (§20). |
| D-19 | Graph extraction **opt-in per Knowledge Base** | §21 runs an LLM over every parent section — hundreds of local calls for a 400-page textbook. A `graph_enabled` flag gates `BUILD_GRAPH`; enabling it later triggers a backfill job. Ingestion always produces chunks, embeddings and full-text indexes. See ADR-008. |
| D-20 | All §26/§29/§30 tuning numbers become named config values | RRF `k`, top-k ranges, candidate pool size, reranker thresholds and evidence limits are configuration from step 0.6 onward — never literals in code. §30 requires calibration against evaluation data, which is impossible if they are scattered. |
| D-25 | **Async data layer throughout** — SQLAlchemy 2.0 asyncio + psycopg3 async | `FR-RET-17` requires concurrent dense and keyword retrieval across query variants, `FR-PRF-06` requires batching, `FR-GEN-12` requires SSE streaming, `NFR-PERF-19` requires backpressure. All are natural in async and awkward otherwise. Cost accepted: no lazy loading, explicit eager loads, and the worker is async too since it shares repository code. |
| D-26 | **structlog** for logging | `NFR-OBS-01` needs a trace ID on every line without threading it through call signatures; `NFR-OBS-02` needs 16 stage timings as queryable fields rather than formatted strings; `NFR-PRV-03` needs redaction as a central processor rather than a convention at each call site. |

### Quality

| # | Decision | Rationale |
|---|---|---|
| D-21 | Full test and evaluation infrastructure | Pytest unit and integration, the ten §64 security tests with the six zero-tolerance release gates, and a runnable §63 metric harness. Vitest and Playwright in the frontend phases. |
| D-22 | Gold evaluation set hand-built from 2–3 user-supplied PDFs | 40–60 labelled Q/A pairs across every query class with gold chunk and page IDs. Synthetic sets generated from ingested chunks produce optimistic metrics because the questions come from the chunks retrieval will find. |
| D-23 | Latency NFRs derived from the design, recalibrated in Phase 17 | The specification states no targets. Defensible budgets are written into `REQUIREMENTS.md` with their reasoning and replaced by measured p95 once the observability phase runs. |
| D-24 | Four governing documents plus ADRs | `PLAN.md`, `REQUIREMENTS.md`, `USE_CASES.md`, `ARCHITECTURE.md`, `docs/adr/`. |

---

## Findings and open risks

Recorded during planning. Each needs revisiting at the phase noted.

| # | Finding | Impact | Revisit |
|---|---|---|---|
| R-01 | **The local-inference privacy argument does not survive Supabase Cloud.** §52 declares `data_boundary: local` so that "private documents do not need to be sent to external providers", but under this deployment every original PDF, OCR'd chunk, message and memory fact lives on Supabase infrastructure. Only the *prompt* stays local. That is a strictly larger disclosure than the one the design avoids. | Accepted deliberately for convenience. The ADR must say "convenience, accepting third-party custody of the corpus" rather than restating §52's local-first framing. A fully local package (local PostgreSQL + pgvector, local filesystem, JWT auth) remains reachable behind the same ports. | ADR-013, Phase 3–4 |
| R-02 | **`pg_cron` will not prevent Supabase's 7-day pause.** Supabase pauses on absence of *external* database requests; internal cron jobs do not count. CI/CD is excluded, so a scheduled task on the development machine is the reliable keepalive — or manual unpause from the dashboard. | Operational annoyance only; no data loss. `pg_cron` still earns its place for cache sweeping and §44 compaction scheduling. | Phase 0.7, Phase 16 |
| R-03 | **Supabase free tier ceilings are binding, not theoretical.** 500 MB database, 1 GB storage, 5 GB egress/month, 2 projects. Roughly 15–20 textbooks of database and — before D-13 — 5–8 of storage. | D-08 and D-13 push the storage ceiling out substantially. Database remains finite; monitor as conversations and memory accumulate. | Phase 7, Phase 16 |
| R-04 | **Step 0.3 (CUDA + Paddle on Windows) is the highest-risk step in Phase 0.** 3–5 GB of downloads and CUDA/cuDNN version matching. | Isolated deliberately, and sequenced *after* all documentation so a failure cannot block the governing documents. | Phase 0.3 |
| R-05 | **`pgvectorscale`, `pg_search` (ParadeDB BM25) and Apache AGE are not available on Supabase Cloud.** Verified against the 64 approved extensions. | AGE would have been the cleanest graph answer — hence D-10 uses plain tables. `pg_search` would give real BM25; mitigated because §28 fuses via RRF, which consumes ranks rather than scores, and by D-12's `rum` indexes. `pgvectorscale` matters only at millions of vectors. | Phase 2, Phase 9 |
| R-06 | **KùzuDB is dead** — archived October 2025, team acqui-hired. Evaluated and rejected as an embedded graph option. | None; recorded so it is not reconsidered. | — |

---

## Phase 0 — Foundation

Repository, governing documents, tooling and a verified environment.

**Running order is docs-first:** documents land before tooling so everything downstream is checked
against written requirements, and the risky GPU install cannot block them.

| Order | Step | Deliverable | Size | Done |
|---|---|---|---|---|
| 1 | 0.1 | Repository skeleton & git | S | ✅ |
| 2 | 0.13 | `PLAN.md` | S | ✅ |
| 3 | 0.8 | `REQUIREMENTS.md` — functional | L | ✅ |
| 4 | 0.9 | `REQUIREMENTS.md` — NFRs & release gates | M | ✅ |
| 5 | 0.10 | `ARCHITECTURE.md` | M | ✅ |
| 6 | 0.11 | ADR-0001 … ADR-0015 | M | ✅ |
| 7 | 0.12 | `USE_CASES.md` | L | ✅ |
| 8 | 0.2 | Backend uv project & dependency groups | S | ✅ |
| 9 | 0.3 | GPU/ML install & CUDA smoke test | M · risky | ☐ |
| 10 | 0.4 | Backend ruff / mypy / pytest | S | ☐ |
| 11 | 0.5 | Frontend Vite/React/TS scaffold | S | ☐ |
| 12 | 0.6 | Config schema & `.env.example` | M | ☐ |
| 13 | 0.7 | Environment verification script | M | ☐ |

### 0.1 — Repository skeleton & git ✅

- [x] §66 directory tree, minus `Dockerfile`
- [x] `__init__.py` across `backend/app/`, `.gitkeep` elsewhere
- [x] `.gitignore` — secrets, private study material, model weights, build artifacts
- [x] `.gitattributes` — `eol=lf`, binary markers, lockfiles collapsed
- [x] `README.md`
- [x] `git init` on `main`

Additions beyond §66: `backend/scripts/`, `backend/tests/fixtures/`, `backend/alembic/versions/`,
`docs/adr/`. `main.py` and `pyproject.toml` deferred to 0.2.

### 0.13 — `PLAN.md` ✅

- [x] 21-phase plan with checkboxes
- [x] Decisions log D-01 … D-24
- [x] Findings and open risks R-01 … R-06
- [x] Specification coverage matrix

### 0.8 — Functional requirements ✅

- [x] Functional requirements extracted from all 68 sections, each traced to its section and to the
      phase that implements it
- [x] 32 domains: OBJ, AUTH, KB, DOC, JOB, ING, TBL, VIS, CHK, IDX, GRA, CNV, QRY, RET, EVD, CTX,
      GEN, CIT, VAL, HOP, MEM, STU, PRG, MDL, PRF, CCH, VIZ, DEL, API, OBS, EVL, UI
- [x] Coverage table confirming all 68 sections are represented

IDs are **domain-prefixed** (`FR-RET-04`) rather than flat-numbered, so requirements can be inserted
without renumbering and a test or use case referencing one is self-describing. IDs are permanent —
a withdrawn requirement is marked `WITHDRAWN`, never reused.

### 0.9 — Non-functional requirements & release gates ✅

- [x] 11 non-functional domains: SEC, PRV, PERF, REL, DAT, OBS, MNT, POR, CAP, UX, GATE
- [x] Latency budgets derived from a stage-by-stage cost model, with the derivation shown (D-23)
- [x] The six §64 zero-tolerance gates as hard, testable NFRs with named enforcing tests
- [x] Capacity targets: ≤ 100 MB permanent storage and ≤ 40 MB database per textbook (D-13)

Latency and capacity targets are **provisional** until measured in Phase 17. Gates are checked from
the phase that introduces each surface, not deferred to Phase 17.

### 0.10 — `ARCHITECTURE.md` ✅

- [x] §5 design principles as the tie-breakers for later phases
- [x] §6 architecture, §7 runtime processes, §8 layer boundaries and the dependency rule
- [x] Layer contents table stating what each layer must **not** contain
- [x] Ports-and-adapters table — the contract Phase 1 implements
- [x] Storage responsibilities (§60) as amended by D-08 and D-13, with the permanent/regenerable
      split made explicit
- [x] Model Gateway structure (§48–§54) and the versioning model
- [x] §67 scaling path with triggers, `pg_partman` designated (D-15)
- [x] Six Mermaid diagrams: architecture, layer dependency, ingestion, query, scope enforcement,
      model gateway
- [x] Closing section on what the architecture deliberately is not

### 0.11 — Architecture decision records ✅

Each ADR records context, decision, alternatives rejected with reasons, consequences, and — the part
that makes it a decision rather than a belief — **the condition under which it should be revisited**.

- [x] ADR-0001 No PyMuPDF — licensing unsuitable for some distribution models (§14)
- [x] ADR-0002 Self-hosted PaddleOCR, not cloud OCR (§14)
- [x] ADR-0003 No LangChain / LangGraph / LlamaIndex (§65)
- [x] ADR-0004 Selective, not global, GraphRAG (§34)
- [x] ADR-0005 PostgreSQL as job queue and cache, not Redis (§12, §56)
- [x] ADR-0006 Modular monolith, not microservices (§6, §67)
- [x] ADR-0007 HyDE disabled by default (§26)
- [x] ADR-0008 Graph extraction opt-in per Knowledge Base (D-19)
- [x] ADR-0009 Provider-agnostic model gateway (§48)
- [x] ADR-0010 One-hop initial traversal depth (§34)
- [x] ADR-0011 Local model quantization benchmark (§55) — **status: pending results, Phase 16**
- [x] ADR-0012 PostgreSQL graph adapter, Neo4j deferred (D-10) — *deviates from §22, §65*
- [x] ADR-0013 Cloudflare R2 over Supabase Storage (D-08, R-01) — *deviates from §60, §65*
- [x] ADR-0014 Page renders as regenerable cache (D-13) — *deviates from §60*
- [x] ADR-0015 `rum` over GIN for full-text indexes (D-12) — *refines §65*
- [x] `docs/adr/README.md` index with the ADR template

ADR-0013 carries `NFR-PRV-06`: it states plainly that the corpus resides with third parties and that
this is accepted for convenience, not because it is privacy-preserving.

ADR-0011 has an empty results table to be filled in Phase 16, and adds **structured-output validity
rate** to the §55 benchmark measures — quantization degrades schema fidelity before fluency, and
this system validates against schema.

### 0.12 — `USE_CASES.md` ✅

- [x] Template: actor, preconditions, main flow, alternate and exception flows, postconditions,
      acceptance criteria
- [x] **UC-01 … UC-24**, cross-referenced to FRs, NFRs, API endpoints and phases
- [x] All written in full rather than stubbed — the specification supplies enough to complete them
      now, and later phases are checked against them rather than the reverse
- [x] Coverage table mapping all nine §2 student capabilities to use cases
- [x] Release-gate coverage table — every gate exercised by at least one use case

**Two use cases added beyond the planned 22.** UC-23 (ask a relationship or prerequisite question)
and UC-24 (explore the concept graph) close a gap: `FR-OBJ-08` — "explore relationships through a
concept graph" — was a §2 objective with no use case. Numbering was appended, not inserted, so
UC-01 … UC-22 remain stable where earlier phases reference them.

### 0.2 — Backend uv project ✅

- [x] `pyproject.toml` with Python pinned to `==3.12.*`; uv resolved 3.12.13
- [x] `uv.lock` committed
- [x] Four dependency groups installed and verified: `core`, `parsing`, `storage`, `dev`
- [x] `backend/app/main.py` — boots, serves `/health`, lifespan hook reserved for Phase 8 warm-up
- [x] `.venv` confirmed ignored

**The `ml` group is deferred to step 0.3.** `paddlepaddle-gpu` is not resolvable from PyPI — it
requires a CUDA-version-specific index that is not known until the GPU is probed. Declaring it now
would make `uv lock` fail. Step 0.3 adds the group with the correct index configuration.

Runtime dependencies live entirely in `[dependency-groups]` rather than `[project.dependencies]`, so
a failed ML install cannot block work on the rest of the backend.

### 0.3 — GPU/ML dependencies & CUDA smoke test

- [ ] CUDA-matched `paddlepaddle-gpu`, CUDA torch, sentence-transformers
- [ ] `paddle.utils.run_check()` and `torch.cuda.is_available()` pass
- [ ] `bge-small-en-v1.5` and `ms-marco-MiniLM-L6-v2` load and run once on GPU

### 0.4 — Backend code-quality tooling

- [ ] Ruff lint and format
- [ ] mypy strict on `domain/` and `application/`
- [ ] pytest with `pytest-asyncio` and coverage; one passing test

### 0.5 — Frontend scaffold

- [ ] Vite + React + TypeScript, CSS Modules, path aliases
- [ ] TanStack Query, Zod
- [ ] ESLint, Prettier, Vitest, Testing Library; one passing test; dev server boots

### 0.6 — Configuration schema & `.env.example`

- [ ] Pydantic Settings: Supabase URL and keys, database URL, R2 credentials, Ollama base URL
- [ ] The four internal model keys (§51)
- [ ] Retrieval parameters — RRF `k`=60, top-k ranges, candidate pool, reranker thresholds (D-20)
- [ ] Chunking parameters (§19 token targets)
- [ ] Job queue tuning, cache TTLs
- [ ] Fully commented `.env.example`

### 0.7 — Environment verification script

- [ ] Pass/fail table for: Python version · CUDA + torch · Paddle · Ollama reachable with
      `gemma3:4b` · Supabase connectivity, server version and availability of `vector`, `rum`,
      `pg_cron`, `pg_trgm` · R2 bucket round-trip (put → signed GET → delete)

---

## Phase 1 — Clean architecture skeleton & domain layer

Covers §5, §6, §8, §51.

- [ ] All §8 domain entities: `KnowledgeBase`, `Document`, `DocumentElement`, `Chunk`, `Evidence`,
      `Citation`, `Conversation`, `MemoryFact`, `GraphEntity`, `GraphRelationship`,
      `RetrievalPlan`, `ModelRequest`, `ModelResponse`, `ProcessingJob`
- [ ] Domain ports: repositories, `StoragePort`, `DenseRetriever`, `KeywordRetriever`, `GraphPort`,
      `OcrPort`, `PdfParserPort`, `EmbeddingPort`, `RerankerPort`, `ModelGatewayPort`, `CacheStore`,
      `ObservabilityPort`
- [ ] `GraphPort` written to a traversal vocabulary (`neighbors`, `subgraph`), not Cypher, so a
      Neo4j adapter can drop in later without touching callers (D-10)
- [ ] Enums: element types, chunk types, job types, priorities, statuses, query classes, memory
      statuses, validation decisions, coverage classes, requirement levels
- [ ] Value objects: `BoundingBox`, `HeadingPath`, `ScopeContext(user_id, knowledge_base_id)`,
      `TokenBudget`
- [ ] DI container and provider wiring
- [ ] **Import-boundary test** failing if `domain/` imports FastAPI, SQLAlchemy or any provider SDK

## Phase 2 — Data model, migrations & Row-Level Security

Covers §9, §22, §41, §59, §60, and the storage half of §10.

- [ ] Alembic against Supabase; `vector`, `rum`, `pg_cron`, `pg_trgm` extensions
- [ ] All 30 §59 tables
- [ ] Every scoped table carries `user_id` and `knowledge_base_id` (§5)
- [ ] All six §59 composite indexes, HNSW vector indexes, `rum` full-text indexes (D-12)
- [ ] Graph traversal indexes on `graph_relationships` in both directions, plus canonical-name
      lookup on `graph_entities` (D-10)
- [ ] **RLS policies on every scoped table**, keyed to `auth.uid()`
- [ ] `tsvector` generated columns and triggers
- [ ] Versioning columns: `embedding_model_id`, `embedding_dimension`, `embedding_version`,
      `active_index_version`, `active_graph_version`, `graph_version`
- [ ] `cache_entries` UNLOGGED with a partial index on expiry (D-14)
- [ ] `messages` and `conversation_retrieval_chunks` designed partition-ready (D-15)
- [ ] SQLAlchemy models and a scoped repository base that cannot query without a `ScopeContext`
- [ ] Migration round-trip test from an empty database

## Phase 3 — Authentication, Knowledge Base CRUD & API surface

Covers §7 (API process), §10, §61, §62 baseline, §64 first tests.

- [ ] Supabase JWT verification resolving `user_id`
- [ ] KB ownership dependency producing `ScopeContext`; returns 404, not 403, on a foreign KB
- [ ] `/api/v1/knowledge-bases` CRUD including `graph_enabled`, `explanation_level`,
      `preferred_language`, `optional_exam_date`
- [ ] Route skeletons for every §61 endpoint, returning 501 until their phase lands
- [ ] Middleware: trace ID, request logging, exception-to-HTTP mapping, CORS
- [ ] Observability baseline — `TraceContext`, stage timers, `model_invocations` writer
- [ ] Security tests: cross-user KB access, cross-KB access, RLS bypass
- [ ] UC-01, UC-02, UC-03

## Phase 4 — Storage, upload flow, job queue & worker

Covers §7 (worker), §11, §12, §60.

- [ ] R2 adapter behind `StoragePort` — S3-compatible presigned URLs, private bucket,
      `{user_id}/{kb_id}/{document_id}/original.pdf` (D-08)
- [ ] Separate cache prefix with TTL for page renders (D-13)
- [ ] Upload endpoint: MIME, magic-byte, size and page-count validation → `documents` row →
      storage write → `DOCUMENT_INGESTION` job → returns ID and status
- [ ] Status lifecycle `PENDING → PROCESSING → COMPLETED → FAILED → DELETING`
- [ ] Job queue: `FOR UPDATE SKIP LOCKED`, `INTERACTIVE`/`NORMAL`/`BACKGROUND` priorities,
      heartbeat, lease-expiry reclaim, `attempt_count` with exponential backoff, dead-letter
- [ ] Separate worker process sharing domain and application code, graceful shutdown
- [ ] Status polling endpoint with per-stage progress
- [ ] Security tests: signed-URL expiry, upload into a foreign KB
- [ ] UC-04, UC-05

## Phase 5 — PDF parsing, page classification & OCR

Covers §13, §14, §15, §16.

- [ ] `pypdf` metadata and native text · `pdfplumber` layout, blocks, tables · `pypdfium2`
      rendering · Pillow, with OpenCV only where preprocessing is necessary
- [ ] Page classifier → `NATIVE_TEXT` / `SCANNED` / `MIXED` / `COMPLEX`
- [ ] PaddleOCR PP-OCRv6 on GPU as primary, per-region for mixed pages, with confidence
- [ ] PaddleOCR-VL fallback triggered only by §15 conditions
- [ ] Tesseract wired as emergency fallback only
- [ ] Element typing: `HEADING`, `PARAGRAPH`, `LIST`, `TABLE`, `FIGURE`, `CHART`, `DIAGRAM`,
      `FORMULA`, `CAPTION`
- [ ] Reading-order resolution, multi-column handling, `heading_path`
- [ ] Full §16 field set including `processing_method` and `confidence`
- [ ] `OCR_PAGE` jobs, idempotent per-page re-run, renders to the TTL cache prefix
- [ ] Extracted document text marked **untrusted** at extraction time (§38 injection defence)
- [ ] Golden-file parser tests

## Phase 6 — Table, figure, chart & diagram processing

Covers §17, §18.

- [ ] Tables: detect → title and caption → headers, rows, units → crop → JSON → Markdown →
      optional HTML → retrieval-oriented text → bbox, page, confidence
- [ ] Large tables split by row group, **repeating title, headers, units and row labels in every
      group**; rows never embedded headerless
- [ ] Visual objects: crop → caption → surrounding paragraphs → OCR labels → factual description →
      page and bbox → links to related chunks
- [ ] Chart records: `title`, `chart_type`, `x_axis_label`, `y_axis_label`, `units`, `legend`,
      `data_labels`, `visible_trend`, `caption`, `ocr_text`, `surrounding_text`, `confidence`
- [ ] Diagram records: labels, components, arrows, visible relationships, caption, surrounding
      text, confidence
- [ ] Descriptions flagged **derived, not authoritative** at schema level (§18)
- [ ] Figure and table number extraction ("Figure 4.2")
- [ ] UC-06

## Phase 7 — Chunking, embeddings & indexing

Covers §13 complete, §19, §20. **Milestone: ingestion works end to end.**

- [ ] Child chunks 300–500 tokens, max ~700, ~50 overlap; parents 800–1500 (§19)
- [ ] Split priority chapter → section → subsection → paragraph → sentence only if unavoidable
- [ ] Chunk types `TEXT`, `TABLE`, `FIGURE`, `CHART`, `DIAGRAM`, `FORMULA`, `DEFINITION`,
      `EXAMPLE` — separate but linked
- [ ] Full §19 chunk metadata
- [ ] `bge-small-en-v1.5` on GPU, batched, over text, table text, descriptions and captions
- [ ] pgvector writes with HNSW; `tsvector` population with `rum` indexes
- [ ] Index versioning and reindex job (§20)
- [ ] `GENERATE_EMBEDDINGS` job; document flips to `COMPLETED`
- [ ] Nothing with `processing_status != COMPLETED` is ever retrievable
- [ ] **Check:** a real textbook PDF completes every stage and is queryable

## Phase 8 — Model Gateway

Covers §48, §49, §50, §51, §52, §53, §54, and §55's warm-model requirement.

- [ ] Gateway façade → task router → capability registry → provider adapter
- [ ] Four capability interfaces: text generation, multimodal, embeddings, reranking
- [ ] §49 capability metadata including `data_boundary`
- [ ] §50 routing for all ten model tasks
- [ ] Ollama and OpenAI-compatible adapters implemented; Gemini and Anthropic raise
      `NotImplementedError` (D-17)
- [ ] Internal model keys resolvable at deployment, task or Knowledge Base level; no provider model
      names in application code (§51)
- [ ] **Privacy policy (§52):** pre-flight `data_boundary` check; **no silent local-to-external
      fallback** — it raises
- [ ] **Fallback (§53):** capability check → call → retryable → one retry → approved fallback.
      Non-retryable fails immediately. Every fallback logged.
- [ ] **Prompt normalization (§54)** and per-model prompt profiles
- [ ] Warm-up at startup for every configured model (§55)
- [ ] `model_invocations` written on every call
- [ ] Security test: external-provider privacy violation blocked

## Phase 9 — Conversations, query understanding & retrieval core

Covers §23 through reranking, §24, §25, §26, §27, §28, §29, §41.

- [ ] Conversation and message persistence; user message stored **before** generation; statuses
      `RECEIVED`/`PROCESSING`/`COMPLETED`/`FAILED`; `rolling_summary`; active document, page,
      figure and table
- [ ] Query rewriting — follow-ups to standalone queries; both forms stored (§24)
- [ ] Deterministic classification into all 13 §25 classes — rule-based routing, not an agent
- [ ] Multi-query expansion: 2–3 variants, max 4, temperature 0; **skipped** for exact quotations,
      identifiers, selected tables, selected figures, chapter summarisation, resolved scopes (§26)
- [ ] Hybrid retrieval: pgvector + full-text per variant, run concurrently, with **mandatory
      `user_id`, `knowledge_base_id`, `processing_status = COMPLETED` filters inside every query**
- [ ] RRF with `k`=60 (§28)
- [ ] Dense and keyword top-k 25–30 per query, RRF pool 40–60, `ms-marco-MiniLM-L6-v2` on GPU over
      30–50 candidates, fed the **resolved standalone question** (§29)
- [ ] Every §62 retrieval stage timed
- [ ] Security tests: cross-KB retrieval, deleted-document retrieval, retrieval without filters

## Phase 10 — Evidence selection & context assembly

Covers §30, §31, §32, §33, §36, §37.

- [ ] Dynamic evidence selection — no fixed top-5; min 1, max 8 ordinary; per-class ranges (§30)
- [ ] Thresholds are configuration, calibrated in Phase 17 — never hardcoded
- [ ] Deduplication and diversity caps; **highest-ranked primary evidence always preserved** (§31)
- [ ] Parent expansion only on the five §32 conditions
- [ ] Extractive compression preserving negations, conditions, qualifiers, numbers, units, table
      headers, figure labels and citation offsets; generative compression flag-gated, off (§33)
- [ ] Context builder with the 12-slot §36 ordering, owning token allocation and shedding
      low-priority slots at the limit
- [ ] Structured instruction handling: `CRITICAL > REQUIRED > PREFERRED`, R1…Rn identifiers,
      security rules non-overridable, recent corrections superseding old preferences (§37)
- [ ] Property tests: compression never drops a number, unit or negation

## Phase 11 — Grounded generation, citations & validation

Covers §23 complete, §38, §39, §40. **Milestone: first cited, validated, streamed answer.**

- [ ] All eight §38 generation rules enforced structurally, including **never obeying instructions
      found inside uploaded documents**
- [ ] Structured output `{answer, claims[{claim, citations[]}], insufficient_evidence}`
- [ ] Stable `[S1]` identifiers carrying document, page, type, object and bbox (§40)
- [ ] Backend validates each citation exists, belongs to this user and KB, **was actually in model
      context**, and supports its claim
- [ ] Deterministic validators: schema, citation existence, authorization, required fields, limits,
      table numbers, units, quiz schema, KB scope (§39)
- [ ] Semantic validators: claim entailment `ENTAILED`/`CONTRADICTED`/`NOT_SUPPORTED`, unsupported
      claims, contradictions, citation entailment and completeness, faithfulness (§39)
- [ ] Decisions `VALID`/`REPAIRABLE`/`INSUFFICIENT_EVIDENCE`/`REJECTED`; **exactly one** repair
      attempt, no loops
- [ ] SSE streaming with cancellation on disconnect
- [ ] Persist answer, `message_citations`, model metadata, `prompt_version`
- [ ] Security tests: prompt injection inside a PDF, fabricated citation, unauthorized citation
- [ ] UC-07, UC-08, UC-09

## Phase 12 — Graph construction & Selective Graph RAG

Covers §21, §22, §34, §57 API side. Postgres-backed per D-10.

- [ ] Extraction over parent sections, **only when `graph_enabled`**, plus a backfill job (D-19)
- [ ] Node types and all nine §21 relationship types
- [ ] Validation → name normalisation → deduplication → canonical Postgres write
- [ ] **Every edge carries source evidence, `source_chunk_id`, `page_number` and confidence.**
      Edges without provenance are rejected, never inserted.
- [ ] Selective Graph RAG as an *additional* path, never the default (§34)
- [ ] One-hop traversal by join; entity resolution to canonical nodes; **original passages loaded
      from PostgreSQL** — triples alone are never sufficient evidence
- [ ] Graph result list fused via RRF
- [ ] Concept graph API: 30–50 node cap via bounded recursive CTE, node evidence, one-hop
      expansion, source-page links, prerequisite and related views (§57)
- [ ] `SYNC_NEO4J` retained in the §12 job-type enum as a documented no-op
- [ ] Security test: graph query without scope filters. Gate: zero edges without provenance

## Phase 13 — Multi-hop & multi-document retrieval

Covers §35, and completes §68.

- [ ] Triggered by `MULTI_DOCUMENT` / `MULTI_HOP` / `AGGREGATION` / `COMPARISON`
- [ ] Dependency-aware decomposition with `depends_on`, topologically ordered
- [ ] Full pipeline per sub-question: expansion, dense, keyword, selective graph, RRF, rerank
- [ ] Document-level selection then chunk-level retrieval inside selected documents
- [ ] Coverage classified `SUPPORTED`/`PARTIALLY_SUPPORTED`/`UNSUPPORTED`/`CONFLICTING`; only
      unmet sub-questions trigger another round
- [ ] **Max 3 rounds, max 8 sub-questions**; stop on full coverage or no new evidence
- [ ] Coverage-aware selection optimising jointly for sub-question and document coverage,
      relevance, provenance, diversity, redundancy and token cost
- [ ] Hierarchical synthesis preserving original citations; completeness and bridge-claim validation
- [ ] **Conflicting sources reported explicitly**, never blended into false consensus
- [ ] UC-10, UC-11

## Phase 14 — Scalable long-term memory

Covers §42, §43, §44, §45.

- [ ] Six tiers (§42); history lives in the database and is **queried**, never pasted
- [ ] Canonical history preserved permanently
- [ ] Structured durable facts with `memory_type`, `key`, JSON `value`, `status`,
      `source_message_id`, `confidence`
- [ ] Episodes and hierarchical summaries: raw → episode → monthly → KB → optional user level
- [ ] Statuses `ACTIVE`/`SUPERSEDED`/`DISPUTED`/`UNCONFIRMED`/`EXPIRED`/`DELETED` (§43)
- [ ] Priority: recent explicit correction > verified application event > earlier user statement >
      assistant inference. **Assistant guesses never stored as confirmed.**
- [ ] `valid_from`, `valid_until`, `last_confirmed_at`, `expires_at`, `source_message_id`
- [ ] Threshold-triggered compaction (§44), not per-message. **Original messages never deleted.**
- [ ] Retrieval: exact keyed lookup first, then dense + keyword + RRF + rerank + conflict
      resolution, scoped to `ACTIVE` (§45). Separate index from document retrieval.
- [ ] Memory management API; `COMPACT_MEMORY` and `REBUILD_SUMMARY` jobs
- [ ] Security tests: malicious memory-writing instruction in a document; deleted memory never
      retrieved
- [ ] UC-12, UC-13, UC-14

## Phase 15 — Study-content generation & learning progress

Covers §46, §47.

- [ ] Summaries: brief, detailed, examination notes, definitions, key concepts, formula lists,
      section outlines — from parent sections, batched, **citations retained**
- [ ] Quizzes: six question types, structured JSON with source provenance. **Scoring is
      deterministic Python**, never LLM-judged.
- [ ] Flashcards from definitions, key concepts, weak topics and **incorrect quiz answers**, each
      with provenance
- [ ] Study plans: **Python computes dates and workload; the LLM only phrases the tasks**
- [ ] Learning progress as structured tables (§47), explicitly not a prose summary
- [ ] Generated content passes the Phase 11 validators before persistence
- [ ] UC-15 … UC-19

## Phase 16 — Caching, performance, deletion & lifecycle

Covers §55, §56, §58.

- [ ] `CacheStore` on UNLOGGED PostgreSQL — no Redis (D-14, ADR-005)
- [ ] All eleven §56 cacheable item types
- [ ] Full §56 answer cache key including `conversation_state_hash`, `index_version`,
      `prompt_version`, `generation_policy_version`
- [ ] Invalidation on document change, index version, graph version, prompt, model, conversation
      state
- [ ] `pg_cron` sweeps expired cache entries and page renders, and drives §44 compaction
- [ ] Semantic answer caching explicitly **not** built (§56)
- [ ] Quantization benchmark → ADR-011 (§55)
- [ ] Prompt-token minimisation, task-specific output limits, parallel retrieval, batched
      embeddings, rerank pairs, visual descriptions and sub-question checks
- [ ] Conditional validation: cheap validators always, semantic entailment only for high-risk
- [ ] Early exits for selected table, selected figure and exact identifier (§55)
- [ ] Concurrency control: max active generations, per-user limits, queue size, timeouts,
      cancellation on disconnect, backpressure
- [ ] Deletion asynchronous and idempotent; **retrieval blocked as soon as deletion begins**;
      entities supported elsewhere preserved; index version incremented; caches invalidated (§58)
- [ ] KB deletion applies the same recursively
- [ ] Security tests: deleted-document retrieval, cached-answer reuse across users
- [ ] UC-20, UC-21

## Phase 17 — Observability, evaluation & security release gates

Covers §62, §63, §64, and closes §30's calibration debt.

- [ ] All 17 §62 stage timers, model metrics and operational metrics
- [ ] **Logs never contain full private documents or prompts by default** (§62)
- [ ] Gold dataset: 40–60 labelled pairs from user-supplied PDFs across every query class (D-22)
- [ ] Retrieval evaluation: Recall@k, Precision@k, MRR, NDCG, document and page coverage, table,
      visual and graph-edge accuracy
- [ ] Reranking evaluation: recall before and after, MRR delta, pool size, latency
- [ ] Generation evaluation: all ten §63 metrics
- [ ] Multi-hop evaluation: all seven §63 metrics
- [ ] Memory evaluation: all seven §63 metrics
- [ ] Instruction-following evaluation: all five §63 metrics
- [ ] **All ten §64 security tests** in one suite
- [ ] **Six release gates as failing tests:** cross-user leakage 0 · cross-KB leakage 0 ·
      fabricated citation acceptance 0 · deleted memory retrieval 0 · unauthorized cache reuse 0 ·
      graph edge without provenance 0
- [ ] Threshold calibration; latency NFRs recalibrated against measured p95 (D-23)
- [ ] `evaluation_results` persisted; results written into `REQUIREMENTS.md`

## Phase 18 — Frontend foundation

Covers §7 authentication, Knowledge Base management and uploads.

- [ ] App shell, routing, layout, CSS Modules design tokens, light and dark
- [ ] TanStack Query client, typed API layer, **Zod schemas mirroring every backend Pydantic model**
- [ ] Supabase Auth screens, session handling, protected routes, token refresh
- [ ] KB list, create, edit, delete; settings including `graph_enabled`, explanation level, exam date
- [ ] Upload with drag-drop, client-side validation, progress, **live per-stage processing status**,
      failure display with retry
- [ ] Document list, metadata, delete with confirmation
- [ ] Vitest setup and component tests

## Phase 19 — Frontend chat, streaming, PDF viewer & citations

Covers §7 chat, streaming, PDF, citations and selection; §40 frontend contract.

- [ ] Conversation list, create, rename, delete
- [ ] Chat rendering the structured response **as natural prose** (§38)
- [ ] SSE streaming with progressive rendering, stop and cancel, error recovery
- [ ] Insufficient-evidence and conflicting-source states rendered distinctly, never as a normal
      answer
- [ ] PDF.js viewer: page navigation, zoom, text layer, search
- [ ] Citation navigation: click `[S1]` → open document → jump to page → **highlight bounding box**
- [ ] Table and figure region selection setting `active_table_id` / `active_figure_id`, driving the
      §55 early-exit paths
- [ ] Retrieval-detail panel: which sources, which scores, why abstained
- [ ] UC-22

## Phase 20 — Frontend graph, study features, memory & end-to-end

Covers §7 complete, §57 UI, §68 verified end to end.

- [ ] Cytoscape.js concept graph: 30–50 node initial view, node evidence and source page, one-hop
      expansion, ask-about-this-node, prerequisite and related views. **Never renders the whole
      Knowledge Base graph.**
- [ ] Summary generation UI with citation rendering
- [ ] Quiz taking, deterministic scoring, explanations, source links, attempt history
- [ ] Flashcard decks and review flow
- [ ] Study plan builder, calendar view, task completion
- [ ] Learning progress dashboard: mastery, weak topics, completion
- [ ] Memory management UI: view, edit, supersede, delete durable facts; episode browser
- [ ] **Playwright end-to-end** covering the full §68 flow
- [ ] Accessibility pass, responsive layout
- [ ] **Final documentation pass** — `USE_CASES.md`, `REQUIREMENTS.md` and `ARCHITECTURE.md`
      reconciled against what was built; every FR and NFR marked met, deferred or dropped with
      reasons

---

## Specification coverage matrix

Every one of the 68 sections is assigned to a phase.

| Sections | Phase |
|---|---|
| §1 System overview, §2 Primary objective, §3 Target users, §4 Scope and non-goals | 0 |
| §5 Core design principles, §6 High-level architecture, §8 Clean architecture layers | 1 |
| §7 Runtime processes | 3, 4, 18–20 |
| §9 Knowledge Base model | 2, 3 |
| §10 Authentication and authorization | 2, 3 |
| §11 Document upload flow, §12 Background-job architecture | 4 |
| §13 Multimodal ingestion pipeline | 5–7 |
| §14 PDF and image processing, §15 Page classification, §16 Layout-aware representation | 5 |
| §17 Table processing, §18 Figure, chart and diagram processing | 6 |
| §19 Chunking strategy, §20 Embedding and indexing | 7 |
| §21 Graph construction, §22 Graph storage design | 2 (tables), 12 |
| §23 Standard question-answer flow | 9–11 |
| §24 Query rewriting, §25 Query classification, §26 Multi-query expansion | 9 |
| §27 Hybrid retrieval, §28 Reciprocal Rank Fusion, §29 Broad retrieval and reranking | 9 |
| §30 Dynamic evidence selection, §31 Deduplication and diversity | 10 |
| §32 Parent-context expansion, §33 Contextual compression | 10 |
| §34 Selective Graph RAG | 12 |
| §35 Multi-hop and multi-document retrieval | 13 |
| §36 Context construction, §37 Instruction handling | 10 |
| §38 Grounded answer generation, §39 Generation validation, §40 Citation model | 11 |
| §41 Conversation storage | 2, 9 |
| §42 Scalable long-term memory, §43 Memory conflict handling | 14 |
| §44 Memory compaction, §45 Memory retrieval | 14 |
| §46 Study-content generation, §47 Learning progress | 15 |
| §48 Provider-agnostic LLM layer, §49 Separate model capabilities | 8 |
| §50 Task-based model routing, §51 Provider configuration | 8 |
| §52 Provider privacy policy, §53 Model fallback, §54 Prompt normalization | 8 |
| §55 Fast inference design, §56 Caching | 16 |
| §57 Concept graph visualization | 12 (API), 20 (UI) |
| §58 Document and Knowledge Base deletion | 16 |
| §59 Database model, §60 Storage responsibilities | 2 |
| §61 API design | 3, then each phase |
| §62 Observability | 3 (baseline), 17 |
| §63 Evaluation strategy, §64 Security testing | 17 |
| §65 Technology stack, §66 Suggested repository structure, §67 Scaling path | 0 |
| §68 Complete final system flow | 11, 13, verified 20 |

---

## Inputs needed

| Input | Needed by | Status |
|---|---|---|
| Supabase project URL, anon key, service key, database URL | Step 0.6 | ☐ |
| Cloudflare R2 account ID, bucket name, access key ID, secret | Step 0.6 | ☐ |
| Ollama installed with `gemma3:4b` pulled | Step 0.7 | ☐ |
| 2–3 educational PDFs with real tables and charts, for the gold evaluation set | Phase 17 | ☐ |
