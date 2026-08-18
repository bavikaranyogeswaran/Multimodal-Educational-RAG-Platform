# Implementation Plan

Phased build plan for the Multimodal Educational Tutor RAG platform, derived from the 68-section
system design specification.

## How to use this document

- Phases run in numerical order unless a dependency says otherwise. Within Phase 0, follow the
  **running order** column, not the step numbers.
- **That ordering has already been departed from.** Phase 9 was built to near-completion while
  phases 5, 6 and 8 were untouched and phase 7 was a third done, on the strength of a placeholder
  ingestion path good enough to put text in the index. It worked, and the retrieval pipeline it
  produced is sound — but the placeholder is now the ceiling on everything measured downstream,
  and phases 10 and 11 would stack on the same foundation. Read each phase's **Status** line
  before assuming the numbering tells you what is finished.
- Work proceeds **one step at a time**. The next step is never started automatically.
- Every phase ends in something testable and one commit.
- Section references like `§27` point at the source system design specification.
- The **Decisions log** below is authoritative. If this plan and a memory of a conversation
  disagree, the log wins.
- The log holds decisions **the user chose in answer to a question**. Judgement calls made *while*
  executing a step live in [EXECUTION_LOG.md](EXECUTION_LOG.md) as `A-xxx` entries, along with the
  assumptions that are not yet verified. Update it at the end of every step.

## Status

| | |
|---|---|
| Phases complete | **4 of 21** — Phase 0, 1, 2, 3 ✅ |
| In progress | **Phase 9** — ~95%, three persistence gaps left |
| Partially built | Phase 4 (~85%) · Phase 5 (~70%) · Phase 7 (~75%) · Phase 8 (~25%) · Phase 17 (~15%) |
| Not started | Phase 6, 10–16, 18–20 |
| Tests | 1,833 unit and security · 15 integration · 109 marked `security`, 75 `gate` |
| Next step | **7.6** — full ingestion, now unblocked; **7.4** still waits on a textbook PDF |
| Last updated | 18 August 2026 (chunking complete through step 7.3) |

Phases 0 through 3 are complete. Phase 9 was built well ahead of phases 4 through 8 being
finished, so the numbering no longer describes the build order — work jumped to conversations and
retrieval once the data model and API surface were in place. Ingestion now parses into typed
elements in reading order and chunks on the structure those elements carry, so §19 is built and
the ceiling it put on retrieval quality is lifted. Two holes remain on that path: pages whose
text layer cannot be trusted are recorded and left unread, since Phase 5 deferred recognition
pending a real textbook to calibrate against, and Phase 6 has not been started at all, so nothing
visual is described or answerable.

Migration `0008` applied at `0008 (head)` against Supabase; fourteen SQLAlchemy models registered
with `Base.metadata`. ruff and mypy clean across `app/`.

**Two known test failures**, neither caused by the code under test:

- `test_container.py::test_every_slot_raises_not_implemented_on_access` — asserts `model_gateway`
  is still an unimplemented slot; it has held a real `OllamaModelGateway` since `897a88d`.
- `test_stage_timer.py::test_measures_real_elapsed_time` — flaky, failing roughly one run in
  three. Asserts at least 20 ms elapsed after a 20 ms sleep, which Windows timer granularity does
  not reliably satisfy.

**Documentation debt carried into Phase 20.** `REQUIREMENTS.md` has no status column against its
334 functional requirements; `USE_CASES.md` tracks no implementation status; `ARCHITECTURE.md`
does not yet describe the transaction boundaries introduced in step 9.15; `EXECUTION_LOG.md` has
no entries between step 3.2 and step 9.11, against the standing constraint that every step
updates it.

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
- **Every step updates [EXECUTION_LOG.md](EXECUTION_LOG.md).** Assumptions made without asking,
  deviations from the plan, discoveries and corrections are recorded as `A-xxx` entries as part of
  the step, not reconstructed afterwards. Anything believed but unverified also goes in the open
  assumptions table with the phase that will confirm it.
- **Comments carry no cross-reference identifiers.** Code comments, docstrings, config comments and
  error messages explain the reasoning in plain language. They do not cite phase numbers, step
  numbers, requirement IDs, use-case IDs, ADR numbers or spec sections — a comment that only points
  at a register is not an explanation, and it rots when the register is renumbered. The registers in
  this repository still cross-reference each other freely; the rule applies to source files.

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
| D-16 | ~~NVIDIA GPU available — CUDA builds throughout~~ | Partially superseded by D-27. GPU confirmed, but at 6 GB it cannot host OCR alongside inference. |
| D-17 | Ollama and OpenAI-compatible adapters implemented; Gemini and Anthropic interface-only | The OpenAI-compatible adapter covers vLLM and llama.cpp servers for free. The gateway, task router, capability registry, privacy policy and fallback logic are built in full regardless (§48–§54). |
| D-18 | English-only content | `bge-small-en-v1.5` as specified. `preferred_language` and `chunk.language` are populated by detection but no multilingual embedding or OCR path is built. Swapping models later is a config change plus reindex, which the versioned-index design already supports (§20). |
| D-19 | Graph extraction **opt-in per Knowledge Base** | §21 runs an LLM over every parent section — hundreds of local calls for a 400-page textbook. A `graph_enabled` flag gates `BUILD_GRAPH`; enabling it later triggers a backfill job. Ingestion always produces chunks, embeddings and full-text indexes. See ADR-008. |
| D-20 | All §26/§29/§30 tuning numbers become named config values | RRF `k`, top-k ranges, candidate pool size, reranker thresholds and evidence limits are configuration from step 0.6 onward — never literals in code. §30 requires calibration against evaluation data, which is impossible if they are scattered. |
| D-25 | **Async data layer throughout** — SQLAlchemy 2.0 asyncio + psycopg3 async | `FR-RET-17` requires concurrent dense and keyword retrieval across query variants, `FR-PRF-06` requires batching, `FR-GEN-12` requires SSE streaming, `NFR-PERF-19` requires backpressure. All are natural in async and awkward otherwise. Cost accepted: no lazy loading, explicit eager loads, and the worker is async too since it shares repository code. |
| D-26 | **structlog** for logging | `NFR-OBS-01` needs a trace ID on every line without threading it through call signatures; `NFR-OBS-02` needs 16 stage timings as queryable fields rather than formatted strings; `NFR-PRV-03` needs redaction as a central processor rather than a convention at each call site. |
| D-27 | **PaddleOCR runs on CPU; the GPU is reserved for inference, embeddings and reranking** | The target GPU has 6 GB. Gemma 3 4B plus KV cache is ~3.5 GB, leaving no room to share with OCR. Job priority (`FR-JOB-06`) arbitrates CPU scheduling, not VRAM — two processes wanting the card would degrade chat latency regardless of priority. Ingestion is background work, so slower OCR costs little; chat latency, which the `NFR-PERF` budgets measure, is protected. Side benefit: the CPU wheel is plain `paddlepaddle` on PyPI, removing the CUDA-index problem that deferred the `ml` group from step 0.2. |
| D-28 | **PaddleOCR-VL retained, CPU-only** | `FR-ING-11` and `FR-ING-12` stay satisfied rather than deferred. `NFR-PERF-17` already caps the VL path at under 20% of pages, so a slow fallback on a rare minority is coherent. `NFR-PERF-12` revised from 20 s to 120 s per complex page. |
| D-30 | **Domain entities are frozen stdlib dataclasses** with validation in `__post_init__` | The domain imports nothing but the standard library — the strongest reading of the dependency rule, and it makes `NFR-MNT-01` trivially satisfiable. Pydantic in the domain would give free validation but pulls serialisation in with it, and domain models that already serialise leak outward into API responses, quietly erasing the presentation boundary. Cost accepted: hand-written validation, and conversion to Pydantic at the API edge. `pydantic` is added to the boundary test's forbidden-import list so this cannot erode. |
| D-31 | **Ports are `typing.Protocol`**, structural rather than nominal | Adapters satisfy a port by shape, so infrastructure never imports a domain class merely to subclass it — the arrow points inward in the most literal sense. Test fakes become plain objects rather than subclasses. Cost accepted: a mismatch surfaces in mypy rather than at import, so type checking must actually run in the loop. |
| D-32 | **Entities are immutable**, with named transition methods | State changes return a new instance — `document.mark_processing()` rather than attribute assignment — so illegal transitions are unrepresentable and no pipeline stage can mutate shared state behind a caller's back. That last point is not theoretical: retrieval stages run concurrently. Cost accepted: more allocation and frequent `dataclasses.replace`. |
| D-29 | **Child chunk overlap is 70 tokens**, not the ~50 §19 suggests | User decision. §19 says "approximately 50 tokens where necessary", so 70 is within the spirit of an approximate figure rather than a substantive deviation. More overlap reduces the chance that a sentence spanning a chunk boundary is retrievable from neither side, at a modest cost in index size and duplicate evidence — which the deduplication stage already handles. Revisit against retrieval evaluation. |

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
| R-07 | **6 GB VRAM is the binding hardware constraint.** Measured in step 0.3: RTX 3050 6 GB Laptop, driver 555.97, sm_86. After Gemma 3 4B (~3.5 GB) and the retrieval models (0.22 GB measured), roughly 2.3 GB remains. | D-27 moves OCR to CPU. `Q8_0` quantization is likely not selectable (ADR-0011). `FR-PRF-02` — all models warm at startup — is satisfiable only because OCR left the GPU. Any future model addition must be budgeted against this ceiling, not assumed to fit. | Phase 8, Phase 16 |
| R-08 | **Cross-encoder scores are low and compressed in absolute terms.** Measured in step 0.3: a relevant pair scored −10.58, an irrelevant one −11.24 — correct ordering, margin only +0.66, both far below zero. | Early confirmation of why §30 forbids universal thresholds (`FR-EVD-05`). A naive "keep candidates above 0" rule would discard every candidate. Evidence selection must use a **relative** margin against the top-ranked candidate, never an absolute cut, and the threshold must be calibrated in Phase 17. | Phase 10, Phase 17 |

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
| 9 | 0.3 | GPU/ML install & CUDA smoke test | M · risky | ✅ |
| 10 | 0.4 | Backend ruff / mypy / pytest | S | ✅ |
| 11 | 0.5 | Frontend Vite/React/TS scaffold | S | ✅ |
| 12 | 0.6 | Config schema & `.env.example` | M | ✅ |
| 13 | 0.7 | Environment verification script | M | ✅ |

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

