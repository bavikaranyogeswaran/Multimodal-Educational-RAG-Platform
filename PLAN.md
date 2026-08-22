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
| Phases complete | **5 of 21** — Phase 0, 1, 2, 3, 8 ✅ |
| Effectively done | Phase 10 (~98%) · Phase 9 (~98%) · Phase 11 (~90%) · Phase 4 (~95%) — every remaining item is blocked on another phase or on an input, not on work in the phase itself |
| Partly built | Phase 7 (~75%, milestone check unrun) · Phase 5 (~70%, OCR deferred) · Phase 6 (~70%, visual records schema done, crops and OCR descriptions remain) · Phase 17 (~20%, evaluation absent) |
| Scaffold only | Phase 18 (~10%, step 0.5 shell) · Phase 16 (~5%, table and adapter but no `CacheStore`) |
| Not started | Phase 12, 13, 14, 15, 19, 20 |
| Tests | 2,686 unit and security — 2,599 unit, 87 security · 18 integration **passing against the live database**, 1 destructive round-trip skipped by design · 121 marked `security`, 87 `gate` · one known flaky test, a Windows timer-granularity assertion unrelated to the code under test |
| Next step | **6.7 — OCR and visual description** (needs Ollama) |
| Last updated | 22 August 2026 (step 6.5 — crops to object store) |

Phases 0 through 3 are complete, and so is Phase 8. Phase 9 was built well ahead of phases 4
through 8 being finished, so the numbering no longer describes the build order — work jumped to
conversations and retrieval once the data model and API surface were in place. Ingestion now
parses into typed elements in reading order and chunks on the structure those elements carry, so
§19 is built and the ceiling it put on retrieval quality is lifted. Two holes remain on that
path: pages whose text layer cannot be trusted are recorded and left unread, since Phase 5
deferred recognition pending a real textbook to calibrate against, and Phase 6 has not been
started at all, so nothing visual is described or answerable.

**The percentages above were reconciled against the source tree on 22 August 2026, and several
of them moved.** Phases 12 and 14 had been carrying a "foundations only, ~15%" figure that
described work belonging to phases 1 and 2 — the entities and the tables — rather than anything
either phase had done; `app/infrastructure/graph/` holds nothing but an `__init__.py`, and no
memory code exists outside its Phase 1 entity and Phase 2 repository. Both now read as not
started, which is what they are. Phase 16 was likewise credited at 20% in the header while its
own section said 5%; nothing reads or writes `cache_entries`, so 5% is the honest figure.

Phase 11 now closes the loop the milestone names, and the answer it produces is traceable after
the fact rather than only correct at the time. A generated answer is parsed against the output
schema, every cited label is checked against the evidence set that was actually sent, each claim
that survives is checked for entailment against the passages it rests on, and the prose the
student actually reads is checked against those claims — because an answer whose claims are each
impeccable can still assert something none of them established. A repairable answer gets exactly
one corrective attempt and no more; anything still ungrounded is refused rather than shown.

What the turn leaves behind is now the point. Two records are written, and they are deliberately
different: the evidence set records what the model *could* have known, the citations record what
it *actually used*, and the gap between them is the thing worth being able to see. Each citation
carries the document, page, type, bounding box and content hash the passage had at the moment it
was cited, copied onto the row rather than joined from the chunk — reprocessing rewrites chunks,
and a citation resolved against current text would quietly begin describing a passage the answer
never saw. Alongside them sit what the call cost and a fingerprint of the prompt that produced
it, so two answers written under different prompts stay distinguishable when their quality is
compared.

§40 is met except for its *object* field, which waits on Phase 6 to create the tables and figures
it would name.

Migrations applied through **`0016 (head)`** against Supabase — `0011` (model_invocations) was
applied on 22 August 2026, having been written in step 8.4 and waiting on a connection since.
Migrations `0012–0015` were applied on the same day. Migration `0016` (crop_key column on
document_figures) was applied on 22 August 2026 as part of step 6.5. Eighteen SQLAlchemy models
registered with `Base.metadata`.

**Neither ruff nor mypy is clean across `app/`.** ruff reports 25 findings and mypy 3, all of
them predating this session's work and none in a file it touched — line lengths and unused `noqa`
directives in the Gemini and Anthropic stubs, an over-long `execute` in the answer use case, two
`TRY300`s in the gateway, and an unused argument in the job repository. Both counts were verified
against the previous commit; ruff was 27 there, so this session reduced it. The long-standing
"ruff and mypy clean" line had been carried forward without either being re-run against the whole
package, and re-running it on individual files is what kept the claim looking true (A-672, A-694).
The test tree is held to neither standard and carries a little lint debt of its own (A-655).

The `message_citations` row-level security policy is verified against PostgreSQL rather than
argued for: SQLite cannot express row-level security, so until the migration was applied the
policy had only ever been read. The destructive migration round-trip remains gated behind
`ALLOW_DESTRUCTIVE_MIGRATION_TEST=1` and has not been run — the chain is verified forward from
`0008` to `0010`, not as a full rebuild.

**Two known flaky tests**, neither caused by the code under test:

- `test_stage_timer.py::test_measures_real_elapsed_time` — fails roughly one run in three.
  Asserts at least 20 ms elapsed after a 20 ms sleep, which Windows timer granularity does not
  reliably satisfy.
- `test_container.py::test_lifespan_stores_container_on_app_state` — fails intermittently with
  `httpx.RemoteProtocolError: Server disconnected without sending a response`, and passes on its
  own. Building a container constructs the token counter, which calls
  `Tokenizer.from_pretrained` and revalidates its vocabulary against HuggingFace over the
  network. On a connection that accepts the TCP handshake and then returns nothing — the same
  failure mode this network shows against Postgres — that surfaces as a protocol error rather
  than a refusal. **The suite should not need the internet to run**; setting `HF_HUB_OFFLINE`
  once the vocabulary is cached, or injecting a pre-built tokenizer in tests, would fix it.

`test_container.py::test_every_slot_raises_not_implemented_on_access` was listed here and no
longer fails.

**Documentation debt carried into Phase 20.** `REQUIREMENTS.md` has no status column against its
334 functional requirements, and `USE_CASES.md` tracks no implementation status. Against the
standing constraint that every step updates it, `EXECUTION_LOG.md` is missing entries for
**steps 3.3–3.7, 4.1–4.8, 9.1–9.10 and 10.6** — the phases built before the discipline took hold,
plus one later omission. Everything from step 4.9 onward is recorded. The transaction boundaries
introduced in step 9.15 are now described in `ARCHITECTURE.md` §5.4, so that item is cleared.

One structural wrinkle in the log itself: entries appear under `## Step N.M` in some places and
`### Step N.M entries` in others, and the phases are not in numerical order because the build was
not either. Reading it front to back does not give the build order; the headings do.

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