### 0.3 — GPU/ML dependencies & CUDA smoke test ✅

- [x] `ml` dependency group declared: `torch` (cu126 index), `sentence-transformers`,
      `paddlepaddle` (**CPU wheel**, D-27), `paddleocr`
- [x] torch resolves from `https://download.pytorch.org/whl/cu126` via `[tool.uv.sources]`

**Measured results**

```
torch            2.13.0+cu126
cuda available   True
device           NVIDIA GeForce RTX 3050 6GB Laptop GPU
capability       sm_86          vram total  6.00 GiB
matmul x10       OK (122 ms)

paddle           3.3.1          compiled w/ cuda  False  (expected — D-27)
paddle device    cpu            paddleocr         3.7.0

bge-small        load 8.9s · encode 104 ms · dim 384 · 136 MiB
ms-marco-MiniLM  load 5.8s · predict 51 ms · num_labels 1 · ordering OK

peak vram        223 MiB        headroom  5.78 GiB
```

- [x] `torch.cuda.is_available()` true; GPU matmul verified
- [x] Paddle confirmed CPU-only, as intended
- [x] Both retrieval models load on GPU and produce correct output — 384-dim embeddings, correct
      relevance ordering from the reranker

**cu126, not cu128.** Driver 555.97 reports CUDA 12.5. CUDA minor-version compatibility covers any
12.x runtime on a driver ≥ 525, so cu126 is safe; cu128 or cu129 would want a newer driver.

Two findings recorded as risks: **R-07** (6 GB ceiling) and **R-08** (compressed reranker scores).

### 0.4 — Backend code-quality tooling ✅

- [x] Ruff lint and format — `ruff check` clean, `ruff format` applied
- [x] mypy: `disallow_untyped_defs` everywhere, **`strict` on `app.domain.*` and
      `app.application.*`** — those layers depend on nothing external, so there is no excuse for
      looseness. Success on 38 source files.
- [x] pytest with `asyncio_mode = "auto"`, coverage, and three custom markers: `security`, `gate`,
      `slow` — so §64 tests and release gates are selectable as a suite from Phase 3 onward
- [x] **8 tests passing**

**The first tests are real, not placeholders.**

`tests/unit/test_layer_boundaries.py` discharges `NFR-MNT-01` — it walks `app/domain/` and
`app/application/`, parses each file's AST, and fails if any inner-layer module imports a framework,
driver or vendor SDK. It also asserts those directories exist, so the rule cannot pass vacuously
because a directory was renamed.

Verified by planting a violation:

```
AssertionError: Dependency rule violated in app/domain/ — dependencies must point inward
(ARCHITECTURE.md §4, NFR-MNT-01):
    app\domain\_probe.py  imports  sqlalchemy, torch
```

`tests/unit/test_app_boots.py` covers the health probe, the versioned OpenAPI path (`FR-API-01`),
and that the lifespan hook completes — the hook Phase 8 hangs model warm-up off (`FR-PRF-02`).

Ruff's rule set includes **ASYNC** (D-25 makes async correctness load-bearing), **S** (bandit —
security is a first-class concern here), and **DTZ** (timezone-aware datetimes — `FR-MEM-13` validity
dates and `FR-JOB-02` lease timestamps are silently wrong if naive).

Source files are read as `utf-8-sig` rather than `utf-8`: a BOM is easy to introduce on Windows and
would otherwise crash the boundary check with a `SyntaxError` instead of doing its job.

### 0.5 — Frontend scaffold ✅

- [x] Vite 7 + React 19 + TypeScript 5.9, CSS Modules, `@/` path alias in both Vite and tsconfig
- [x] TanStack Query and Zod installed; query client configured with deliberate defaults
- [x] ESLint 9 flat config with type-aware rules, Prettier, Vitest, Testing Library
- [x] `npm run typecheck` · `npm run lint` · `npm test` (3 passed) · `npm run build` all clean
- [x] Dev server verified rendering in a browser with no console errors
- [x] `.claude/launch.json` for both `frontend` and `api` processes

Scaffolded **manually rather than with `create-vite`**, which would have overwritten the §66 tree
established in 0.1.

**TypeScript is strict beyond the default template** — `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `erasableSyntaxOnly`. `NFR-MNT-07` requires the
frontend to mirror the backend contract in Zod; loose typing on this side would defeat the point.

**Design tokens carry semantic answer states from the start** — `--color-abstain` and
`--color-conflict` exist in `global.css` because `NFR-UX-02` and `NFR-UX-03` require abstentions and
source conflicts to be *visually distinct*, not styled like ordinary answers. Cheaper to establish
now than to retrofit in Phase 19.

The query client disables retry on 401 and 404, since `FR-AUTH-13` makes a foreign Knowledge Base
return 404 by design — retrying it is pure latency.

### 0.6 — Configuration schema & `.env.example` ✅

- [x] 16 typed settings groups in `app/configuration/settings.py`, each with its own env prefix
- [x] Supabase, database, R2, Ollama, and the four internal model keys (§51)
- [x] Every §19/§26/§29/§30 tuning constant as named configuration (D-20, NFR-MNT-04)
- [x] Memory compaction thresholds, job queue tuning, cache TTLs, observability flags
- [x] `backend/.env.example` and `frontend/.env.example`, fully commented with requirement
      references
- [x] 21 tests passing; ruff and mypy clean

**Secrets are `SecretStr`.** Verified by a test that injects a sentinel value into every credential
field and asserts it appears in neither `repr`, `str`, `model_dump()` nor `model_dump_json()`
(NFR-SEC-12).

**Seven invariants are enforced at startup rather than documented.** A misconfiguration that boots
successfully is the one that reaches production:

| Invariant | Requirement |
|---|---|
| Signed-URL TTL within 60–3600 s | NFR-SEC-05 |
| `parent_target_tokens` > `child_max_tokens` | FR-EVD-09 — otherwise parent expansion restores nothing |
| `max_items` ≥ `min_items` | FR-EVD-04 |
| Expansion leaves room for the original query | FR-QRY-06 |
| Job lease outlasts two heartbeats | FR-JOB-07 — otherwise a healthy worker loses its job mid-flight |
| Reranker candidates ≤ candidate pool | FR-RET-09 |
| Production forbids logging prompts, document text or model outputs | NFR-PRV-03 |

**There is deliberately no absolute reranker threshold setting.** R-08 measured scores of −10.58
(relevant) and −11.24 (irrelevant); a plausible-looking "keep scores above zero" rule would discard
every candidate. Selection uses `EVIDENCE_RELATIVE_SCORE_MARGIN` against the top-ranked candidate,
and a test fails if a key matching `ABSOLUTE` or `SCORE_THRESHOLD` is ever reintroduced.

Two tests keep `.env.example` and the schema in sync in both directions — a declared key that no
setting reads (looks configured, does nothing), and a credential the schema needs that the file
does not document (a fresh clone would not know to set it).

Ruff's `RUF002`/`RUF003` are disabled: comments legitimately contain `§48–§54` and `−10.58`.
`RUF001`, which catches ambiguous characters in *identifiers* — the actual homoglyph hazard —
remains enabled.

### 0.7 — Environment verification script ✅

`backend/scripts/verify_environment.py`, run with `uv run python scripts/verify_environment.py`.

- [x] Python version, CUDA + torch with a real GPU matmul, Paddle build and device
- [x] Ollama reachability plus a check that every configured model key is actually pulled
- [x] PostgreSQL connectivity, server version, and per-extension status for `vector`, `rum`,
      `pg_cron`, `pg_trgm`
- [x] R2 round-trip — put, fetch through a presigned URL, verify the bytes, delete
- [x] Four tests covering the script's own logic

**Current output on this machine:**

```
  runtime
    python         PASS   3.12.13
    torch / cuda   PASS   2.13.0+cu126 · RTX 3050 6GB Laptop · 6.00 GiB · sm_86
    paddle / ocr   PASS   paddle 3.3.1 · paddleocr 3.7.0 · cpu
  services
    ollama         FAIL   nothing listening at http://127.0.0.1:11434
    postgres       SKIP   DATABASE_URL not set
    r2 storage     SKIP   STORAGE_ACCOUNT_ID / credentials not set

  3 pass · 1 fail · 2 skip
```

**SKIP and FAIL are deliberately different.** An unconfigured service skips; a configured but broken
one fails, and only a failure sets a non-zero exit code. The script is meant to be useful *before*
everything is wired up, not only afterwards — otherwise nobody runs it until it is too late to help.

Checks distinguish three shades of wrong rather than two: a Paddle GPU build when the configuration
says CPU is a warning (wasteful, risks VRAM contention), not a failure. An extension that is
available but not yet installed is a warning, because migrations install it.

The verification is **live rather than declarative** — it runs a GPU matmul, fetches a real presigned
URL and compares the bytes. Checking that a library imports proves considerably less.

---

## Phase 1 — Clean architecture skeleton & domain layer

Covers §5, §6, §8, §51. Frozen stdlib dataclasses (D-30), `Protocol` ports (D-31), immutable
entities with named transitions (D-32).

Entities first, then ports, then wiring — the dependency order. Grouping the ports lets the whole
contract surface be reviewed for consistency at once rather than scattered across entity files.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 1.1 | Domain vocabulary — enums, value objects, `ScopeContext`, error hierarchy | M | ✅ |
| 1.2 | Knowledge Base, Document, Page, DocumentElement | M | ✅ |
| 1.3 | Chunk, Evidence, Citation, RetrievalPlan | M | ✅ |
| 1.4 | Conversation, Message, MemoryFact | M | ☑ |
| 1.5 | GraphEntity, GraphRelationship | S | ☑ |
| 1.6 | ModelRequest, ModelResponse, ProcessingJob | M | ✅ |
| 1.7 | Repository ports | M | ✅ |
| 1.8 | Adapter ports | M | ✅ |
| 1.9 | Model gateway port and capability registry | M | ☑ |
| 1.10 | Composition root, DI wiring, boundary test made load-bearing | M | ☑ |

### 1.1 — Domain vocabulary ✅

`app/domain/enums.py`, `values.py`, `scope.py`, `errors.py`. **90 tests passing**, ruff and mypy clean.

- [x] 22 enums covering ingestion, jobs, conversations, routing, validation, memory, graph and the
      model gateway
- [x] Value objects `BoundingBox`, `HeadingPath`, `TokenBudget`
- [x] `ScopeContext(user_id, knowledge_base_id)`
- [x] Domain error hierarchy; the domain never names a status code
- [x] `pydantic` and `pydantic_settings` added to the boundary test's forbidden list, enforcing D-30

**The boundary test stopped being vacuous.** Verified by planting a `pydantic` import plus an
outward reach into `app.infrastructure` — both caught. Audited what the domain actually imports:

```
['__future__', 'app', 'dataclasses', 'enum', 'typing', 'uuid']
```

Standard library only, as D-30 requires.

**Behaviour lives on the enums** rather than in scattered `if` statements, so routing rules are
stated once and testable directly: `QueryClass.needs_decomposition`, `.benefits_from_graph`,
`.forbids_expansion`; `DocumentStatus.is_retrievable`; `MemoryStatus.is_retrievable`;
`ValidationDecision.is_returnable`; `CoverageStatus.needs_another_round`;
`DataBoundary.accepts_private_content`.

Two enums are `IntEnum` because their ordering is the point rather than an accident of declaration:
`JobPriority` (workers claim by descending priority) and `RequirementLevel` (conflicts resolve by
comparing levels). `MemoryProvenance` was added for the same reason — a correction outranking an
assistant guess is an ordering, so it is modelled as one.

Two design points worth recording:

- **`NotFoundError` and `ScopeViolationError` are distinct types** even though the API answers both
  identically. A resource the caller does not own must be indistinguishable from one that does not
  exist, or the API becomes an oracle for guessing identifiers — but keeping them separate
  internally is what lets a scope violation be recorded as a security event while a genuine miss is
  not.
- **`CoverageStatus.CONFLICTING` does not trigger another retrieval round.** More searching will not
  resolve sources that genuinely disagree; the disagreement is the finding.

`BoundingBox` carries `intersection_over_union` and `merged` now rather than later — associating
captions with figures needs both, and geometry reimplemented at three call sites is geometry wrong
at two of them.

### 1.2 — Knowledge Base and document entities ✅

`app/domain/knowledge_base/entities.py`, `app/domain/documents/entities.py`,
`app/domain/invariants.py`. **163 tests passing**, ruff and mypy clean.

- [x] `KnowledgeBase` with the full §9 property set, `graph_enabled`, and both version pointers
- [x] `Document`, `DocumentPage`, `DocumentElement` with the full §16 field set
- [x] Status transitions as a state machine

**The state machine refuses what would misdescribe the system.** `COMPLETED → PROCESSING` is
allowed, because reprocessing after an embedding-model change must be possible.
`COMPLETED → PENDING` is not, because it would describe an indexed document as never having been
ingested. `DELETING` is **absorbing** — a path back would make content retrievable after its files
had gone.

**Every scoped entity reports its own scope.** A Knowledge Base *is* a scope, so nothing downstream
pairs two loose identifiers and risks pairing them wrongly.

**Document text is `UntrustedText`**, whose string form is a placeholder rather than the content.
Interpolating it into a prompt template by accident yields `<untrusted text, 240 chars>` instead of
whatever the document author wrote — so the mistake is visible in output rather than silent. Reading
the characters requires `.value`, and that call site is then an explicit acknowledgement.

Four invariants are enforced at construction: a failed document carries a reason and a recovered one
does not; a completed document knows its page count; an OCR-derived element carries both a bounding
box and a confidence, since a citation that cannot be opened at a location is not much of a
citation.

Transitions take `now` as an argument — the domain reads no clock, so behaviour is reproducible and
no test freezes a global.

**mypy was not checking the test suite at all.** Two `conftest.py` files collided on module name and
mypy stops after that error. Fixing it surfaced eleven real annotation gaps, now closed with a
generic `Builder[T]` protocol rather than ignore comments.

### 1.3 — Retrieval entities ✅

`app/domain/documents/chunks.py`, `app/domain/retrieval/entities.py`. **236 tests passing**, ruff and
mypy clean.

- [x] `Chunk` with parent link and full §19 metadata
- [x] `EvidenceLabel`, `Evidence`, `EvidenceSet`
- [x] `Citation`
- [x] `RetrievalFilters` and `RetrievalPlan`, derived from the query class

**The fabricated-citation gate is now structural.** The chain is: retrieval produces evidence,
evidence carries a positional label, the model may cite only those labels, and validation resolves
each citation through `EvidenceSet.require` — *the same set that was put in front of the model*.

That last point is the one that matters. A chunk can be entirely real, belong to the right student
and the right Knowledge Base, and still not have been supplied for this question. Resolving a
citation against the database would wave it through; resolving against the supplied set does not.

**`EvidenceSet` refuses to span more than one scope**, at construction. Mixed evidence is a leak that
has already happened by the time anyone inspects it, so it is refused where it would be assembled.

**`RetrievalFilters` deliberately omits the mandatory filters.** It holds only optional narrowing —
user, Knowledge Base and completed-status predicates come from the scope, because a field can be
left unset and those must not be.

**`RetrievalPlan.for_query` applies the routing properties already on `QueryClass`** rather than
restating them, so a second set of rules cannot drift from the first. It also drops an early exit
when the object it depends on was not actually selected: asking about "the table on page 67" without
having selected one still needs a search to find out which table that is.

**A duplicate `EarlyExitPath` was found and reconciled** — see A-114.

### 1.4 — Conversation and memory entities

- [x] `Conversation` with active document, page, figure and table state
- [x] `Message` with role, status, rewritten query and model metadata
- [x] `MemoryFact` with the six statuses, provenance and validity dates — the supersession rule
      lives on the entity, not in a service

### 1.5 — Graph entities

- [x] `GraphEntity`
- [x] `GraphRelationship` — **cannot be constructed without `source_chunk_id`, `page_number` and
      evidence.** Provenance becomes unrepresentable-if-absent at the type level, before the
      database constraint backs it up in Phase 2

### 1.6 — Model and job entities ☑

- [x] `ModelRequest` and `ModelResponse` in provider-neutral form — the §54 seven-slot prompt
      structure, not a provider payload
- [x] `ProcessingJob` with priority, attempt count, lease and heartbeat

### 1.7 — Repository ports ☑

- [x] Knowledge Base, document, chunk, conversation, memory, graph and job repositories
- [x] Every method takes `ScopeContext` as its first parameter, so an unscoped query does not
      type-check — the scoping requirement expressed in the signature rather than in a comment

### 1.8 — Adapter ports ☑

- [x] `StoragePort`, `PdfParserPort`, `OcrPort`, `EmbeddingPort`, `RerankerPort`
- [x] `DenseRetriever`, `KeywordRetriever`, `GraphPort`, `CacheStore`, `ObservabilityPort`
- [x] `GraphPort` in traversal vocabulary — `neighbors(...)`, `subgraph(...)` — never a query
      language, so a graph database can be introduced later without touching callers (D-10)

### 1.9 — Model gateway port

- [x] The four capability interfaces: text generation, multimodal, embeddings, reranking
- [x] Capability metadata and the ten model tasks
- [x] The `data_boundary` type that makes the privacy pre-flight expressible

### 1.10 — Composition root and wiring

- [x] DI container and adapter registration
- [x] Lifespan integration
- [x] **The boundary test stops passing vacuously here** — this is where it starts earning its place

## Phase 2 — Data model, migrations & Row-Level Security

Covers §9, §22, §41, §59, §60, and the storage half of §10.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 2.1 | Alembic setup + extension activation migration | S | ✅ |
| 2.2 | Knowledge Base, Document & Page SQLAlchemy models + migration | M | ✅ |
| 2.3 | Chunk models, pgvector column, tsvector column, versioning columns + migration | M | ✅ |
| 2.4 | Retrieval indexes: HNSW, rum full-text, six composite scoped indexes | S | ✅ |
| 2.5 | Conversation, Message & Memory SQLAlchemy models + migration | M | ✅ |
| 2.6 | Graph SQLAlchemy models, traversal indexes + migration | S | ✅ |
| 2.7 | Job queue & cache models, UNLOGGED cache_entries, pg_cron sweep + migration | S | ✅ |
| 2.8 | Row-Level Security policies on all scoped tables | M | ✅ |
| 2.9 | Async session factory + ScopedRepository base | M | ✅ |
| 2.10 | KnowledgeBaseRepository, DocumentRepository & ChunkRepository implementations | M | ✅ |
| 2.11 | ConversationRepository, MemoryRepository, GraphRepository & JobRepository implementations | M | ✅ |
| 2.12 | Migration round-trip test + per-table smoke integration | S | ✅ |

### 2.1 — Alembic setup and extension activation ☑

- [x] `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`; `env.py` wired to `DATABASE_URL`
      from application settings using the `psycopg` (psycopg3) async dialect
- [x] `app/infrastructure/database/base.py` — single `Base(DeclarativeBase)` used by all ORM models;
      `alembic/env.py` points `target_metadata` at `Base.metadata`
- [x] `alembic/versions/0001_activate_extensions.py` — `CREATE EXTENSION IF NOT EXISTS` for
      `vector`, `rum`, `pg_cron`, `pg_trgm`; downgrade is an intentional no-op
- [x] `alembic upgrade head` confirmed at `0001 (head)` against the Supabase project — all four
      extensions activated; `rum` and `pg_cron` were available on the free tier

### 2.2 — Knowledge Base, Document & Page models ☑

- [x] `KnowledgeBaseModel` → `knowledge_bases`: `id`, `user_id`, `name`, `description`, `subject`,
      `learning_goal`, `preferred_language`, `explanation_level`, `exam_date`, `graph_enabled`,
      `active_index_version`, `active_graph_version`, `created_at`, `updated_at`
- [x] `DocumentModel` → `documents`: `id`, `user_id`, `knowledge_base_id`, `filename`,
      `content_type`, `byte_size`, `storage_key`, `status`, `title`, `page_count`, `checksum`,
      `language`, `failure_reason`, `created_at`, `updated_at`, `processed_at`
- [x] `DocumentPageModel` → `document_pages`: `id`, `user_id`, `knowledge_base_id`, `document_id`,
      `page_number`, `kind`, `width`, `height`, `rotation`, `ocr_confidence`, `processed_at`
- [x] Every scoped table carries `user_id` + `knowledge_base_id` (§5)
- [x] FK `documents.knowledge_base_id → knowledge_bases.id ON DELETE CASCADE`
- [x] FK `document_pages.document_id → documents.id ON DELETE CASCADE`
- [x] Migration `0002_knowledge_bases_documents_pages.py` applied at `0002 (head)` against Supabase
- [x] `alembic/env.py` imports models package so autogenerate sees all tables
- [x] `test_metadata_starts_empty` removed from `test_alembic_setup.py` (became fragile once models
      are imported in the same pytest process)
- [x] 35 unit tests across `TestKnowledgeBaseModel`, `TestDocumentModel`, `TestDocumentPageModel`,
      `TestSchemasMigration`

### 2.3 — Chunk models, embedding column, tsvector column, versioning columns ☑

- [x] `DocumentElementModel` → `document_elements`: `id`, `user_id`, `knowledge_base_id`,
      `document_id`, `page_number`, `element_type`, `text`, `reading_order`, `processing_method`,
      bounding box (x0/y0/x1/y1), `heading_path TEXT[]`, `confidence`, `created_at`
- [x] `ChunkModel` → `chunks`: core columns plus `embedding VECTOR(384)` (pgvector), `tsv TSVECTOR`
      (trigger-maintained), versioning columns (`embedding_model_id`, `embedding_dimension`,
      `embedding_version`, `index_version`), `parent_chunk_id` (self-ref FK), `source_element_id`
      (FK → document_elements)
- [x] `ChunkElementModel` → `chunk_elements`: composite PK `(chunk_id, element_id)`, both FK ON
      DELETE CASCADE
- [x] `chunks_tsv_update` trigger function + `chunks_tsv_trigger` BEFORE INSERT/UPDATE trigger
      — tsvector maintained automatically; never written from Python
- [x] Migration `0003_document_elements_chunks.py` applied at `0003 (head)` against Supabase
- [x] Fix: `server_default` for `TEXT[]` columns must use `sa.text("'{}'")`  not a plain string
      (plain strings are SQL-quoted by Alembic, turning `'{}'` into the string `'{}'` instead of
      the array literal)
- [x] Fix: `import sqlalchemy as sa` in `chunk.py` to access `sa.text()` without collision with the
      `text: Mapped[str]` column attribute that shadows the `text` import inside the class body
- [x] 40 unit tests across `TestDocumentElementModel`, `TestChunkModel`, `TestChunkElementModel`,
      `TestChunksMigration`

### 2.4 — Retrieval indexes

- [x] HNSW index on `chunks.embedding` using pgvector's `vector_cosine_ops` operator class
      (`m=16, ef_construction=128`)
- [x] `rum` index on `chunks.tsv` for BM25-style full-text retrieval (D-12)
- [x] Six composite scoped indexes on `(user_id, knowledge_base_id, ...)`:
      `document_id` · `chunk_type` · `index_version` · `language` · `ordinal` · `content_hash`
- [x] All indexes in a dedicated migration (`0004`) so they can be rebuilt without touching
      table DDL; 10 unit tests; migration applied at `0004 (head)`

### 2.5 — Conversation, Message & Memory models

- [x] `conversations`: `id`, `user_id`, `knowledge_base_id`, `title`, active document /
      page / figure / table UUIDs, `rolling_summary` (nullable TEXT), `created_at`,
      `updated_at`; FK to `knowledge_bases` and `documents`
- [x] `messages`: `id`, `conversation_id`, `user_id` and `knowledge_base_id` (denormalized for
      RLS), `role`, `status`, `content`, `rewritten_query`, and four separate model-metadata
      columns (`model_id`, `prompt_tokens`, `completion_tokens`, `finish_reason`)
- [x] `conversation_retrieval_chunks` join table — composite PK `(message_id, chunk_id)`,
      `rank`, `score`, `created_at` for future range partitioning (D-15); no `PARTITION BY`
      declared yet
- [x] `memory_facts`: `id`, `user_id`, `knowledge_base_id`, `memory_type`, `content`,
      `provenance` (INTEGER ordinal of `MemoryProvenance` IntEnum), `status`, `valid_from`,
      `valid_until`, `superseded_by` (self-referential FK ON DELETE SET NULL), `created_at`,
      `updated_at`; scope + status composite index for retrieval
- [x] Migration `0005` applied at `0005 (head)`; 33 unit tests; 607/607 suite passing

### 2.6 — Graph models and traversal indexes

- [x] `graph_entities`: `id`, `user_id`, `knowledge_base_id`, `entity_type`, `name`,
      `description`, `source_document_id`, `source_chunk_id`, `page_number` (all nullable
      for structural nodes), `graph_version` (server_default=1), `created_at`, `updated_at`
- [x] `graph_relationships`: `id`, `user_id`/`knowledge_base_id` (denormalized for RLS),
      `source_entity_id`, `target_entity_id`, `relationship_type`, `source_chunk_id`,
      `page_number`, `evidence` — all three provenance columns NOT NULL at the schema level;
      `weight` (Float, default 1.0), `extraction_confidence` (nullable), `graph_version`
- [x] Bidirectional traversal indexes: `ix_graph_rels_source_entity_id` and
      `ix_graph_rels_target_entity_id` on `graph_relationships`
- [x] Canonical-name lookup index `ix_graph_entities_scope_name` on
      `(user_id, knowledge_base_id, name)`
- [x] Migration `0006` applied at `0006 (head)`; 27 unit tests; 634/634 suite passing

### 2.7 — Job queue, cache and pg_cron sweep

- [x] `processing_jobs`: `id`, `job_type`, `priority`, `status`, `attempt_count`,
      `max_attempts`, `payload` (JSONB), `scheduled_at`, `lease_expires_at`,
      `last_heartbeat_at`, `failure_reason`, `created_at`, `updated_at`; composite
      `(status, priority)` claim index for `FOR UPDATE SKIP LOCKED`
- [x] `cache_entries` as an UNLOGGED table: `key` (TEXT PK), `value` (BYTEA), `expires_at`;
      partial index on `(expires_at) WHERE expires_at IS NOT NULL`; note: SQLAlchemy has no
      Table kwarg for UNLOGGED so the ORM model carries no `__table_args__` — the migration's
      raw `CREATE UNLOGGED TABLE` statement is the sole DDL source
- [x] `pg_cron` schedule `sweep-expired-cache` registered in migration; runs every minute
- [x] Migration `0007` applied at `0007 (head)`; 26 unit tests; 660/660 suite passing

### 2.8 — Row-Level Security policies

- [x] `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on all 12 scoped tables
- [x] `FOR ALL` policy (`USING` + `WITH CHECK`) per table keyed to `auth.uid()`; 10 direct tables
      use `user_id = auth.uid()`, 2 bridge tables (`chunk_elements`,
      `conversation_retrieval_chunks`) delegate via EXISTS subquery to their scoped parent