**Status: ~70% — first pass complete, 6 of 6 steps. OCR deferred pending reassessment.**
`app/infrastructure/parsing/` now holds `pdfplumber_parser.py`, and the placeholder it replaced —
`_extract_pdf_pages` in `app/worker/__main__.py`, which read native text with `pypdf` and silently
skipped pages that returned none — was deleted in step 5.3. A page whose text layer cannot be
read is now classified and recorded as a `PageKind` rather than indexed as though empty.

**`app/infrastructure/ocr/` is still an empty package**, so a `SCANNED` or `COMPLEX` page is
recorded accurately and then left unread. That is the honest failure the placeholder used to
hide, but it is still a hole: nothing in a scanned textbook is retrievable.

**The domain layer for this phase was already in place before it started.** `DocumentPage`,
`DocumentElement`, `PageKind`, `ProcessingMethod` and `ElementType` were written in Phase 1;
`PdfParserPort` and `OcrPort` are declared; `save_pages`, `get_pages`, `save_elements` and
`get_elements` are implemented against `document_pages` and `document_elements` from Phase 2.
Phase 5 was adapters and wiring — no new entities, no migration.

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

**Status: ~60% — steps 6.1, 6.2, 6.3 and 6.4 done.** Tables are now first-class records and, as of 6.2,
retrievable ones. A detected region is read into named columns, per-column units, aligned rows
and the caption the document gave it, then rendered to JSON, Markdown, HTML and the prose that
gets embedded — and the table's chunk now holds that prose rather than its joined cells, so a
question about a named column can match. `Conversation.active_table_id` and `active_figure_id`
are still never set, because selection needs the API surface Phase 19 provides.

**The "blocked on Phase 5" note this section used to carry was stale.** The parser has emitted
`TABLE` and `FIGURE` elements since step 5.3, and left the seam open on purpose — tables carried
joined cell text because "headers, units and row grouping are a later concern", and figures were
recorded empty because "a figure has nothing to say until something looks at it" (A-661).

**The phase splits along a line worth naming.** Every table requirement is deterministic parsing
and needs no model, no recognition and no object store. Every visual requirement needs at least
one of the three: OCR for labels, which is Phase 5's deferred second pass, and a multimodal call
for the description, which nothing has yet exercised for real. Tables therefore come first —
not as a preference, but because it is the only order in which the work can be verified rather
than mocked (A-662).

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 6.1 | Table structure — headers, units, aligned rows, caption association | M | ✅ |
| 6.2 | Table serialisation — JSON, Markdown, optional HTML, retrieval-oriented prose | M | ✅ |
| 6.3 | Large tables split by row group, repeating headers and units | M | ✅ |
| 6.4 | Figure and table number extraction | S | ✅ |
| 6.5 | Crops to the object store | S | ✅ |
| 6.6 | Visual records: chart and diagram schema | M | ✅ |
| 6.7 | Factual descriptions — **needs OCR and a multimodal model** | L | ☐ |

### 6.1 — Table structure ✅

- [x] `DocumentTable` entity, refusing a row that does not line up with its headers — a short
      row silently shifts every value after the gap into the wrong column, and a table that
      answers confidently with the wrong figure is worse than one that admits it could not read
- [x] `resolve_table_structure` reads a raw grid into headers, units and rows. Three cases, and
      only the middle is certain: a first row holding numbers is data and the columns are named
      by position, words above numbers is a header on the evidence, words above words is a
      header by convention. Both uncertain outcomes are flagged rather than hidden (A-666)
- [x] Units read from a parenthesised or bracketed suffix on the column name, or from a
      dedicated units row where one is followed by measurements; the dedicated row wins
- [x] Caption association searches above and below, nearest wins, bounded by three times the
      caption's own height. A table-specific label pattern stops a figure's caption being
      claimed by a table beside it — exercised directly by the structured fixture (A-668)
- [x] `document_tables` table and migration `0012`, with its own `FOR ALL` policy in both
      directions. Not covered by the enumeration test, which is pinned to migration 0008 and
      cannot see a table added later (A-671)
- [x] `ParsedPage` replaced the bare tuple the parser and the ingestion command each declared
      separately, and now carries tables alongside elements (A-663)
- [x] `save_tables` and `get_tables` on the document repository; ingestion persists tables after
      elements, since each names the element it was read from
- [x] 68 tests: grid reading against wrapped, ragged, headerless and unit-bearing input; entity
      invariants; migration and model; and extraction from a real fixture PDF end to end

### 6.2 — Table serialisation ✅

- [x] Four forms, for four readers: JSON to rebuild the grid from, Markdown to put in front of a
      model, HTML for a viewer, and prose to embed. All pure functions of the table — nothing
      reads a clock, a file or a model, so a given grid renders the same way every time
- [x] **The prose form names a column on every row it appears in.** That repetition buys two
      things: a search for "accuracy on run 2" matches a line holding both the word and the
      number rather than bare figures whose meaning sits in a header several lines above, and
      every line stands alone once a table too large to keep whole is cut between lines
- [x] **This closes a real defect.** An oversized table was already being split on line
      boundaries — the split that does not cut a row in half — but every piece after the first
      then carried rows with no column names anywhere in it, which is precisely what a row must
      never be embedded without. The format discharges the rule rather than the splitter (A-675)
- [x] Stored on the row rather than derived on read: the prose form is what a vector is built
      from, and re-rendering later with a changed renderer would leave stored embeddings
      describing text that exists nowhere (A-676)
- [x] Every value escaped in the HTML form, since a cell reading `<script>` is content that
      happens to look like markup. Pipes escaped in Markdown for a different reason — an
      unescaped one ends its cell early and shifts every later value a column left
- [x] `with_renderings` as a named transition; migration `0013` adds the four columns, all
      nullable, because a table exists as a grid before it is rendered
- [x] Ingestion renders before saving and hands the chunker a copy whose table elements carry
      the prose. The stored element keeps the literal reading — the two records are wanted for
      different things (A-678)
- [x] 44 tests: every form against wrapped, empty, ragged, unit-bearing and hostile input, plus
      the ingestion path end to end

### 6.3 — Large-table row-group splitting ✅

- [x] When a table's prose is too large to keep as one chunk, the chunker now repeats the
      anchor line (caption or, when there is none, the first data row) at the start of every
      group after the first. A split piece then carries enough context to identify which table
      it came from and what each column holds, without needing to fetch its neighbour
- [x] **The prose form already made each row self-describing** — step 6.2's decision that every
      row names its own columns is what made the "headerless rows" half of this requirement
      already met. What remained was attaching the table's identity to each group, which is
      the anchor line (A-696)
- [x] Only TABLE chunks get anchor repetition. Formulas, diagrams, charts and figures split
      on line boundaries without it — nothing in those types has the semantic concept of
      "this piece belongs to a named numbered object" the way a table row does (A-697)
- [x] `_split_table_rows()` added to `Chunker`. `_standalone_drafts()` dispatches to it for
      TABLE chunks and to the existing `_split_lines()` for every other standalone type