- [x] System tables (`processing_jobs`, `cache_entries`) left untouched — no user scope
- [x] No `FORCE ROW LEVEL SECURITY`; no service-role bypass — deferred to Phase 3
- [x] Migration `0008` applied at `0008 (head)`; 16 unit tests; 676/676 suite passing

### 2.9 — Async session factory and ScopedRepository base

- [x] `AsyncEngine` built from `DATABASE_URL` with psycopg3 async driver (not asyncpg — see A-220)
      via `build_engine(settings.database)` in `infrastructure/database/session.py`; pool
      parameters come from `DatabaseSettings`
- [x] `AsyncSession` factory via `build_session_factory(engine)` with `expire_on_commit=False`;
      wired into `Container.session_factory` in `wire.py`; stub placed there when `DATABASE_URL`
      is absent so the Container still constructs in tests
- [x] `ScopedRepository` abstract base in `infrastructure/database/repository.py`: stores
      `_scope` + `_session`; raises `InvariantViolationError` if anything other than a
      `ScopeContext` is passed; provides `_scope_filter(model)` (AND user_id + kb_id) and
      `_user_filter(model)` (user_id only) helpers
- [x] `get_session` FastAPI dependency in `session.py` reading `request.app.state.container.session_factory`
- [x] No migration; 25 unit tests; 701/701 suite passing

### 2.10 — KnowledgeBaseRepository, DocumentRepository & ChunkRepository ✅

- [x] SQLAlchemy implementations of the three repository protocols defined in Phase 1
- [x] All methods receive `ScopeContext` as first argument and delegate filtering to `ScopedRepository`
- [x] Each scoped method checks the caller's `ScopeContext` against the one the repository was
      constructed with, raising `ScopeViolationError` before any statement is issued
- [x] `ChunkRepository.save_batch` stores chunks without embeddings; embedding worker populates them later
- [x] Tests use `pytest-asyncio` with an async SQLite in-memory engine (KB, Doc, Page) and mock session (Element, Chunk) for fast isolation

### 2.11 — ConversationRepository, MemoryRepository, GraphRepository & JobRepository ✅

- [x] SQLAlchemy implementations of all four remaining repository protocols from Phase 1
- [x] `SqlJobRepository` is a plain class (no `ScopedRepository` base); worker methods have no scope
- [x] `JobRepository.claim_next` uses `SELECT ... FOR UPDATE SKIP LOCKED` (PostgreSQL-specific)
- [x] `JobRepository.list_for_scope` filters by `payload["knowledge_base_id"]` JSONB access
- [x] `SqlGraphRepository.delete_for_document` deletes entities; relationships cascade at DB level
- [x] SQLite tests for Conversation, Memory, and Graph (all use standard SQL types); mock tests for Job (JSONB payload)
- [x] `sqlite_session` fixture extended with conversations, messages, memory_facts, graph_entities, graph_relationships tables
- [x] 129 repository tests total across all seven repository test files (steps 2.10 + 2.11)

### 2.12 — Migration round-trip test and per-table smoke integration