- [x] The first split piece is unchanged from the current behaviour — the anchor is already
      its first line because it came first in the original text. No duplicate is introduced
      in piece 1; only pieces 2 onwards are modified
- [x] 5 tests: table that fits unchanged; caption repeated in every group; first row as anchor
      when there is no caption; split pieces keep TABLE chunk type; other standalone types do
      not repeat their anchor. All 56 chunker tests pass

### 6.4 — Figure and table number extraction ✅

- [x] One module now states what a caption label looks like, and both things that were already
      matching them ask it — the element classifier deciding a line is a caption, and table
      extraction deciding a caption belongs to a table rather than a figure beside it. This step
      would otherwise have added a third copy of the same rule (A-684)
- [x] Kind and number captured, not just detected: `Table 4.2`, `Fig. 3`, `Chart 2b`, `Table A.1`,
      `Table 12.3.1`, `Table 4-2`. Plate and exhibit read as a figure and scheme as a diagram,
      because a reader means the same thing by them
- [x] **The number is stored as the document wrote it.** None of `4.2`, `A.1` or `2b` is a number,
      and `4.2` and `4-2` are different on the page — a student types what they see, so what was
      printed is what should match (A-685)
- [x] Extracted from the caption rather than removed from it, so a caption still reads the way the
      document wrote it while the number is separately addressable
- [x] Migration `0014` adds the column and an index on scope plus number, since looking a table up
      by number is always a scoped lookup
- [x] Negative cases carry their weight: "Table of contents", "Figure it out", "Section 4.2" and
      a sentence merely mentioning a table are all refused
- [x] 41 tests, including extraction from the real fixture PDF

**This retires the input side of Phase 11's table-number matching validator**, which was
impossible while the number lived only inside a caption sentence. The validator itself is Phase 11
work and is not done here (A-690).

### 6.5 — Crops to the object store ✅

- [x] `crop_key: str | None` field on `DocumentFigure` — the R2 key where the cropped image lives.
      Null on records from documents processed before this step, or when the page failed to render.
      Not a URL: URLs are signed on-demand and expire; the key is permanent
- [x] `FigureCropperPort` in `domain/ports/adapters.py` — takes PDF bytes, 1-indexed page number,
      page height in PDF pts, and bounding box; returns PNG bytes for the region
- [x] `FigureCropper` in `infrastructure/rendering/figure_cropper.py` — renders via pypdfium2 at
      `page_render_dpi`, converts bounding box from PDF pts (origin bottom-left) to pixel
      coordinates (origin top-left), crops with PIL, returns PNG. Runs on a thread via
      `asyncio.to_thread`, same approach as `PageRenderer`
- [x] Crop key format: `{crops_prefix}/{user_id}/{kb_id}/{doc_id}/{figure_id}.png` — scoped and
      deterministic so a re-ingestion overwrites rather than accumulating beside the old file
- [x] `crops_prefix: str = "figures"` added to `StorageSettings` — separate from
      `page_render_prefix` because crops are permanent (re-sent to the model on every visual
      question) while renders are cached with a TTL
- [x] `IngestDocumentUseCase` extended: `figure_cropper: FigureCropperPort | None` + `crops_prefix`
      constructor params. After parsing and before `save_figures`, `_crop_and_upload_figures`
      renders each figure's page, crops it, uploads, and returns the figures with `crop_key` set.
      A crop failure is logged and skipped — the figure record is still saved, with null `crop_key`
- [x] Migration `0016` — `ALTER TABLE document_figures ADD COLUMN crop_key TEXT` (nullable)
- [x] `FigureCropper` wired in `wire.py` whenever `STORAGE_ACCOUNT_ID` is configured; null slot in
      `container.py` when not, so dev environments without R2 still work
- [x] `test_container.py` updated: `monkeypatch.delenv("STORAGE_ACCOUNT_ID")` added to the unwired
      test so it stays correct on machines with R2 configured (A-717)
- [x] 5 new tests in `TestFigureCropping`: crop uploaded to storage; saved figure carries crop_key;
      key scoped to user/kb/document; null cropper leaves crop_key null; crop failure leaves figure
      saved with null crop_key and no storage upload. All 42 ingest tests pass; full unit suite
      2,614 passing (5 new)

### 6.6 — Visual records: figure, chart and diagram schema ✅

- [x] `DocumentFigure` domain entity — frozen dataclass with `kind` discriminator (FIGURE, CHART,
      DIAGRAM), bounding box, caption, number, and all chart-specific and diagram-specific fields.
      Fields that require image analysis are present but nullable; they are filled in step 6.7
- [x] One entity for all three visual kinds: they share most fields, and the kind discriminator
      lets downstream code branch where it needs to. Three separate entities would have tripled
      the repository protocol, migration and mapper for minimal gain at this stage (A-698)
- [x] `__post_init__` enforces: kind must be FIGURE/CHART/DIAGRAM; page number positive; timestamp
      timezone-aware; confidence in `[0.0, 1.0]` when present
- [x] `is_described` property — `True` once `description` is set (Phase 6.7)
- [x] `DocumentFigureModel` ORM model — `document_figures` table, `kind` as TEXT (not enum),
      diagram array fields as `ARRAY(Text())`, both FKs cascade (A-701)
- [x] Migration `0015` — creates table, 4 indexes, RLS enabled with `document_figures_user_isolation`
      policy checking both read and write directions. Not yet applied to live Supabase — needs
      hotspot connection (A-702)
- [x] `save_figures` / `get_figures` added to `DocumentRepository` protocol and `SqlDocumentRepository`
- [x] `_caption_for()` in the parser generalised to take `kind` keyword so figure captions are not
      claimed by nearby tables and vice versa (A-700)
- [x] `_build_figure()` in the parser — mirrors `_build_table()`; every detected image produces a
      `DocumentFigure` with FIGURE kind; CHART/DIAGRAM reclassification waits for step 6.7 (A-699)
- [x] `ParsedPage` gains a `figures` field; early-return paths for scanned/complex pages set it
      to `[]`
- [x] `IngestDocumentUseCase` persists figures after elements, same pattern as tables
- [x] 59 new tests across entity, migration, ORM model, parser and ingest use case

- [x] Tables: detect → title and caption → headers, rows, units → crop → JSON → Markdown →
      optional HTML → retrieval-oriented text → bbox, page, confidence — **all but the crop**,
      which needs the object store and waits for 6.5
- [x] Large tables split by row group, **repeating the anchor line (caption or first row) in every
      group**; rows never embedded headerless — the headerless half is met by the prose
      format (step 6.2) and the anchor repetition (step 6.3) covers the identity context
- [x] Schema for figure, chart and diagram visual records — entity, ORM model, migration, parser
      wiring and ingestion — **fields filled in step 6.7**
- [ ] Visual objects: crop → caption → surrounding paragraphs → OCR labels → factual description →
      page and bbox → links to related chunks
- [ ] Chart records: `chart_type`, `x_axis_label`, `y_axis_label`, `units`, `legend`,
      `data_labels`, `visible_trend` — schema exists, values wait on step 6.7
- [ ] Diagram records: labels, components, arrows, visible relationships — schema exists, values
      wait on step 6.7
- [ ] Descriptions flagged **derived, not authoritative** at schema level (§18) — `is_described`
      property exists; `description` itself is filled in step 6.7
- [x] Figure and table number extraction ("Figure 4.2") — **done for tables in 6.4 and figures
      in 6.6** via the same `parse_caption_label()` function
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
through every stage — has never been run. Step 7.5 installed the `ml` group and closed A-358, so
the embedder and reranker are real adapters now; what still blocks 7.6 and 7.7 is not code but
inputs, namely R2 credentials and a running Ollama. **No real model call has yet happened in
this repository**, which is the single largest unverified claim in the plan: every gateway test
uses a fake, so the adapters are correct against a contract rather than against a server.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 7.1 | Real token counting behind a port | M | ✅ |
| 7.2 | Structure-aware child chunks, built from elements | L | ✅ |
| 7.3 | Parent chunks from sections, with `parent_chunk_id` linkage | M | ✅ |
| 7.4 | Parse and chunk a real textbook offline, and report what it did | M | ✅ |
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

### 7.4 — Parse and chunk a real textbook offline ✅

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
- [x] Read the output against "Data Science in the Cloud with Microsoft Azure Machine Learning
      and Python" (O'Reilly, 62 pages) — headings match real section titles, reading order
      correct, no column misreads (A-708, A-709)
- [x] Assessment written — feeds directly into 7.8 action list (A-710 through A-713)

**Assessment — "Data Science in the Cloud" (O'Reilly, 62 pp)**

*Pages.* 45% NATIVE_TEXT, 44% MIXED, 11% SCANNED. The 54.8% of pages that defeat the text
layer is correct: the book is screenshot- and diagram-heavy, and pdfplumber cannot read Azure
ML studio screenshots. `complex_vector_drawing_threshold = 400` is calibrated correctly —
raising it would misclassify pages that genuinely need OCR. The OCR finding answers the 7.8
question: 55% of pages are unreadable without it, so phases 5.7–5.9 are worth building.

*Headings.* The 75 HEADING elements (27%) match real O'Reilly section titles: "Introduction",
"Downloads", "Working Between Azure ML and Spyder", "Overview of Azure ML", "A Regression
Example", etc. The 27% rate is appropriate for this recipe-style book (~1.4 labelled sections
per page). `heading_size_ratio = 1.15` is correctly calibrated. The inspect_parse.py display
truncates paths to 60 chars, making every path look like only the book title; the actual
hierarchy is Book title → Chapter → Section (confirmed with full-path logging, A-706).

*Chunks.* Content-section chunks are 100–400 tokens; the 89.5% single-child rate and 173-token
median are biased by front-matter chunks and reflect O'Reilly's many short how-to sections, not
a chunker bug. Zero content elements are absent from chunks. No children breach the 700-token
ceiling.