- [x] `test_migrations_at_head` — non-destructive: query `alembic_version`, assert == "0008"
- [x] `test_migration_round_trip` — destructive round-trip (`downgrade base` → `upgrade head`)
      via subprocess; guarded by `ALLOW_DESTRUCTIVE_MIGRATION_TEST=1`
- [x] Per-table smoke inserts (all raw SQL via `text()`, rolled-back transactions):
      `knowledge_bases`, `documents`, `document_pages`, `chunks`, `conversations`,
      `memory_facts`, `graph_entities`, `processing_jobs`
- [x] RLS check: insert as postgres → `SET LOCAL ROLE anon` → `SELECT count(*) = 0`
- [x] Tests marked `integration`, skipped when `TEST_DATABASE_URL` not set
- [x] `integration` marker added to pyproject.toml `markers` list
- [x] `WindowsSelectorEventLoopPolicy` set in integration conftest (psycopg3 requirement)
- [x] 836 unit tests unaffected; 10 integration tests collect cleanly

## Phase 3 — Authentication, Knowledge Base CRUD & API surface

Covers §7 (API process), §10, §61, §62 baseline, §64 first tests.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 3.1 | Supabase JWT verification + `get_current_user` FastAPI dependency | M | ✅ |
| 3.2 | KB ownership dependency → `ScopeContext`; 404 on foreign or missing KB | S | ✅ |
| 3.3 | Middleware: trace ID, CORS, request logging, exception-to-HTTP mapping | M | ✅ |
| 3.4 | Observability baseline: structlog pipeline, `TraceContext`, stage timers | M | ✅ |
| 3.5 | `/api/v1/knowledge-bases` CRUD — 5 endpoints, Pydantic schemas | M | ✅ |
| 3.6 | §61 route skeletons — every remaining endpoint returning 501 | S | ✅ |
| 3.7 | Security tests: cross-user KB access, cross-KB access, unauthenticated access | M | ✅ |

### 3.1 — JWT verification + auth dependency ✅

Built with **RS256 verified against Supabase's JWKS**, not the HS256 shared secret this step
originally specified — `SupabaseSettings` already carried `jwks_url` and `jwks_cache_seconds`, so
the asymmetric path was the consistent choice and no `SUPABASE_JWT_SECRET` was introduced
(A-252). The dependency landed in `app/api/dependencies/`, not `app/api/deps/`, and that
directory name is what every later step follows (A-256).

- [x] `app/infrastructure/auth/jwt.py` — `decode_jwt(token: str) → dict`:
      validates signature (RS256 against the JWKS in `app/infrastructure/auth/jwks.py`), expiry,
      and audience `"authenticated"`; raises `AuthenticationError` on any failure
- [x] `app/api/dependencies/auth.py` — `get_current_user` FastAPI dependency:
      extracts Bearer token from `Authorization` header; calls `decode_jwt`;
      returns `user_id: uuid.UUID` from the `sub` claim; 401 on missing or invalid token
- [x] `PyJWT` added to `core` dependency group
- [x] Tests: valid token → `user_id`, expired token → 401, wrong audience → 401, missing
      header → 401, malformed token → 401

### 3.2 — KB ownership dependency ✅

- [x] `app/api/dependencies/scope.py` — `get_kb_scope` FastAPI dependency:
      takes `kb_id: uuid.UUID` from path + `user_id` from 3.1 + `AsyncSession` from DI;
      queries `knowledge_bases WHERE id = :kb_id`; returns 404 if not found **or** if the
      row belongs to a different user — the two cases are indistinguishable to the caller
      (FR-AUTH-13); returns `ScopeContext(user_id, kb_id)` on success
- [x] Tests: own KB → ScopeContext; foreign KB → 404; missing KB → 404

### 3.3 — Middleware ✅

- [x] `app/api/middleware/trace.py` — generates a UUID trace ID per request, stores it in a
      `ContextVar`, adds it to the response as `X-Trace-ID`
- [x] `app/api/middleware/errors.py` — exception handler registered on the FastAPI app:
      `NotFoundError` → 404, `ScopeViolationError` → 404 (never 403, FR-AUTH-13),
      `AuthenticationError` → 401, `InvariantViolationError` → 422, unhandled → 500;
      every response body is `{"detail": "<message>", "trace_id": "<id>"}`
- [x] `app/api/middleware/logging.py` — ASGI middleware that logs method, path, status code,
      and duration via structlog on every request/response; redacts `Authorization` header value
- [x] CORS middleware registered in `main.py` using `CORS_ORIGINS` from settings
- [x] Tests: trace ID present in response headers; domain errors map to correct HTTP codes;
      auth header value never appears in log output

### 3.4 — Observability baseline ✅

- [x] `app/application/observability/context.py` — `TraceContext`: `ContextVar` holding the
      current trace ID and optional user ID; `bind()` and `get()` helpers used by log processors
- [x] `app/application/observability/timer.py` — `StageTimer`: context manager that measures
      elapsed time for a named stage; `elapsed_ms()` returns an integer; used in Phase 9 onward
      for the 17 §62 stage timers
- [x] `app/infrastructure/observability/structlog_setup.py` — call-once `configure_structlog()`:
      adds timestamp, log level, trace ID (from `TraceContext`), and a PII redaction processor
      that strips any key matching `prompt`, `document_text`, `model_output` in production
      (`DEBUG_ALLOW_CONTENT_LOGGING` setting gates the exception); outputs JSON in production,
      coloured console in development
- [x] `app/infrastructure/observability/invocation_log.py` — `write_model_invocation()`:
      writes a structlog event `model_invocation` with `model_id`, `task`, `prompt_tokens`,
      `completion_tokens`, `latency_ms`, `trace_id`; Phase 8 adds a DB write on top of this