*Running headers.* The position+normalization suppressor (7.8a) correctly prevents heading-size
running headers from corrupting the heading stack. Body-size running headers (e.g., "2 | Data
Science in the Cloud…" at 9 pt on p8, same size as body text) are classified as PARAGRAPH and
bypass the suppressor, appearing as the first line of the following chunk. This is a coverage
gap in the suppressor, not a calibration problem.

**Numbers that do not need to change:** `heading_size_ratio`, `complex_vector_drawing_threshold`,
`paragraph_gap_multiplier`, chunking targets.

**What 7.8 must do:** drop running header elements from output rather than reclassifying them,
and extend the suppressor to cover body-size repeating text in the top margin (A-710, A-711).

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
- [x] **Migration `0011` applied — head is `0011 (head)`.** It had been written and waiting on a
      connection since step 8.4; it creates `model_invocations` and two indexes and drops
      nothing (A-656)
- [x] **The integration suite runs against the live database: 18 passed, 1 skipped.** That closes
      the item below, unrun since it was written. The skip is the destructive round-trip, still
      gated and deliberately not enabled (A-657)
- [x] First opportunity to run the integration suite, unrun since it was written (A-283)
- [ ] **Blocked on credentials:** `STORAGE_ACCOUNT_ID`, `STORAGE_ACCESS_KEY_ID` and
      `STORAGE_SECRET_ACCESS_KEY` are present in `.env` but empty. The adapter is built and
      unit-tested, so this is a credentials task rather than an implementation one (A-659)
- [ ] **Blocked on a document:** no real textbook exists in the repository. The eight fixtures
      under `tests/fixtures/pdfs/` are synthetic and were built to exercise specific parser
      branches, so they cannot answer what D-22 needs them to
- [ ] Upload → job enqueued → worker claims it → pages, elements, chunks and embeddings persisted
      → document reaches `COMPLETED`
- [ ] Expect to iterate, and re-ingestion still duplicates rather than replaces (A-312) — delete
      and re-upload between attempts, which the deletion path built in 4.11 supports

### 7.7 — Query the ingested textbook end to end

- [ ] **Blocked on Ollama**, which is not installed — nothing is listening on `127.0.0.1:11434`.
      All four model keys resolve to `gemma3:4b`, so a single pull serves generation, query
      rewriting, faithfulness checking and vision. **No real model call has ever happened in
      this repository** (A-660)
- [ ] Ask real questions of the real document: dense and keyword retrieval, fusion, reranking,
      evidence assembly, a streamed answer with citations that open at the right page
- [ ] The first observation of retrieval quality on anything other than fixtures

### 7.8 — Recalibrate the tuning numbers from what was found

- [x] **Settled `complex_vector_drawing_threshold = 400`** — 54.8% of real-book pages are
      MIXED/SCANNED, confirming the threshold is not over-triggering. No change needed (A-712)
- [x] **OCR decision made on evidence** — 55% of pages in the real textbook defeat the text
      layer. Phases 5.7–5.9 (OCR pipeline) are worth building (A-713)
- [x] **No configuration numbers need to change** — `heading_size_ratio = 1.15`,
      `paragraph_gap_multiplier`, and all chunking targets are correctly calibrated for
      real-book output; the 7.4 assessment confirmed this
- [x] **Drop running headers from chunk text** — `_elements_for` now skips element creation
      entirely for identified running headers (via `continue`) rather than reclassifying
      to PARAGRAPH; the reading_order gap from skipped drafts is harmless (A-714)
- [x] **Extend suppressor to body-size running headers** — `_detect_running_headers` now
      tracks PARAGRAPH drafts in the top margin alongside HEADINGs; `_elements_for` applies
      the same position+membership check for both types (A-715)
- [ ] **Known gap:** pdfplumber-merged running headers — when the vertical gap between a
      running header and the first paragraph is below the grouping threshold, they emit as
      one text block; the suppressor cannot match the combined text to a known running
      header string. Requires sub-line word-object inspection or lowering
      `paragraph_gap_multiplier` — deferred (A-716)

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

**Status: complete — 8 of 8 steps.** There is a real gateway in front of the adapters now. A
façade holds an ordered provider list and routes each of the ten tasks to the first provider whose
profile declares it, refuses a private request bound for a third party before the call is made,
falls through to the next capable provider when one fails retryably, and renders the prompt
through a per-adapter profile so two providers wanting different message shapes do not each get
their own copy of the twelve-slot logic. Every completed call leaves a `model_invocations` row.

The step this phase existed to prevent is now structurally impossible: with one local provider
none of the routing, privacy or fallback logic was ever exercised, so the single-provider setup
was hiding the absence of all of it. A second adapter — OpenAI-compatible, covering vLLM and
llama.cpp servers — is what makes the machinery load-bearing rather than decorative.

Two items stay open, and both are deliberate rather than unfinished. Neither blocks a later phase.

| Step | Deliverable | Done |
|---|---|---|
| 8.1 | Gateway façade + task router | ✅ |
| 8.2 | Privacy pre-flight (§52) | ✅ |
| 8.3 | Fallback chain (§53) | ✅ |
| 8.4 | `model_invocations` table (§48) | ✅ |
| 8.5 | Warm-up on startup (§55) | ✅ |
| 8.6 | OpenAI-compatible adapter; Gemini and Anthropic stubs (D-17) | ✅ |
| 8.7 | Prompt normalisation profiles (§54) | ✅ |
| 8.8 | Data boundary security gate | ✅ |

- [x] **Gateway façade → task router → provider adapter** — `ModelGatewayFacade` wraps an
      ordered provider list; the first provider whose profile supports the requested task is
      selected; the container now holds the façade, not `OllamaModelGateway` directly
- [~] Four capability interfaces: text generation, multimodal, embeddings, reranking. Embeddings
      and reranking are deliberately **separate ports** (`EmbeddingPort`, `RerankerPort`) rather
      than gateway capabilities — they are called from retrieval, not from generation, and routing
      them through a provider façade would put a task router in front of two adapters that have
      exactly one implementation each. `TextGenerationCapability` and `MultimodalCapability` do
      form a proper hierarchy, multimodal extending text (A-588)
- [x] §49 capability metadata including `data_boundary` — `ModelProfile` carries it
- [x] §50 routing for all ten model tasks — `ModelGatewayFacade._provider_for` selects the first
      capable provider by task, raising `UnsupportedCapabilityError` when none qualifies
- [x] Ollama adapter implemented
- [x] OpenAI-compatible adapter; Gemini and Anthropic raising `NotImplementedError` (D-17)
- [~] Internal model keys resolvable at deployment, task or Knowledge Base level (§51) — only the
      deployment level resolves: one model id comes from settings and is passed to the adapter's
      constructor. Per-task and per-Knowledge-Base overrides need a Knowledge Base setting to
      read, which is Phase 14's surface, and a routing table the façade does not yet consult
- [x] **Privacy policy (§52):** `ModelRequest.privacy_sensitive` derived property; façade raises
      `DataBoundaryViolationError` before calling a THIRD_PARTY provider for a private request;
      check applied in `generate`, `generate_stream`, and `generate_with_image`; no silent reroute
- [x] **Fallback (§53):** on `ProviderError(retryable=True)` the façade tries the next capable
      provider in the list; `retryable=False` propagates immediately; privacy violation is always
      fatal even during fallback; last error re-raised when all candidates exhaust; fallback event
      logged via structlog `gateway.provider_fallback`
- [x] **Prompt normalization (§54)** and per-model prompt profiles — `PromptProfile` dataclass
      in `providers/prompt.py`; `build_chat_messages` accepts a profile; `use_acknowledged_exchange`
      flag controls memory/evidence user→assistant wrapping; Ollama and OpenAI-compat adapters
      each carry a profile and pass it to `build_chat_messages`
- [x] Warm-up at startup for every configured model (§55) — `warm_models_on_startup` triggers a
      one-token `ANSWER_GENERATION` call at lifespan startup; failure is logged and non-fatal
- [x] `model_invocations` written on every call — migration 0011 creates the table;
      `write_model_invocation()` emits a structlog event and adds a row per completed call;
      streaming excluded (no single end-to-end latency); write failures are non-fatal
- [x] Security test: external-provider privacy violation blocked

## Phase 9 — Conversations, query understanding & retrieval core

Covers §23 through reranking, §24, §25, §26, §27, §28, §29, §41.

**Status: ~98% — closed out on 22 August 2026.** Built out of order, ahead of phases 5–8. The
retrieval pipeline is complete and the persistence layer was finished in steps 9.11–9.15, which
also closed a defect where the conversations router never committed — every write on this path
was being discarded, and no unit test could see it because they all assert against a mocked
repository.

All fifteen steps are done, and the three field-level gaps that had been carried below them are
now closed too: the rewritten query is persisted on the user message, a `PROCESSING` placeholder
is committed before streaming, and the model-metadata item turned out to have been fixed already
and never marked. **One item remains, `rolling_summary`, and it is deferred by decision** — the
column exists and nothing reads it until Phase 14, so writing it now would mean writing a
producer with no consumer.

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
- [x] `PROCESSING` status — before streaming begins, a placeholder assistant message with
      `PROCESSING` status is committed; `_record_turn` merges the final state over it by
      primary key. A server crash during generation leaves the row as `PROCESSING` rather
      than absent, preventing the incomplete turn from being replayed as a completed one
- [ ] **`rolling_summary`** — column exists, absent from the `Conversation` entity, never written.
      Deferrable: nothing reads it until Phase 14
- [x] Query rewriting — follow-ups resolved to standalone queries before search
- [x] **Both forms stored (§24)** — `RetrievalResult` now surfaces `standalone_query` and
      `was_rewritten`; when the rewriter changed the query, `answer.py` opens a second
      unit of work and saves `user_message.with_rewritten_query(...)` before streaming begins
- [x] **Model metadata on assistant messages** — `OllamaTokenStream` and
      `OpenAICompatTokenStream` both implement `.usage` (a `GenerationUsage` set once the
      stream is fully drained); `_collect_stream` reads it via `getattr`; `_record_turn` passes
      all four fields to `Message`; `_msg_to_model` maps them to `MessageModel`. The open item's
      description was stale — the pipeline was already complete and verified on 18 August 2026
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
- [x] **Verified against the live database on 18 August 2026.** The whole integration suite ran
      for the first time since it was written: 14 passed, 1 skipped, the skip being the
      destructive migration round-trip which stays behind its own flag. Durability on the
      streamed write path is now demonstrated rather than argued, and the schema matches the
      models against a real PostgreSQL 17.6 rather than SQLite

## Phase 10 — Evidence selection & context assembly

Covers §30, §31, §32, §33, §36, §37.

**Status: ~98% — every step done.** Evidence is sized, deduplicated, expanded and
compressed, then assembled into a twelve-slot prompt that sheds low-priority context before
it ever touches the essentials, with every passage carrying the label the model must cite it
by and every requirement carrying the name it will be scored against. What is left is not a
step but a dependency: duplicate visual descriptions and graph evidence go through the same
comparison and the same compression as everything else, and nothing produces either until
phases 6 and 12, so both are covered by argument rather than by a test with the real thing
in it.

Retrieval used to end at reranking and hand the surviving chunks to the model as raw text.
Everything between those two points was this phase: how many passages to send, which of
them are saying the same thing twice, when a fragment needs the section it came from, what
to cut when it will not fit, in what order the whole prompt is assembled, and what to give
up when it still will not fit. The pieces built ahead of it are read now — parent chunks
had been written on every ingestion since step 7.3 with nothing loading them, and
`Chunk.with_compressed_text` had never been called.

| Step | Deliverable | Size | Done |
|---|---|---|---|
| 10.1 | Dynamic evidence selection, sized by query class | M | ✅ |
| 10.2 | Deduplication and diversity caps | M | ✅ |
| 10.3 | Parent expansion, on the five conditions only | L | ✅ |
| 10.4 | Extractive compression | L | ✅ |
| 10.5 | Context builder — twelve slots and the token budget | L | ✅ |
| 10.6 | Structured instruction handling | M | ✅ |

### 10.1 — Dynamic evidence selection ✅

- [x] `EvidenceSelector` in the domain decides how many passages survive. `top_k` is gone
      from both `RetrieveEvidenceQuery` and `AnswerCommand` — the caller no longer says
      (FR-EVD-01)
- [x] Counts follow the query class, every class mapped, clamped by the configured global
      bounds of one and eight (FR-EVD-02, FR-EVD-04)
- [~] The decision weighs reranker score, relative margin, token budget and count.
      Diversity and source coverage are step 10.2's caps; modality needs Phase 6 (FR-EVD-03)
- [x] The margin and the global bounds stay in configuration. The per-class ranges are a
      domain table rather than twenty-six environment variables, injectable so any one of
      them can be lifted out when there is an evaluation set to calibrate it against
      (FR-EVD-05, D-20, A-407)
- [x] Tests: a direct question does not receive five passages; a comparison does not receive
      one; a weak second is kept for a comparison and dropped for a direct question; the
      budget overrides the class minimum and one passage overrides the budget
- [x] A new `select` stage is timed and logged alongside the other seven

### 10.2 — Deduplication and diversity caps ✅

- [x] `EvidencePruner` in the domain, running between reranking and selection. Removes the
      same chunk retrieved twice, identical text under different ids, a matching content
      hash, a passage contained within a longer one, a child and the parent it came from,
      and tables sharing their rows (FR-EVD-06)
- [~] Duplicate visual descriptions and repeated graph evidence go through the same
      comparison, but nothing produces either until phases 6 and 12, so both are covered by
      argument rather than by a test with the real thing in it (A-417)
- [x] Caps: two children per parent, three chunks per page, a configured maximum per
      document, all from configuration. For comparisons the document allowance is halved, so
      one book cannot supply the whole answer to a question about two (FR-EVD-07, A-414)
- [x] The highest-ranked passage is admitted outright, before any rule is consulted — a
      guarantee that is now the shape of the loop rather than a condition that never fired
      (FR-EVD-08, A-415)
- [x] Order is never changed. Promoting a passage here would overrule the reranker, which is
      the one stage that looked at the query and the passage together
- [x] Tests: 22, covering each kind of repetition, each cap, and the survival of the top
      result under caps that would otherwise remove it

### 10.3 — Parent expansion ✅

- [x] `ExpansionRules` in the domain names all five ways a fragment can be incomplete in
      itself: it opens mid-sentence or on a continuation word, it opens by pointing at
      something it does not contain, it is a table without its caption, a formula without
      its definitions, or a visual whose explanation is the prose beside it (FR-EVD-09)
- [x] Never by default. The rules decline wherever they would have to guess, because a
      missed expansion leaves the passage as retrieval found it while a wrong one replaces
      a precise passage with a section several times its size (FR-EVD-10, A-423)
- [x] `get_many` added to `ChunkRepository` and the SQL implementation — one scoped query
      for the whole evidence list rather than one per fragment (A-425)
- [x] Runs before selection, since expansion changes what each passage costs and the budget
      is spent in the step after (A-419)
- [x] Two fragments from one section yield one expansion, not two copies of it (A-421); a
      parent that cannot be loaded leaves its fragment alone (A-422)
- [x] The tier step 7.3 wrote is now read. Parent chunks stop being storage nobody queries
- [x] Tests: 26 on the rules, 7 on the loading, 4 on the batch query, and a new
      `expand_parents` stage timed alongside the rest

### 10.4 — Extractive compression ✅

- [x] `EvidenceCompressor` selects whole sentences from the original, so what is sent is
      word for word in the document and can therefore be cited (FR-EVD-11).
      `Chunk.with_compressed_text` has its first caller
- [x] Sentences carrying a negation, a number or a condition are kept whatever they score,
      and past the budget if it comes to that. Units need no rule: they sit in the sentence
      with their number (FR-EVD-12, A-426, A-427)
- [x] Tables are cut by row, never by sentence, and keep their title and headings
      unconditionally (FR-EVD-13). Formulas and captions are indivisible and go whole
- [~] Graph evidence would be cut as prose. Nothing produces any until Phase 12, so the
      rule is unwritten rather than untested (FR-EVD-14, A-433)
- [x] Generative compression raises at construction rather than switching on, which records
      the decision where it will be read instead of leaving an unexercised path that
      rewrites evidence when flipped (FR-EVD-15, A-428)
- [x] Property tests across six claims and four budgets: no number and no negation present
      in the source is ever absent from the result
- [x] The sentence splitter is now shared with the chunker, so the two cannot diverge into
      cutting inside what the other treats as indivisible (A-430)

### 10.5 — Context builder ✅

- [x] `ModelRequest` grew from seven slots to the twelve FR-CTX-01 specifies: system and
      security policies, task objective, mandatory requirements, active Knowledge Base
      state, pinned durable memory, relevant historical memory, rolling conversation
      summary, recent raw turns, source evidence, current question, required output
      schema, final critical checklist. Seven callers already built the old shape, so
      extending it in place is what let every one of them move in this step rather than
      two structures drifting apart (FR-CTX-01, A-434)
- [x] `ContextBuilder` owns token allocation. Five slots — identity, safety rules, the
      task, the evidence, the question — are never shed; the rest are cleared to their
      empty value, one at a time, in a fixed order, stopping the moment the prompt fits
      (FR-CTX-02, A-436, A-437)
- [x] `ModelSettings.prompt_token_budget` (8000) must exceed
      `EvidenceSettings.context_token_budget` (6000), enforced by a cross-settings
      validator — otherwise the passages alone could fill the whole prompt (A-441)
- [x] Evidence is rendered **with its label**. `LabeledPassage` carries a plain string
      label rather than the retrieval package's `EvidenceLabel`, so a provider-neutral
      request does not import from the package that produced it. The model can now say
      which passage it is citing, which it could not before this step (FR-CTX-01, A-435)
- [x] The Ollama adapter's rendered order now matches the twelve slots exactly — recent
      turns before evidence, evidence before the question — which moved evidence and
      memory relative to where they sat before (A-440)
- [x] Tests: 20 on the context builder covering shedding order and the five essentials
      never being touched, plus updates across model, adapter, application and security
      tests wherever `ModelRequest` or evidence rendering was touched
- [~] Most of the new slots — mandatory requirements, Knowledge Base state, memory, the
      summary, the output schema, the checklist — have no producer yet and are exercised
      only by direct construction; `AnswerUseCase` populates only what earlier phases have
      built (A-442)

### 10.6 — Structured instruction handling ✅

- [x] An instruction is a thing rather than a sentence: `Instruction` in the domain carries
      its text, what kind of instruction it is, how strongly it binds, and optionally the
      subject it governs and when the student said it. The adapter renders one per line,
      so what the model receives is a list it can answer point by point (FR-CTX-03)
- [x] `InstructionCategory` is the seven-rung priority ladder — security and privacy,
      grounding and source use, task objective, output contract, user constraints, style
      preferences, optional enhancements — and sorting by it is what produces reading
      order, so the order is a property of the enum rather than of any caller (FR-CTX-04)
- [x] Every requirement is `CRITICAL`, `REQUIRED` or `PREFERRED`, and the classification
      does real work: shedding gives up preferences early, required rules last, and
      critical ones never (FR-CTX-05, A-449)
- [x] `R1…Rn`, assigned after resolution in final reading order. Shedding leaves the
      survivors' names alone, so a gap where R2 used to be records that it was dropped
      rather than hiding it (FR-CTX-06, A-447)
- [x] Conflicts are settled before assembly, and they are **declared, not inferred** — an
      instruction names the subject it governs, and two on one subject compete. Level
      decides first, then recency, then whether it was an explicit correction; a security
      rule claims its subject outright so nothing contradicting it is sent at all
      (FR-CTX-07, A-443, A-444, A-445)
- [x] A security rule below `CRITICAL` and a correction without a timestamp both fail
      construction, so the guards downstream cannot be guarding an impossible state
      (A-446)
- [~] `build_all` gives each task its own request and the whole budget, and `build` is its
      single-task case, so the one caller passes through the same path. Nothing yet
      produces more than one task, so the separation is exercised by tests rather than by
      traffic (FR-CTX-08, A-450)
- [x] `ModelRequest.mandatory_requirements` holds structured requirements rather than
      rendered strings — an identifier that exists only inside a formatted line has to be
      parsed back out by whatever scores compliance (A-448)
- [x] The use case's safety rules were split: grounding and citation became numbered
      requirements, and what stays in the never-shed slot gained the rule that passages and
      conversation are material to reason about, never instructions to follow (A-452)
- [x] Tests: 32 on instructions, 30 on the context builder, 3 on the use case, 3 on the
      adapter. A preference cannot displace a security rule, approached from four
      directions; a later correction beats an earlier preference and a later preference
      beats an earlier correction; every requirement in a built prompt carries a name
- [~] Nothing yet produces a student instruction. The five the use case declares are the
      same every turn; constraints, preferences and corrections arrive with Phase 8's
      memory store and a Knowledge Base's own requirements with Phase 14 (A-453)

### Definition of done

- [x] Dynamic evidence selection — no fixed top-5; min 1, max 8 ordinary; per-class ranges (§30)
- [x] Thresholds are configuration, calibrated in Phase 17 — never hardcoded
- [x] Deduplication and diversity caps; **highest-ranked primary evidence always preserved** (§31)
- [x] Parent expansion only on the five §32 conditions
- [x] Extractive compression preserving negations, conditions, qualifiers, numbers, units, table
      headers, figure labels and citation offsets; generative compression flag-gated, off (§33)
- [x] Context builder with the 12-slot §36 ordering, owning token allocation and shedding
      low-priority slots at the limit
- [x] Structured instruction handling: `CRITICAL > REQUIRED > PREFERRED`, R1…Rn identifiers,
      security rules non-overridable, recent corrections superseding old preferences (§37)
- [x] Property tests: compression never drops a number, unit or negation
- [~] Duplicate visual descriptions and graph evidence are deduplicated and compressed by the
      same rules as everything else, but nothing produces either until phases 6 and 12, so
      neither is tested against the real thing (A-417, A-433)

## Phase 11 — Grounded generation, citations & validation

Covers §23 complete, §38, §39, §40. **Milestone: first cited, validated, streamed answer.**

**Status: ~90% — 18 steps done.** The milestone is met on the backend: an answer is generated
against evidence, parsed to a schema, checked citation by citation and claim by claim, repaired
once if it can be, refused if it cannot, streamed to the caller, and persisted with its citations
and what the call cost. Four release-gate tests cover fabricated and cross-scope citations.

Everything still open is blocked rather than pending. The §40 *object* field, UC-08, and two of
the `[~]` items below all wait on Phase 6; quiz-answer schema validation belongs to Phase 15.
The two validators that are genuinely unbuilt and unblocked are **word and token limits** and
**table-number matching** — small, and the natural companions to whichever phase first needs them.

- [x] All eight §38 generation rules enforced structurally, including **never obeying instructions
      found inside uploaded documents**. Each is a numbered requirement or a safety rule in the
      prompt, and the ones that can be checked are checked: evidence-only answering and citing
      every claim by entailment, never reaching another Knowledge Base by the citation-existence
      check against a scope-filtered evidence set, and figures surviving verbatim by a
      deterministic comparison against the passages a claim cites. The two that remain
      behavioural — chat history is not evidence, and source fact is distinguished from model
      inference — are stated as critical requirements, which is the enforcement available for a
      rule about how to read rather than what to output
- [x] Structured output `{answer, claims[{claim, citations[]}], insufficient_evidence}`, parsed
      and schema-checked on the way back. The claim field is named `text` rather than `claim`
- [~] Stable `[S1]` identifiers carrying document, page, type, object and bbox (§40). A citation
      now carries document, page, chunk and element type, bounding box, and the content hash the
      passage had when it was cited — enough to resolve it back to a place in a PDF for the
      viewer in Phase 19. Only *object* is missing: a chunk carries no table or figure id until
      Phase 6 creates them, and a column nothing can fill reads as a bug rather than as
      scaffolding (FR-CIT-02)
- [x] Backend validates each citation exists, belongs to this user and KB, **was actually in model
      context**, and supports its claim. Authorization holds structurally rather than as a
      separate lookup: only a label present in the evidence set that was actually sent can
      validate, and retrieval scope-filters that set, so a cross-Knowledge-Base label is
      indistinguishable from an invented one
- [~] Deterministic validators: schema, citation existence, authorization, required fields, limits,
      table numbers, units, quiz schema, KB scope (§39). Schema, citation existence,
      authorization, required fields, Knowledge Base scope and unit matching are done — the last
      of these comparing every figure in a claim against the passages it cites, by value rather
      than by spelling. Word and token limits and table-number matching are not; quiz answer
      schema belongs to Phase 15 and cannot be built here
- [x] Semantic validators: claim entailment `ENTAILED`/`CONTRADICTED`/`NOT_SUPPORTED`, unsupported
      claims, contradictions, citation entailment and completeness, faithfulness (§39).
      Entailment runs per cited passage, and unsupported claims, contradictions and citation
      completeness all fall out of it. Faithfulness closes the last gap: the prose the student
      reads is checked against the claims already verified, because an answer whose claims are
      each impeccable can still assert something none of them established
- [x] Decisions `VALID`/`REPAIRABLE`/`INSUFFICIENT_EVIDENCE`/`REJECTED`; **exactly one** repair
      attempt, no loops
- [x] SSE streaming with cancellation on disconnect. A turn the student walks away from is
      recorded as `CANCELLED` rather than as a completed answer nobody received — `CancelledError`
      and `GeneratorExit` are both `BaseException`, so both once slipped past the failure handler.
      The endpoint closes the answer stream deterministically, since the turn is only recorded in
      that stream's cleanup
- [x] Persist answer, `message_citations`, model metadata, `prompt_version`. All four land, and
      all four are verified against the live database rather than against SQLite — including the
      `message_citations` row-level security policy, which SQLite cannot express at all. Model
      metadata comes from the streaming path, which reports what the call cost once it ends;
      `prompt_version` is a fingerprint of the prompt template, so it cannot go stale
- [x] Security tests: prompt injection inside a PDF, fabricated citation, unauthorized citation
- [~] UC-07, UC-08, UC-09. **UC-09** is met on the backend: an abstention is produced when
      nothing is supported, and its alternate flow now holds too — a partially supported
      answer returns the part the evidence carries and names what was left out, rather than
      being withheld whole. **UC-07**'s main flow is built end to end, but two of its steps
      reference things that do not exist yet (relevant memory is Phase 14, the exact-answer
      cache is Phase 16) and its final step is the Phase 19 viewer, so it can only be
      verified as far as the backend goes. **UC-08 cannot be met in this phase at all**: it
      needs a selected table or figure, which Phase 6 has not started creating, and an image
      crop sent to a multimodal model, which the gateway refuses today
      (`generate_with_image` raises `UnsupportedCapabilityError`). Listing it under Phase 11
      was optimistic; it belongs after Phase 6 and the Phase 8 gateway work

## Phase 12 — Graph construction & Selective Graph RAG

Covers §21, §22, §34, §57 API side. Postgres-backed per D-10.

**Status: not started.** `app/infrastructure/graph/` holds nothing but an `__init__.py`, and the
two graph endpoints return 501. What exists belongs to earlier phases and was credited here in
error until 22 August 2026: `GraphEntity` and `GraphRelationship` are Phase 1 entities, the
`graph_entities` and `graph_relationships` tables with their traversal indexes are step 2.6, and
`SqlGraphRepository` is step 2.11. No extraction, no traversal, no fusion of graph results.

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

**Status: not started.** No decomposition, coverage classification or hierarchical synthesis code
exists. The four query classes that trigger this path are already classified correctly by Phase
9's `QueryClassifier`, and `CoverageStatus` is a Phase 1 enum — so the entry points are there and
lead nowhere. Partly blocked: the per-sub-question pipeline calls selective graph retrieval,
which is Phase 12.

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

**Status: not started.** The three memory endpoints return 501. As with Phase 12, what exists is
earlier work: `MemoryFact` with its six statuses and the supersession rule is a Phase 1 entity,
the `memory_facts` table is step 2.5, and `SqlMemoryRepository` is step 2.11. Nothing writes a
fact, nothing compacts, nothing retrieves. Phase 9's `rolling_summary` gap and Phase 10's empty
memory slots both wait here.

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

**Status: not started.** `app/domain/study/` is an empty package and all ten study-content
endpoints return 501. Unlike phases 12 and 14 there is no groundwork at all here — no entity, no
table, no repository.

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
**No `CacheStore` implementation reads or writes `cache_entries`** — the only module in `app/` that
names the table is the ORM model that declares it.

Document deletion is no longer part of this gap: step 4.11 built the `DELETE_DOCUMENT` consumer,
so an individual document's file, cached renders and row are removed. What is still missing here
is deletion's *lifecycle* half — index-version bumping and cache invalidation, which have no
consumer until the answer cache below exists — and Knowledge Base deletion, which currently
relies on cascades and leaves every document's stored object orphaned in R2.

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

**Status: ~20%.** The observability baseline arrived early in step 3.4 and the security suite has
been growing alongside each phase — 121 tests marked `security`, 87 marked `gate`, across eight
files. What is entirely
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
- [~] **All ten §64 security tests** in one suite — eight files exist under `tests/security/`
      covering KB access, RLS through the API, upload, document deletion, retrieval scope, the
      evidence record, the generation pipeline and the data boundary; the rest await the phases
      they test
- [~] **Six release gates as failing tests:** cross-user leakage 0 ✅ · cross-KB leakage 0 ✅ ·
      fabricated citation acceptance 0 ✅ (`test_generation_security.py`, four tests, resting on
      the evidence record) · deleted memory retrieval 0 (Phase 14) · unauthorized cache reuse 0
      (Phase 16) · graph edge without provenance 0 (Phase 12). Three of six are enforced; the
      three that are not each name a phase that has not started
- [ ] Threshold calibration; latency NFRs recalibrated against measured p95 (D-23)
- [ ] `evaluation_results` persisted; results written into `REQUIREMENTS.md`

## Phase 18 — Frontend foundation

Covers §7 authentication, Knowledge Base management and uploads.

**Status: ~10% — the step 0.5 scaffold and nothing since.** `App.tsx`, `main.tsx`,
`AppProviders.tsx`, `queryClient.ts` and `global.css` exist with its design tokens; every
directory under `src/features/` is a bare `.gitkeep`, as are `src/api/`, `src/schemas/`,
`src/pages/`, `src/hooks/`, `src/components/` and `src/state/`. **Nothing in the frontend calls
the backend.** D-01 put the backend first deliberately, so this is on plan rather than behind it.

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

**Status: not started.** Blocked on Phase 18. Two items are additionally blocked on Phase 6:
table and figure region selection has nothing to select, and citation navigation can highlight a
bounding box but cannot name the object it belongs to until §40's *object* field is fillable.

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

**Status: not started.** Blocked on Phase 18 and on every backend phase it renders — 12 for the
graph, 14 for memory, 15 for study content. Cytoscape.js is not installed.

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