- [x] `configure_structlog()` called in the FastAPI lifespan before any handlers register
- [x] Tests: redaction processor strips flagged keys in production mode and passes them in
      debug mode; `StageTimer` reports correct elapsed time; `TraceContext` is request-scoped
      (one request's trace ID does not leak to another)

### 3.5 — Knowledge Base CRUD API ✅

- [x] `app/api/schemas/knowledge_base.py` — Pydantic v2 schemas:
      `CreateKnowledgeBaseRequest` (name required; description, subject, learning_goal,
      preferred_language, explanation_level, optional_exam_date all optional);
      `UpdateKnowledgeBaseRequest` (all fields optional);
      `KnowledgeBaseResponse` (full field set including timestamps)
- [x] Five endpoints under `/api/v1/knowledge-bases` in `app/api/routers/knowledge_bases.py`:
      `POST /` → create row via `KnowledgeBaseRepository`, return 201 + `KnowledgeBaseResponse`;
      `GET /` → list all KBs for `user_id`, return 200 + list;
      `GET /{kb_id}` → single KB via `get_kb_scope`, return 200;
      `PATCH /{kb_id}` → partial update, return 200;
      `DELETE /{kb_id}` → delete KB + all child rows (CASCADE in schema), return 204
- [x] Router registered on the FastAPI app in `main.py`
- [x] Every response includes `X-Trace-ID` via the trace middleware from 3.3
- [x] Tests: 201 on create; 200 list returns only the requesting user's KBs; 404 on get/update/delete
      for a foreign KB; 401 when no token supplied; 422 on missing required field; 204 on delete

### 3.6 — §61 route skeletons ✅

- [x] One router file per resource group, each endpoint returning
      `{"detail": "Not implemented", "phase": "<N>"}` with HTTP 501:
      documents (§11, Phase 4), conversations + messages (§23, Phase 9),
      graph (§57, Phase 12), study content (§46, Phase 15), memory (§42, Phase 14)
- [x] All skeleton routes wired through `get_current_user` and `get_kb_scope` so auth + scope
      enforcement is active from day one — the 501 body is never reached without a valid token and
      an owned KB
- [x] Routers registered in `main.py`; OpenAPI document lists all endpoints at their final paths
- [x] Test: `GET /api/v1/knowledge-bases/{kb_id}/conversations` with a valid token returns 501;
      the same call without a token returns 401 (auth fires before the 501)

### 3.7 — Security tests: authentication and KB access ✅

- [x] `tests/security/test_kb_access.py` — marked `security` and `gate`:
      cross-user KB access → 404 (user A's valid token, user B's KB ID);
      unauthenticated access to any endpoint → 401;
      expired token → 401;
      valid token but KB does not exist → 404
- [x] `tests/security/test_rls_api.py` — end-to-end RLS check via the API layer:
      create a KB as user A (direct DB insert, bypassing auth); attempt to read it as user B
      via the API; assert 404 is returned and no KB data is disclosed in the error body
- [x] All security tests runnable standalone: `uv run pytest -m security`
- [x] UC-01 (sign-in, token issued) and UC-02 (create KB) acceptance criteria met by the CRUD
      tests in 3.5 and the security tests here

## Phase 4 — Storage, upload flow, job queue & worker

Covers §7 (worker), §11, §12, §60.

**Status: ~95% — recovery gaps closed.** The job entity's retry lifecycle is now connected:
a failed attempt schedules its own retry, a job whose worker died is reclaimed as a failed
attempt, and a budget that runs out dead-letters. `max_attempts` means what it says.

Deletion completes. `DELETE /documents/{id}` still returns 202 and marks the document
`DELETING`, and now a worker finishes the job — removing the stored original, the cached
page renders, and the row, with chunks, elements and pages following by cascade.

What remains is small and mostly waiting on other phases: per-stage progress reporting
needs the stages that phases 5 to 7 produce, and no endpoint issues a presigned URL yet,
so there is nothing whose expiry a security test could check.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 4.9 | Retry with backoff — failed jobs return to the queue until attempts are exhausted | M | ✅ |
| 4.10 | Lease-expiry reclaim — an orphaned job becomes a failed attempt | S | ✅ |
| 4.11 | `DELETE_DOCUMENT` consumer — remove the stored file, the cached renders, and the row | M | ✅ |

4.9 comes first because reclaim routes through the retry path: building 4.10 first would mean
building the same machinery twice.

### 4.9 — Retry with backoff ✅

- [x] `ProcessingJob.fail` records when the job becomes eligible again, computed as an exponential
      backoff from `attempt_count` and clamped to `backoff_max_seconds`. A job that has used its
      last attempt goes to `DEAD_LETTER` instead, which is what finally makes that state reachable
- [x] `claim_next` claims `PENDING` jobs and `FAILED` jobs whose delay has elapsed and whose
      attempts remain, requeueing then claiming in one transaction. One query rather than a
      separate scheduler, and `FAILED` stays an observable state between attempts rather than
      being skipped through
- [x] The worker no longer marks a document `FAILED` on every exception. It stays `PROCESSING`
      while a retry is pending and flips to `FAILED` only when the job dead-letters — so the
      status a student is shown means what it says
- [x] Tests: backoff grows with each attempt and stops at the ceiling; a job is not claimable
      before its delay elapses and is after; the last attempt dead-letters rather than failing;
      a dead-lettered job is never claimed again

### 4.10 — Lease-expiry reclaim ✅

- [x] `claim_next` also considers `RUNNING` jobs whose lease has expired, treating the lost
      attempt as a failure so it re-enters 4.9's path with its attempt counted
- [x] Routed through `FAILED` rather than straight back to `PENDING`: a crashed worker's job *is*
      a failed attempt, and a job that reliably kills its worker would otherwise retry for ever
      without ever exhausting its attempts
- [x] Tests: a job whose lease has expired is reclaimed; one whose lease is still valid is not,
      even while its worker is silent; a reclaimed job counts the lost attempt; repeated crashes
      eventually dead-letter rather than looping

- [x] Implemented as its own sweep, `reclaim_expired`, rather than folded into
      `claim_next`. A reclaimed job is not immediately claimable — it has just failed, so
      it waits out a backoff like any other failure — and a method called `claim_next`
      that wrote to the database and then returned nothing would be a surprising thing to
      read. The worker sweeps once per poll before claiming
### 4.11 — Deletion consumer ✅

- [x] The worker claims `DELETE_DOCUMENT` alongside `DOCUMENT_INGESTION`
- [x] The handler removes what the database cannot reach — the stored original, and the cached
      page renders — then deletes the row. Chunks, elements and pages follow by cascade;
      `graph_entities.source_document_id` is `SET NULL` deliberately, because §58 preserves
      entities that other documents also support
- [x] Idempotent throughout, since a retried deletion must be safe: removing an object that is
      already gone is a success, not a failure
- [x] Tests: the stored file is removed; cached renders are removed; the row is gone and its
      chunks with it; running the handler twice succeeds; a document already deleted by another
      path does not fail the job

**Not in scope, deliberately.** Index-version bumping and cache invalidation belong to Phase 16,
where the answer cache they would invalidate is actually built — writing them now would mean
writing them against a consumer that does not exist. Knowledge Base deletion has the same gap one
level up: `DELETE /knowledge-bases/{id}` removes the row and relies on cascades, which leaves every
document's stored object orphaned in R2. It is a second job type and a second step, recorded here
so it is not mistaken for done.

- [x] R2 adapter behind `StoragePort` — S3-compatible presigned URLs, private bucket,
      `{user_id}/{kb_id}/{document_id}/original.pdf` (D-08)
- [x] Separate cache prefix with TTL for page renders (D-13)
- [x] Upload endpoint: MIME, magic-byte, size and page-count validation → `documents` row →
      storage write → `DOCUMENT_INGESTION` job → returns ID and status
- [x] Status lifecycle `PENDING → PROCESSING → COMPLETED → FAILED → DELETING`
- [x] Job queue: `FOR UPDATE SKIP LOCKED`, `INTERACTIVE`/`NORMAL`/`BACKGROUND` priorities,
      heartbeat, dead-letter on attempt exhaustion
- [x] Separate worker process sharing domain and application code, graceful shutdown
- [x] Status polling endpoint (per-stage progress still pending — there is one status, not a
      stage breakdown, because the stages it would report belong to phases 5–7)
- [x] Security tests: upload into a foreign KB, storage-key isolation
- [ ] Signed-URL expiry test — no endpoint issues a presigned URL yet, so there is nothing to
      expire; the adapter method exists and is unit-tested
- [x] UC-04, UC-05 (subject to ingestion being a skeleton — see Phase 5)

## Phase 5 — PDF parsing, page classification & OCR

Covers §13, §14, §15, §16.

**Status: first pass complete — 6 of 6 steps. OCR deferred pending reassessment.** `app/infrastructure/parsing/` and
`app/infrastructure/ocr/` are empty packages. What exists instead is a deliberate placeholder:
`_extract_pdf_pages` in `app/worker/__main__.py` reads native text with `pypdf` and skips pages
that return none. A scanned page yields nothing and the document still completes, so it is
indexed as though empty — a silent failure this phase turns into a recorded `PageKind`.

**The domain layer for this phase already exists.** `DocumentPage`, `DocumentElement`, `PageKind`,
`ProcessingMethod` and `ElementType` were written in Phase 1; `PdfParserPort` and `OcrPort` are
declared; `save_pages`, `get_pages`, `save_elements` and `get_elements` are implemented against
`document_pages` and `document_elements` from Phase 2. Phase 5 is adapters and wiring — no new
entities, no migration.

Two §16 requirements are consequently satisfied before any parser is written, by construction
rather than by discipline: `DocumentElement.text` is `UntrustedText`, so extracted text cannot
reach a prompt as instruction; and an element whose `processing_method` is `OCR` or `OCR_VL`
cannot be constructed at all without a bounding box and a confidence, because the entity raises.

**Split into two passes.** Steps 5.1–5.6 are ordinary work against libraries already installed and
serve native-text documents completely. OCR is deferred to a second pass and reassessed once real
parsed output exists — R-04 identified this install class as the highest-risk in the project, and
there is no reason to carry that risk inside an otherwise low-risk phase.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 5.1 | `PageClassifier` — pure rules over per-page signals → `PageKind` | S | ✅ |
| 5.2 | `PdfPlumberParser` behind `PdfParserPort`; golden-file tests introduced | M | ✅ |
| 5.3 | Rewire ingestion — parse, classify, persist pages and elements | M | ✅ |
| 5.4 | Element typing — headings, lists, captions, formulas, table and figure regions | M | ✅ |
| 5.5 | Reading-order resolution, multi-column handling, `heading_path` | M | ✅ |
| 5.6 | Page rendering via `pypdfium2` into the TTL cache prefix | S | ✅ |
| — | **Reassess before committing to OCR** | | |
| 5.7 | PaddleOCR PP-OCRv6 adapter on **CPU** (D-27), per-region for mixed pages | L · risky | ☐ |
| 5.8 | PaddleOCR-VL fallback on §15 conditions only; Tesseract as emergency | M | ☐ |
| 5.9 | `OCR_PAGE` jobs, idempotent per-page re-run | M | ☐ |

### 5.1 — Page classification ✅

- [x] `app/domain/documents/page_classifier.py` — `PageSignals` (native character count, image
      area as a fraction of page area, vector-drawing count, text-block count) and
      `PageClassifier.classify(signals) → PageKind`. Pure and rule-based, in the same shape as
      `QueryClassifier`: the parser gathers the signals, the domain decides
- [x] Thresholds come from settings, never literals (D-20)
- [x] Tests: each of the four kinds; behaviour exactly at every threshold boundary; a page with
      no signals at all classifies rather than raising

### 5.2 — Native-text parser ✅

- [x] `app/infrastructure/parsing/pdfplumber_parser.py` implementing `PdfParserPort` — `pypdf`
      for document metadata, `pdfplumber` for per-page words, blocks and dimensions
- [x] Emits one `DocumentPage` per page carrying kind, width, height and rotation
- [x] Emits `DocumentElement`s typed `PARAGRAPH` with `processing_method = NATIVE_TEXT`, bounding
      boxes and sequential `reading_order`. Typing beyond paragraph is 5.4
- [x] `SCANNED` and `COMPLEX` pages return an empty element sequence, per the port's contract
- [x] **Golden-file tests introduced here** — a small fixture PDF committed with its expected
      page and element output; every later step in this phase extends the expectations rather
      than adding a separate test pass at the end
- [x] Tests: encrypted PDF, zero-page PDF and a malformed file all raise rather than returning
      partial output

### 5.3 — Rewire ingestion ✅

- [x] `IngestDocumentUseCase` takes `PdfParserPort` in place of the injected
      `pdf_page_extractor` callable; `_extract_pdf_pages` in `app/worker/__main__.py` is deleted
- [x] Pages and elements persisted through `DocumentRepository` before chunking begins
- [x] Chunking input is deliberately **unchanged** in this step — the chunker keeps consuming
      page text. Rewriting it over elements is Phase 7, and doing it here would mean writing the
      splitter twice, once before headings exist and again after
- [x] Tests: pages and elements are persisted under the calling scope; a document with no
      extractable text still completes with its pages recorded

### 5.4 — Element typing ✅

- [x] `HEADING` from font size relative to page body text, weight, and position; `LIST` from
      leading markers and hanging indents; `CAPTION` from proximity to a table or figure region
      plus a leading label; `FORMULA` from glyph and symbol density
- [x] `TABLE` and `FIGURE` **regions** detected and recorded with their bounding boxes. Their
      contents are Phase 6 — this step establishes only that a region is there and where
- [x] Tests: a heading is not classified from font size alone when the whole page is large type;
      a caption is not attached across a column boundary

### 5.5 — Reading order, columns and heading path ✅

- [x] Column detection from horizontal whitespace; reading order resolved within and then across
      columns rather than by raw y-coordinate
- [x] `heading_path` derived by carrying the heading stack down the resolved order, so every
      element knows the section it sits in
- [x] Tests: a two-column page orders left column fully before right; a figure spanning both
      columns does not break the order; `heading_path` survives a page break mid-section

### 5.6 — Page rendering ✅

- [x] `pypdfium2` render at the configured DPI, written to the R2 cache prefix with its TTL
      (D-13) — permanent storage is not used, because renders are regenerable
- [x] Idempotent per page: re-rendering replaces rather than accumulating
- [x] Tests: a render round-trips through the cache adapter; an expired entry returns `None`
      rather than stale bytes

### Second pass — OCR (5.7–5.9)

Deferred deliberately, and to be re-divided against what 5.1–5.6 actually produce. The proportion
of pages classified `SCANNED` or `COMPLEX` in real material is the number that should decide how
much of this is worth building, and that number does not exist yet.

- [ ] PaddleOCR PP-OCRv6 as primary, **running on CPU** — the 6 GB card is reserved for
      inference, embeddings and reranking, which is what makes `FR-PRF-02` satisfiable at all
      (D-27, R-07). Per-region for `MIXED` pages, with a confidence on every element
- [ ] PaddleOCR-VL fallback triggered **only** by the §15 conditions, never as a general retry —
      `NFR-PERF-17` caps this path at under 20% of pages and `NFR-PERF-12` allows it 120 s per
      complex page precisely because it is rare (D-28)
- [ ] Tesseract wired as emergency fallback only, never selected while either Paddle path is
      available
- [ ] `OCR_PAGE` jobs, idempotent per-page re-run — re-running a page replaces its elements
      rather than appending a second set
- [ ] Element `confidence` populated from the engine, not assumed; low-confidence extraction is
      recorded rather than silently accepted (A-098's 0.6 threshold is a placeholder awaiting
      exactly this data)

## Phase 6 — Table, figure, chart & diagram processing

Covers §17, §18.

**Status: not started.** Nothing produces a table, figure, chart or diagram record. The
`ChunkType` enum carries `TABLE`, `FIGURE`, `CHART` and `DIAGRAM`, and `Chunk.carries_a_visual`
is written and tested against them, but no chunk is ever created with any type other than `TEXT`.
`Conversation.active_table_id` and `active_figure_id` are stored and never set, because there is
nothing to select. Blocked on Phase 5.

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

**Status: ~75% — all three chunking steps done.** The fixed-width character window is gone.
Chunking now consumes the typed elements Phase 5 produces, places boundaries on the structure
they carry, counts sizes in real tokens, and writes two tiers: small children that retrieval
searches and the section-bounded parents they expand into. That was the single largest
constraint on retrieval quality in the system, and it is lifted.

What remains is not chunking. The reindex job has columns and no job, embedding still runs
inline in the ingestion job rather than as its own, and the milestone check — a real textbook
through every stage — has never been run, because the `ml` group is not installed in the active
environment (A-358) and no real model call has yet happened in this repository.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 7.1 | Real token counting behind a port | M | ✅ |
| 7.2 | Structure-aware child chunks, built from elements | L | ✅ |
| 7.3 | Parent chunks from sections, with `parent_chunk_id` linkage | M | ✅ |
| 7.4 | Parse and chunk a real textbook offline, and report what it did | M | ◐ |
| 7.5 | Install the `ml` group; prove the embedder runs | S | ✅ |
| 7.6 | Full ingestion against the real database and object store | M | ☐ |
| 7.7 | Query the ingested textbook end to end | M | ☐ |
| 7.8 | Recalibrate the tuning numbers from what was found | S | ☐ |

Steps 7.4 to 7.8 are the milestone check, divided so that each one adds a single dependency
rather than all of them at once. 7.4 needs nothing that is not already installed — no database,
no object store, no models — because the parser and the chunker are where the untested
assumptions are, and finding them there is far cheaper than finding them behind a worker, a
queue and a 2.5 GB download.

### 7.1 — Token counting ✅

- [x] `TokenCounterPort` in the domain, and an implementation over the `tokenizers` library
      loading the same vocabulary as the embedding model
- [x] Counts match what the embedding model will actually see, including its own input
      ceiling — a chunk sized against an estimate can exceed the model's limit and be
      silently truncated, losing the end of a passage that retrieval then cannot find
- [x] `Chunk.token_count` stops being `len(text) // 4`
- [x] Tests: counts agree with the model's tokenizer on known strings; the counter is
      cached rather than rebuilt per call; a missing vocabulary fails loudly at startup
      rather than silently producing estimates

### 7.2 — Child chunks from elements ✅

- [x] Chunking consumes `DocumentElement`s rather than flattened page text, which is the
      dependency 5.3 deliberately left in place until headings existed
- [x] Split priority chapter → section → subsection → paragraph, and a sentence split only
      where a single paragraph exceeds the ceiling on its own
- [x] Children 300–500 tokens, hard maximum ~700, overlap 70 (D-29)
- [x] Chunk types carried from element types: a table becomes a `TABLE` chunk holding its
      rows, a figure region a `FIGURE` chunk — separate but linked, never dissolved into
      the prose around them
- [x] Full §19 metadata: `heading_path`, `chapter`, `section`, `element_type`,
      `bounding_box`, `page_start` and `page_end` from the elements the chunk came from
- [x] Tests: no chunk splits a word; a chunk never spans two sections; a table's rows stay
      together; overlap is real text from the neighbouring chunk; a paragraph longer than
      the ceiling splits on sentences rather than mid-clause

### 7.3 — Parent chunks ✅

- [x] A parent is the content under one heading, which is what `heading_path` records.
      Loading one restores the section a fragment came from, which is what parent
      expansion exists to do
- [x] Parents 800–1500 tokens; a section longer than the ceiling splits within itself
      rather than merging with its neighbour
- [x] `parent_chunk_id` set on every child, so expansion has something to follow — the
      column has existed since Phase 2 and has never been written
- [x] Tests: every child names a parent; a parent contains its children's text; a section
      shorter than the floor still produces one parent rather than none; parents never
      straddle two sections
- [x] Only children are searched. Both retrievers exclude parents outright rather than
      relying on a parent having no embedding — the full-text trigger indexes every row it
      is given, so a section and a paragraph inside it would otherwise be returned as two
      separate results competing for the same slots

### 7.4 — Parse and chunk a real textbook offline — tool built, assessment blocked

- [x] `scripts/inspect_parse.py` takes a PDF path, runs the real `PdfPlumberParser` and
      `Chunker`, and reports what came out: page kinds, elements per page by type, the heading
      paths it inferred, chunk and parent counts, the token distribution against the configured
      targets, how many chunks breach the ceiling, and how many parents hold only one child
- [x] No database, no object store, no models — pdfplumber and the tokenizer are already
      installed, so this runs today on any machine with the file
- [x] Verified against all eight fixtures: columns reported on the two-column page, a chunk
      spanning the break on the section-across-pages page, and a refused file answered with a
      sentence rather than a traceback
- [x] The report carries its own unit tests, against the usual habit for scripts — it decides
      which tuning numbers move in 7.8, and both of its rules had defects (A-383, A-384)
- [ ] **Blocked:** read the output against the document itself — are the columns right, do the
      headings match the real section titles, does reading order follow the page. Needs a
      textbook PDF; the repository holds only fixtures this repository wrote (A-387)
- [ ] **Blocked:** the written assessment of where the parser is wrong and which tuning numbers
      need to move

### 7.5 — Install the `ml` group; prove the embedder runs ✅

- [x] `uv sync --group ml` — torch 2.13.0+cu126, sentence-transformers 5.6.1, transformers
      5.14.1, paddle 3.3.1 and paddleocr 3.7.0 as the CPU build, exactly as D-27 specified
- [x] The card is real and usable: RTX 3050 6 GB, driver 555.97, sm_86, and a matmul on it
- [x] Ten tests over the real model — 384 dimensions matching the reserved column width, one
      unit-length vector per text, stable across calls, unchanged by what it was batched
      alongside, and closer to a paraphrase than to another subject
- [x] Closes A-358 — `container.embedder` and `container.reranker` hold real adapters
- [ ] **Left open by decision:** the suite went from 26 seconds to 242, because sixteen tests
      build a container and each one now loads two models onto the GPU (A-391)

Three findings here matter more than the step did. The worker cannot reach Postgres on Windows
at all — `psycopg` refuses the event loop `asyncio.run` gives it, before any I/O — which blocks
7.6 until it is fixed (A-388). The API escapes the same fault only because the documented run
command uses `--reload` (A-389). And the environment verifier has been reporting a Postgres
failure that says nothing about the network (A-390).

### 7.6 — Full ingestion against the real database and object store

- [x] **Done ahead of the rest:** every process that starts its own loop now chooses one
      `psycopg` will run on, through `app/runtime.py` — the worker and the environment
      verifier. The API cannot choose, because uvicorn passes its own factory and ignores any
      policy set around it, so startup checks the loop it was handed and refuses to serve on a
      loop that cannot reach the database (A-396, A-397). The suite itself had been running on
      that unusable loop throughout (A-398)
- [x] Postgres answers: 17.6, with `vector`, `rum`, `pg_cron` and `pg_trgm` all present. What
      looked like a network failure was this fault the whole time (A-400)
- [ ] R2 credentials are still unset, and Ollama is not installed — 7.7 needs it
- [ ] Upload → job enqueued → worker claims it → pages, elements, chunks and embeddings persisted
      → document reaches `COMPLETED`
- [ ] First opportunity to run the integration suite, unrun since it was written (A-283)
- [ ] Expect to iterate, and re-ingestion still duplicates rather than replaces (A-312) — delete
      and re-upload between attempts, which the deletion path built in 4.11 supports

### 7.7 — Query the ingested textbook end to end

- [ ] Needs Ollama running with a model pulled; no real model call has ever happened here
- [ ] Ask real questions of the real document: dense and keyword retrieval, fusion, reranking,
      evidence assembly, a streamed answer with citations that open at the right page
- [ ] The first observation of retrieval quality on anything other than fixtures

### 7.8 — Recalibrate the tuning numbers from what was found

- [ ] Turn the findings into configuration changes and, where the fault is structural, code fixes
- [ ] Settle `complex_vector_drawing_threshold` (A-296), which was set to 400 without evidence
- [ ] Decide OCR on evidence rather than in advance: how many pages of a real textbook actually
      defeat the text layer decides whether 5.7 to 5.9 are worth building

- [x] **Child chunks 300–500 tokens, max ~700, 70 overlap; parents 800–1500** (§19, D-29) —
      two tiers, sized in real tokens counted against the embedding vocabulary
- [x] **Split priority chapter → section → subsection → paragraph → sentence** — boundaries come
      from the parsed structure, and sentences only where one paragraph exceeds the ceiling alone
- [x] **Chunk types** beyond `TEXT` — a table becomes a `TABLE` chunk holding its rows, a figure
      region a `FIGURE` chunk, never dissolved into the prose around them
- [x] **Full §19 chunk metadata** — `heading_path`, `chapter`, `section`, `element_type`,
      `bounding_box` and the page range all written from the elements a chunk came from, and
      `parent_chunk_id` set on every child, so Phase 10 has something to expand to
- [x] `bge-small-en-v1.5` on GPU, batched
- [x] pgvector writes with HNSW; `tsvector` population with `rum` indexes
- [x] Index versioning columns written on every chunk (`index_version`, `embedding_version`)
- [ ] Reindex job (§20) — the columns support it, no job exists
- [x] Embeddings generated during `DOCUMENT_INGESTION`; document flips to `COMPLETED`
- [ ] Separate `GENERATE_EMBEDDINGS` job — embedding runs inline in the ingestion job instead
- [x] Nothing with `processing_status != COMPLETED` is ever retrievable — enforced in SQL and
      covered by `tests/security/test_retrieval_security.py` as a release gate
- [ ] **Check:** a real textbook PDF completes every stage and is queryable

## Phase 8 — Model Gateway

Covers §48, §49, §50, §51, §52, §53, §54, and §55's warm-model requirement.

**Status: ~25%.** One adapter satisfies `ModelGatewayPort` directly and is wired straight into the
container — there is no gateway in front of it. Everything the gateway exists to provide (routing,
privacy enforcement, fallback, normalization) is therefore absent, and the single-provider setup
hides that, because with one local provider none of it is exercised.

- [ ] **Gateway façade → task router → capability registry → provider adapter** — the container
      holds `OllamaModelGateway` in the `model_gateway` slot; nothing sits between caller and
      provider
- [ ] Four capability interfaces: text generation, multimodal, embeddings, reranking — embeddings
      and reranking are separate ports (`EmbeddingPort`, `RerankerPort`), not gateway capabilities
- [x] §49 capability metadata including `data_boundary` — `ModelProfile` carries it
- [ ] §50 routing for all ten model tasks — `ModelProfile.tasks` declares the nine text tasks and
      `profile_for` rejects unsupported ones, but there is no router choosing between models
- [x] Ollama adapter implemented
- [ ] OpenAI-compatible adapter; Gemini and Anthropic raising `NotImplementedError` (D-17)
- [ ] Internal model keys resolvable at deployment, task or Knowledge Base level (§51) — one model
      id comes from settings and is passed to the adapter's constructor
- [ ] **Privacy policy (§52):** pre-flight `data_boundary` check; **no silent local-to-external
      fallback** — nothing reads `data_boundary` at call time
- [ ] **Fallback (§53):** `ProviderError` carries a `retryable` flag and no caller acts on it —
      there is no retry, no approved-fallback chain, and nothing logged
- [ ] **Prompt normalization (§54)** and per-model prompt profiles — the seven-slot `ModelRequest`
      is mapped to Ollama's chat array inside the adapter, which is the normalization step done
      once for one provider rather than as a shared stage
- [ ] Warm-up at startup for every configured model (§55) — `warm_models_on_startup` is defined in
      settings and read by nothing
- [ ] `model_invocations` written on every call — no such table exists;
      `write_model_invocation()` emits a structlog event only
- [ ] Security test: external-provider privacy violation blocked

## Phase 9 — Conversations, query understanding & retrieval core

Covers §23 through reranking, §24, §25, §26, §27, §28, §29, §41.

**Status: ~95%.** Built out of order, ahead of phases 5–8. The retrieval pipeline is complete and
the persistence layer was finished in steps 9.11–9.15, which also closed a defect where the
conversations router never committed — every write on this path was being discarded, and no unit
test could see it because they all assert against a mocked repository.

All fifteen steps are done. The open boxes below are individual fields and one unrun test, not
remaining stages — which is why the checkbox count reads lower than the percentage.

| Step | Deliverable | Done |
|---|---|---|
| 9.1–9.8 | Classifier, retrievers, fusion, expander, rewriter, reranker, orchestrator, stage timing | ✅ |
| 9.9 | Retrieval security tests — scope, document status, empty filters | ✅ |
| 9.10 | User and assistant message persistence around the stream | ✅ |
| 9.11 | `save_retrieval_chunks` on the repository | ✅ |
| 9.12 | Evidence record written from `AnswerUseCase` | ✅ |
| 9.13 | Evidence-record gate — stored set must equal prompt set | ✅ |
| 9.14 | Commit on conversation creation | ✅ |
| 9.15 | `ConversationUnitOfWork`; streamed writes commit in their own transaction | ✅ |

- [x] Conversation and message persistence; user message stored **before** generation; statuses
      `RECEIVED`/`COMPLETED`/`FAILED`; active document, page, figure and table
- [ ] `PROCESSING` status never used — a message goes `RECEIVED` → terminal
- [ ] **`rolling_summary`** — column exists, absent from the `Conversation` entity, never written.
      Deferrable: nothing reads it until Phase 14
- [x] Query rewriting — follow-ups resolved to standalone queries before search
- [ ] **Both forms stored (§24)** — the rewriter's output is used for retrieval and reranking and
      then discarded; `Message.rewritten_query` and `with_rewritten_query()` exist and are unused
- [ ] **Model metadata on assistant messages** — `model_id`, `prompt_tokens`,
      `completion_tokens` are always null, because `generate_stream` yields bare strings and
      never reports usage. Properly a Phase 8 fix
- [x] Deterministic classification into all 13 §25 classes — rule-based, no agent
- [x] Multi-query expansion: 2–3 variants, temperature 0, skipped when the plan forbids it (§26)
- [x] Hybrid retrieval: pgvector + full-text per variant, run concurrently, with **mandatory
      `user_id`, `knowledge_base_id`, `processing_status = COMPLETED` filters inside every query**
- [x] RRF with `k`=60 (§28)
- [x] Dense and keyword top-k, RRF pool, `ms-marco-MiniLM-L6-v2` over the candidate pool, fed the
      **resolved standalone question** (§29) — all sized from settings per D-20
- [x] Retrieval stages timed via `StageTimer` and emitted as structlog events
- [x] Security tests: cross-KB retrieval, non-`COMPLETED` document retrieval, empty-filter bypass
- [x] Evidence record persisted per answer, gated on equality with the prompt set — the
      prerequisite for Phase 11's "was this citation in context?" validation
- [ ] **Unverified:** `tests/integration/test_answer_persistence.py` proves the streamed writes
      reach PostgreSQL, and has never been run — it needs `TEST_DATABASE_URL` and commits real
      rows. Until it runs, durability on this path is argued, not demonstrated

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

**Status: ~5%.** Groundwork only, laid by earlier phases: the UNLOGGED `cache_entries` table and
its `pg_cron` sweep exist from step 2.7, and `R2CacheAdapter` with TTL-on-read exists from Phase 4.
No `CacheStore` port implementation reads or writes `cache_entries`, and the deletion path is
half-built — see the `DELETE_DOCUMENT` gap in Phase 4.

- [ ] `CacheStore` on UNLOGGED PostgreSQL — no Redis (D-14, ADR-005); table and sweep exist,
      nothing uses them
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

**Status: ~15%.** The observability baseline arrived early in step 3.4 and the security suite has
been growing alongside each phase — 109 tests marked `security`, 75 marked `gate`. What is entirely
absent is evaluation: no gold dataset, no metric harness, and no calibration, which means every
tuning number in `settings.py` is still the placeholder it was written as, and D-23's promise to
replace the derived latency budgets with measured p95 is unmet.

- [x] Stage timers via `StageTimer`, emitted as structlog events with elapsed milliseconds —
      retrieval stages only; the full §62 set spans phases not yet built
- [ ] Model metrics and operational metrics
- [x] **Logs never contain full private documents or prompts by default** (§62) — redaction
      processor strips `prompt`, `document_text` and `model_output` unless
      `DEBUG_ALLOW_CONTENT_LOGGING` is set
- [ ] Gold dataset: 40–60 labelled pairs from user-supplied PDFs across every query class (D-22)
- [ ] Retrieval evaluation: Recall@k, Precision@k, MRR, NDCG, document and page coverage, table,
      visual and graph-edge accuracy
- [ ] Reranking evaluation: recall before and after, MRR delta, pool size, latency
- [ ] Generation evaluation: all ten §63 metrics
- [ ] Multi-hop evaluation: all seven §63 metrics
- [ ] Memory evaluation: all seven §63 metrics
- [ ] Instruction-following evaluation: all five §63 metrics
- [ ] **All ten §64 security tests** in one suite — five files exist under `tests/security/`
      covering KB access, RLS through the API, upload, document deletion, retrieval scope and the
      evidence record; the rest await the phases they test
- [ ] **Six release gates as failing tests:** cross-user leakage 0 ✅ · cross-KB leakage 0 ✅ ·
      fabricated citation acceptance 0 (Phase 11 — the evidence record it depends on is in place)
      · deleted memory retrieval 0 (Phase 14) · unauthorized cache reuse 0 (Phase 16) · graph edge
      without provenance 0 (Phase 12)
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

Verify each with `uv run python scripts/verify_environment.py` after supplying it.

| Input | Needed by | Status |
|---|---|---|
| Supabase project URL, anon key, service key, database URL | Phase 2 | ✅ supplied; migrations applied at `0008 (head)` |
| Cloudflare R2 account ID, bucket name, access key ID, secret | Phase 4 | ✅ supplied as the `STORAGE_*` settings |
| Ollama installed with `gemma3:4b` pulled | Phase 8 | ☐ — not responding on `localhost:11434` |
| 2–3 educational PDFs with real tables and charts, for the gold evaluation set | Phase 17 | ☐ |
| `TEST_DATABASE_URL` for the integration suite | Phase 9 onward | ☐ — unset, so 15 integration tests skip |

Ollama being down does not fail the test suite, because every test that touches the gateway uses
a fake — which also means no test in the repository has ever exercised a real model call.

`TEST_DATABASE_URL` was not previously listed and should have been. Without it the integration
tests silently skip, including the one that proves streamed writes reach PostgreSQL. Per the
Supabase pooler note, it wants the session pooler host on port 5432, and the connection needs a
network that does not block outbound Postgres.
