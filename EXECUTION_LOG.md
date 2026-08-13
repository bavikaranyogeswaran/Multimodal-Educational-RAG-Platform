# Execution Log

Assumptions and judgement calls made **while executing** a step — the small decisions taken without
asking, the places where reality differed from the plan, and the things believed but not yet
verified.

## What belongs here, and what does not

| Register | Holds |
|---|---|
| [PLAN.md](PLAN.md) decisions log (`D-xx`) | Decisions **chosen by the user** in answer to a question, before execution |
| [PLAN.md](PLAN.md) findings (`R-xx`) | Risks that affect more than one phase |
| [docs/adr/](docs/adr/) | Architectural decisions with alternatives and a revisit condition |
| **This file** (`A-xxx`) | Everything settled **during** a step — assumptions, small choices, deviations, discoveries, corrections |

The distinction that matters: a `D-xx` was offered as a question and answered. An `A-xxx` was not
worth interrupting for, but is still the reason some piece of code looks the way it does.

## Conventions

- **IDs are permanent.** A superseded entry is marked, never renumbered or deleted.
- **Kind** is one of:
  - `assumption` — believed true, not verified. These carry risk.
  - `choice` — a judgement call where a reasonable alternative existed.
  - `deviation` — differs from the plan, the specification, or a stated intent.
  - `discovery` — learned during execution and changed something.
  - `correction` — something was wrong and was fixed.

---

## Open assumptions

Unverified beliefs currently load-bearing. Each needs confirming at the phase named.

| ID | Assumption | Confirm at |
|---|---|---|
| A-032 | CUDA minor-version compatibility lets a cu126 build run on driver 555.97 (reports CUDA 12.5) | Held so far — GPU matmul and both models ran. Watch for driver-related failures under sustained load. |
| A-034 | PP-OCRv6 on CPU takes roughly 8–15 s per scanned page | Phase 5, first real OCR run |
| A-035 | PaddleOCR-VL on CPU takes roughly 60–120 s per complex page | Phase 5 |
| A-036 | Gemma 3 4B at Q4 plus KV cache occupies ~3.5 GB, leaving room for the retrieval models | Phase 8, when a model is first loaded |
| A-037 | A ~2,500-token prompt prefills in ~700 ms on this GPU | Phase 11, first real generation |
| A-038 | A Supabase round trip costs 40–120 ms from this machine | Phase 2, first real connection |
| A-041 | A 400-page textbook yields ~1,000 child and ~300 parent chunks, ~25–35 MB of database | Phase 7 |
| A-042 | Page renders at 200 DPI average ~250 KB each | Phase 5 |
| A-098 | Extraction confidence below 0.6 is worth surfacing to the student as doubtful | Phase 5, against real OCR output. A placeholder with no data behind it. |

Everything in this table feeds a latency or capacity target in
[REQUIREMENTS.md](REQUIREMENTS.md). If one proves wrong, the target derived from it moves with it.

---

# Phase 0 — Foundation

## Step 0.1 — Repository skeleton

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-001 | deviation | Four directories added beyond the specified tree: `backend/scripts/`, `backend/tests/fixtures/`, `backend/alembic/versions/`, `docs/adr/` | The specification's tree omits them but the plan requires each. Alembic will not run without `versions/`. |
| A-002 | choice | Governing documents at repository root; ADRs under `docs/adr/` | Root placement makes them discoverable without hunting; ADRs are numerous enough to warrant a directory. |
| A-003 | choice | `__init__.py` in every `app/` directory, `.gitkeep` elsewhere | A Python package *is* its `__init__.py`. Using `.gitkeep` there would be replaced in the next step anyway. |
| A-004 | choice | `.gitattributes` added, not in the plan | A cross-platform Python and Node repository on Windows will otherwise accumulate mixed line endings, and the resulting diffs are unreadable. |
| A-005 | choice | `data/`, `storage/`, `uploads/` gitignored | The evaluation PDFs are private study material. An ignore rule is cheaper than discovering a textbook in the history. |
| A-006 | deviation | `main.py` and `pyproject.toml` deferred from 0.1 to 0.2 | Both are in the specified tree, but neither is meaningful before the Python project exists. |

## Step 0.13 — PLAN.md

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-007 | choice | The plan carries a decisions log, a risk register and a coverage matrix, beyond the phase checklists | A checklist records *what*; without the other three, the *why* survives only in conversation. |
| A-008 | choice | Risks numbered `R-xx` and given a "revisit at" phase | A risk with no named revisit point is a note, not a risk. |

## Step 0.8 — Functional requirements

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-009 | deviation | Domain-prefixed IDs (`FR-RET-04`) rather than the flat `FR-001` the plan specified | Flat numbering across 334 requirements makes insertion require renumbering, which breaks every test that cited an old number. |
| A-010 | choice | Requirements written in MUST / SHOULD / MUST NOT form | Descriptive prose cannot be tested. The modal verb is what makes a requirement checkable. |
| A-011 | choice | Prohibitions captured as explicit requirements | The specification states them as prose. A prohibition nobody wrote down is one that fails silently — nothing alerts you when a forbidden thing simply happens. |
| A-012 | choice | Derived requirements trace to a decision ID instead of a specification section | Keeps visible which requirements came from the source document and which from our own decisions. |
| A-013 | choice | 32 domains rather than the plan's nine | Nine groups of forty requirements are not navigable. The finer split makes a domain's whole surface reviewable at once. |

## Step 0.9 — Non-functional requirements

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-014 | choice | Latency budgets derived from a published stage-by-stage cost model rather than asserted | A number with no derivation cannot be argued with, and cannot be corrected when one of its inputs turns out wrong. |
| A-015 | discovery | The cost model showed network round trips to Supabase are the largest non-model cost — roughly 360 ms of the 1.8 s budget | A consequence of hosting that was not obvious when the hosting was chosen. Recorded rather than absorbed. |
| A-016 | choice | Release gates are checked from the phase that introduces each surface, not deferred to Phase 17 | A gate first exercised at the end is a gate that finds problems when they are most expensive. |
| A-017 | choice | Several NFRs written as structural rather than aspirational — an unscoped query must fail *at construction*, RLS presence is asserted by enumerating tables | "Remember to do this" and "cannot be done wrong" are different requirements. Only the second survives a tired afternoon. |
| A-018 | choice | `NFR-PERF-17` added: VL fallback exceeding 20% of pages means the classifier is miscalibrated | The specification says the heavy model must not run everywhere but gives no threshold, so the rule was untestable. |

## Step 0.10 — ARCHITECTURE.md

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-019 | choice | The layers table states what each layer must **not** contain | The prohibition is the part a test can be written against. |
| A-020 | deviation | Six diagrams rather than the two the plan named | Layer dependency, scope enforcement and the model gateway each turn on a relationship that prose describes poorly. |
| A-021 | choice | The scaling path gives a **trigger** for each step, not just an ordering | "Add workers" without "when queue depth is persistently non-zero" is not actionable, and invites adding them on instinct. |
| A-022 | choice | A closing section on what the architecture deliberately is not | Negative constraints erode quietly. A future phase is likelier to reach for a framework if nobody recorded why it is absent. |

## Step 0.11 — Architecture decision records

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-023 | choice | Every ADR ends with a **revisit condition** | A decision with no falsifying condition is a belief that hardens into folklore. |
| A-024 | discovery | ADR-0011 gained **structured-output validity rate** as a benchmark measure, beyond the five the specification lists | Quantization degrades instruction-following and schema fidelity before it degrades fluency. A model can read fine while failing exactly what this system validates. |
| A-025 | discovery | With the graph in PostgreSQL, provenance can be enforced by a `NOT NULL` constraint rather than application discipline | Turns the zero-tolerance gate on provenance-free edges from a code property into a schema property. Strengthens ADR-0012 beyond what motivated it. |
| A-026 | choice | ADR-0014 documents why crops stay permanent while page renders do not | The asymmetry is not obvious: recovering a 60 KB crop needs the original, a re-render and a bounding box, and it is read on every visual question. |

## Step 0.12 — Use cases

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-027 | discovery | `FR-OBJ-08` — exploring relationships through a concept graph — was a stated product objective with **no use case**. Added UC-23 and UC-24 | Found by checking the use cases against the nine primary objectives rather than assuming coverage. |
| A-028 | deviation | All 24 use cases written in full; the plan said early ones in full and later ones stubbed | Stubs would mean later phases define their own acceptance criteria, which inverts the point of writing them in advance. |
| A-029 | choice | Numbering appended rather than inserted when adding UC-23 and UC-24 | Earlier phases already reference UC-01 … UC-22. |
| A-030 | discovery | Writing exception flows forced five behavioural decisions that would otherwise have been made ad hoc mid-implementation | A selected region matching no object falls back to page level **and says which page**; an over-committed study plan **states the shortfall** rather than compressing; a truncated graph neighbourhood **indicates truncation**; one page failing OCR does not fail the document; partial evidence answers what it can and **names** what it cannot. |

## Step 0.2 — Backend project

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-031 | deviation | The `ml` dependency group deferred to 0.3 | Forced, not preferred: `paddlepaddle-gpu` is not resolvable from the public index without a CUDA-version-specific source, and the CUDA version was unknown. Declaring it would have made the lock fail outright. |
| A-039 | choice | All runtime dependencies in dependency groups, none in project dependencies | This is what makes the isolation real — a broken ML install cannot block work on the rest of the backend. |
| A-040 | choice | `pgvector` and `tenacity` added to core, beyond the plan's list | The first supplies the column type the schema needs; the second the bounded-retry primitive the model gateway requires. Both would have been added later anyway, at the cost of a lockfile churn. |
| A-043 | choice | PyJWT over python-jose | Better maintained. python-jose has a history of advisories and is close to unmaintained. |
| A-044 | choice | `httpx2` added to dev | Starlette 1.3 deprecated `httpx` for its test client; without it every test run from Phase 3 onward emits a deprecation warning. |
| A-045 | choice | `main.py` deliberately thin, with liveness and readiness explicitly separated in a comment | Conflating them is a common mistake, and one that makes a health check useless precisely when a dependency is down. |

## Step 0.3 — GPU and ML dependencies

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-033 | choice | torch resolved from the **cu126** index, not cu128 or cu129 | Driver 555.97 reports CUDA 12.5. Minor-version compatibility covers 12.x on a driver ≥ 525; a newer runtime would want a newer driver. |
| A-046 | discovery | 6 GB VRAM is the binding constraint on the whole design — recorded as R-07 | Measured, not assumed. It forced OCR onto CPU, made `Q8_0` quantization probably unselectable, and is the reason keeping all models warm is possible at all. |
| A-047 | discovery | Cross-encoder scores are low and compressed: −10.58 relevant against −11.24 irrelevant — recorded as R-08 | Empirical confirmation that an absolute score threshold would discard every candidate. Directly shaped the configuration schema two steps later. |
| A-048 | deviation | Ingestion latency targets revised upward after moving OCR to CPU; two full-document budgets added | The original targets assumed GPU OCR. Chat targets were left unchanged, since the GPU is no longer contended. |

## Step 0.4 — Code-quality tooling

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-049 | choice | mypy strict on the domain and application layers only | Those depend on nothing external, so there is no third-party typing to fight. Strictness at the adapter edge adds noise without safety. |
| A-050 | choice | Ruff enables ASYNC, S and DTZ beyond a conventional set | Async correctness is load-bearing given the async data layer; security is a first-class concern; naive datetimes in memory validity or job leases are silently wrong, which is the worst kind. |
| A-051 | choice | Three pytest markers registered before anything needs them | Phase 17 must consolidate the security suite and release gates into something selectable. Tagging from the start is far cheaper than retrofitting. |
| A-052 | correction | Source files read as `utf-8-sig`, not `utf-8` | Found by planting a probe file written with a BOM: `ast.parse` died with a confusing `SyntaxError` before reaching the import check. On Windows a BOM is easy to introduce. |
| A-053 | choice | The first tests are the dependency-rule guard and an application boot check, not placeholders | A trivial passing test proves the runner works and nothing else. |

## Step 0.5 — Frontend scaffold

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-054 | choice | Scaffolded by hand rather than with the Vite generator | The generator would have overwritten the directory tree established in 0.1. |
| A-055 | choice | TypeScript stricter than the default template — unchecked index access, exact optional properties, verbatim module syntax | The frontend mirrors the backend contract in Zod; loose typing here defeats having the contract. |
| A-056 | choice | Semantic tokens for abstention and conflict states defined in the stylesheet immediately | Abstentions and source conflicts must be visually distinct from ordinary answers. Establishing the vocabulary now is far cheaper than retrofitting it once the chat interface exists. |
| A-057 | choice | The query client does not retry 401 or 404 | A Knowledge Base the user does not own returns 404 by design, so a retry can never succeed and only adds latency. |
| A-058 | choice | `.claude/launch.json` added, not in the plan | Both processes get a named launch configuration, so later phases do not rediscover the commands. |
| A-059 | correction | The CSS Modules test asserts the class is *scoped*, not that it matches a particular scoping pattern | The first version checked Vite's `[name]__[local]___[hash]` format, which differs between development, test and production builds, so it failed under the test runner. |
| A-060 | correction | Type-aware linting scoped to TypeScript files, with type checking disabled for JavaScript | The first configuration applied typed rules to the ESLint config file itself, which the TypeScript project does not cover — producing a stack trace rather than a lint error. |
| A-061 | choice | The React hooks plugin registered explicitly rather than through its preset | Its shipped configuration is not flat-config shaped in the current major version; spreading the rules object is version-proof. |

## Step 0.6 — Configuration schema

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-062 | choice | Sixteen settings groups, each with its own environment prefix, rather than one nested structure | Prefixed variables read better in an env file than nested delimiters, and each group can be constructed independently in a test. |
| A-063 | choice | **No absolute reranker threshold setting exists.** Only a relative margin | Following directly from A-047. A plausible-looking `EVIDENCE_SCORE_THRESHOLD=0.0` would discard every candidate. Omitting the knob is more reliable than documenting that it is dangerous, and a test fails if one is reintroduced. |
| A-064 | choice | Seven invariants enforced at startup rather than documented | A misconfiguration that boots successfully is the one that reaches production. |
| A-065 | choice | `.env.example` and the schema kept in sync in **both** directions by tests | A declared key no setting reads is worse than an absent one — it looks configured and does nothing. |
| A-066 | choice | Ruff's ambiguous-unicode rules for docstrings and comments disabled; the identifier rule kept | Prose legitimately contains typographic dashes. Ambiguous characters in *identifiers* are the actual homoglyph hazard. |
| A-067 | correction | The secret-leakage test rewritten to inject a sentinel value | The first version's regular expression matched the literal wrapper text `service_role_key=SecretStr(`, so it was failing on the redaction working correctly. |
| A-068 | correction | The "no absolute threshold" test rewritten to parse assignment keys | The first version matched the word *absolute* in the explanatory comment. |

## Step 0.7 — Environment verification

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-069 | choice | SKIP and FAIL are distinct, and only FAIL sets a non-zero exit code | A script that reports failure on a machine nobody has configured yet is a script nobody runs until it is too late to help. |
| A-070 | choice | A third state, WARN, for configurations that are wasteful rather than broken | A GPU Paddle build when the configuration says CPU is worth saying and is not a failure. |
| A-071 | choice | Verification is live — a real GPU matmul, a real presigned URL fetch with byte comparison | Checking that a library imports proves considerably less than checking it works. |
| A-072 | discovery | Ollama is not installed on this machine | Confirmed rather than inferred. Moved in the inputs table to the phase that actually needs it. |

## Cross-cutting revisions

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-073 | deviation | The "no identifiers in comments" instruction extended to **validation error message strings**, beyond the literal request | An operator hitting an error at two in the morning should not need the requirements register open. Flagged at the time so it could be reverted. |
| A-074 | correction | `PLAN.md` was corrupted by a PowerShell read-write round trip that re-encoded every typographic character; restored from the index and the edits redone | PowerShell 5.1 reads as ANSI and writes as UTF-8. Editing files through the shell was abandoned. |

---

# Phase 1 — Domain layer

## Step 1.1 — Domain vocabulary

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-075 | choice | Behaviour attached to enum members rather than placed in services | Routing rules are stated once and testable directly. Scattered conditionals drift apart. |
| A-076 | choice | `MemoryProvenance` added as an ordered enum, beyond the plan's list | "A recent correction outranks an assistant guess" is an ordering. Modelling it as one avoids reimplementing the comparison in Phase 14. |
| A-077 | choice | Ten enums included beyond the plan's named list — page kind, processing method, job status, message role, graph node type, model task, claim status, retriever kind, memory type, memory provenance | Each is needed by an entity in steps 1.2 to 1.6. Splitting them across steps would mean editing this module five more times. |
| A-078 | deviation | Study-content enums deliberately excluded | Summary kinds and question types belong with the entities in Phase 15, and were not in the step's stated scope. |
| A-079 | choice | `BoundingBox` carries no page number | A box is a region; which page it is on belongs to whatever owns the box. Two sources of truth for the same fact is how they diverge. |
| A-080 | choice | `BoundingBox` given intersection-over-union and merge now rather than in Phase 6 | Associating captions with figures needs both. Geometry reimplemented at three call sites is geometry wrong at two of them. |
| A-081 | choice | `TokenBudget.allocate` raises rather than clamping | Silently truncating would build an answer on less evidence than the caller believes it supplied. A separate method exists for the shedding path, where not fitting is expected. |
| A-082 | choice | `ScopeContext.__str__` truncates identifiers to eight characters | It ends up in log lines, where full UUIDs are noise rather than information. |
| A-083 | choice | `NotFoundError` and `ScopeViolationError` kept as distinct types despite mapping to the same response | A resource the caller does not own must be indistinguishable from one that does not exist, or the API becomes an oracle for guessing identifiers. Distinct internally is what lets one be logged as a security event and the other not. |
| A-084 | choice | `CoverageStatus.CONFLICTING` does not trigger another retrieval round | More searching will not resolve sources that genuinely disagree. The disagreement is the finding. |
| A-085 | correction | Exception classes renamed with the `Error` suffix | Ruff's naming check enforcing the language convention. It was right. |
| A-086 | choice | `JobType.SYNC_GRAPH_PROJECTION` has a member name that differs from its stored value `SYNC_NEO4J` | The stored value keeps schema compatibility with the specified job-type set; the member name describes what it would actually do. |
| A-087 | correction | An enum test asserts string behaviour through `str()` and `.value` rather than direct comparison | A member whose name and value deliberately differ makes the direct comparison unprovable to the type checker, though it holds at runtime. |

## Step 1.2 — Knowledge Base and document entities

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-088 | choice | `UntrustedText` introduced as a type, and `DocumentElement.text` uses it | Document text must reach a prompt as evidence, never as instruction. A type carries that provenance where a convention would not. Its `__str__` returns a placeholder rather than the content, so accidental interpolation into a prompt template produces visibly wrong output instead of handing a document author the system prompt. |
| A-089 | choice | `app/domain/invariants.py` added for shared validation helpers | Every entity checks the same handful of things. Written once, the messages stay consistent and the checks cannot quietly diverge across six modules. |
| A-090 | choice | `KnowledgeBase.scope` derives the scope from the entity itself | Nothing downstream should have to pair a user identifier with a Knowledge Base identifier by hand and risk pairing them wrongly. Every scoped entity now reports its own scope. |
| A-091 | choice | `COMPLETED → PROCESSING` is permitted; `COMPLETED → PENDING` is not | Reprocessing after an embedding-model change must be possible. Returning to pending would describe an already-ingested document as never having been ingested. |
| A-092 | choice | `DELETING` is an absorbing state with no outbound transitions | A path back would make content retrievable again after its files had been removed. |
| A-093 | choice | Transitions take `now` as a required argument; the domain reads no clock | Behaviour stays reproducible and no test has to freeze a global. |
| A-094 | choice | A failed document must carry a reason, and a non-failed one must not | A failure nobody can act on tells the student only that something went wrong; a stale reason on a recovered document misreports its state. |
| A-095 | choice | A completed document must know its page count | Completion means the pipeline ran to the end, which is not describable without knowing what it covered. |
| A-096 | choice | An element produced by OCR must carry both a bounding box and a confidence | It was read from a rendered region, so its location is known. A citation that cannot be opened at a location is not much of a citation. |
| A-097 | choice | `ExplanationLevel` added to the enums, with three levels | The Knowledge Base carries an explanation level but the specification does not enumerate one. A free string would have no closed set to route on. |
| A-098 | assumption | Low extraction confidence is defined as below 0.6 | A placeholder threshold with no data behind it. Should be calibrated once real OCR output exists — recorded in the open assumptions table. |
| A-099 | discovery | mypy was not checking the test suite at all | Two `conftest.py` files without package markers collided on module name, and mypy stops after that error. Adding `__init__.py` to the test directories fixed it and immediately surfaced eleven genuine annotation gaps. |
| A-100 | correction | Fixture factories typed with a generic `Builder[T]` protocol rather than silenced with ignore comments | The first version scattered `# type: ignore[no-untyped-def]` at every call site, which switches type checking off for the test that uses it — the opposite of what running mypy over tests is for. |
| A-101 | correction | Test directories became packages, and their `.gitkeep` placeholders were removed | Required by the module-name fix. It also makes the relative imports between test modules legitimate rather than incidentally working. |
| A-102 | correction | A bulk regular-expression edit across the test files produced a syntax error and several over-long lines | Multi-line signatures were not matched by a pattern written for single-line ones. Repaired by hand. Bulk edits over Python signatures are not reliable; targeted edits are. |

## Step 1.3 — Retrieval entities

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-103 | choice | `Chunk` lives under documents rather than retrieval | It is derived from document elements and carries document identifiers, page numbers and a heading path. Retrieval consumes it; it is not owned by retrieval. |
| A-104 | choice | `EvidenceLabel` is a value object parsing and rendering `S1`, not a bare string | The model never sees a chunk identifier, so it cannot invent one that happens to exist. An invented label is either out of range or malformed, and both are caught by the type. |
| A-105 | choice | `EvidenceSet` refuses to span more than one scope, at construction | Mixed evidence is a leak that has already happened by the time anyone inspects it. Refusing it where it would be assembled is the last moment it is still preventable. |
| A-106 | choice | Citation resolution goes through `EvidenceSet.require`, never through a repository lookup | A chunk can be real, belong to the right student and the right Knowledge Base, and still not have been supplied for this question. Resolving against the database would wave that through; resolving against what was actually put in front of the model does not. |
| A-107 | choice | `Evidence` must record at least one retriever | Evidence that arrived from nowhere cannot be explained or reproduced, and retrieval decisions have to be inspectable after the fact. |
| A-108 | choice | Mandatory scope filters are deliberately absent from `RetrievalFilters` | It holds only optional narrowing. A field can be left unset, and the user, Knowledge Base and completed-status predicates must not be capable of being unset. |
| A-109 | choice | `RetrievalPlan.for_query` derives routing from the properties already on the query class | A second, separate set of rules would drift from the first. This reads as an application of the existing rules rather than a restatement. |
| A-110 | choice | An early exit is dropped when the object it depends on was not actually selected | Asking about "the table on page 67" without having selected one still needs a search to work out which table that is. |
| A-111 | choice | `RetrievalPlan` validates that graph retrieval and the graph flag agree, and that a shortcut never coexists with query expansion | Both are states that would silently produce the wrong pipeline rather than an error. |
| A-112 | choice | `Chunk.carries_a_visual` excludes tables | A table's structured form is authoritative, so answering from it does not require re-reading the picture. A figure's stored description is derived, so it does. |
| A-113 | choice | Compression may not lengthen text or empty a chunk, and does not recompute the token count | Compression that adds text is generation. The caller knows the tokenizer, and a guessed count would corrupt the context builder's budget. |
| A-114 | discovery | `enums.py` already contained an `EarlyExitPath`, added outside this session, and my edit created a duplicate class definition | Caught by the linter's redefinition check. Reconciled rather than overwritten: the pre-existing member names describe the path taken (`TABLE_LOOKUP`) rather than its trigger, which reads better at the call site, so those were kept. |
| A-115 | deviation | "No early exit" is `None` rather than an enum member | Follows from A-114 — the pre-existing enum had no member standing for absence, and adding one would have been wrong anyway. No shortcut is not a kind of shortcut. |

## Step 1.4 — Conversation and memory entities

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-116 | choice | `MessageStatus` gained `can_transition_to`, `successors`, and `is_terminal` on the enum itself | Consistent with `DocumentStatus`, which carries the same machinery. The state machine lives with the type it describes, not distributed across callers. |
| A-117 | choice | `Conversation` stores active_document_id, active_page_number, active_figure_id, and active_table_id as plain optional fields, not as a nested state object | The context is shallow — at most four fields — and the navigation methods are straightforward replaces. A nested state object would add indirection with no corresponding benefit. |
| A-118 | choice | Figure and table selections are mutually exclusive and enforced by `__post_init__` | At any moment the student has selected at most one visual object. Permitting both simultaneously would require every routing decision to resolve the tie — better to refuse the state upfront. |
| A-119 | choice | `focus_page`, `focus_figure`, and `focus_table` do not check `active_document_id` themselves; the invariant in `__post_init__` catches it on the resulting entity | A guard in the method and a guard in the invariant would be two statements of the same rule. A single guard in `__post_init__` is the one the frozen dataclass already guarantees will run. |
| A-120 | choice | `Message.content` is `UntrustedText` for both user and assistant roles | User input can carry injection attempts. Assistant output can carry injected content absorbed from documents and may reappear in a future turn's context. Uniform provenance tracking forces callers to use `.value` explicitly rather than interpolating content by accident. |
| A-121 | choice | `model_id`, `prompt_tokens`, and `completion_tokens` must be set together or not at all; `finish_reason` is independently optional | The three core fields come from a single provider response and are meaningless apart from each other. `finish_reason` varies by provider and is genuinely absent in some responses. |
| A-122 | choice | `MemoryFact.create_successor` receives `successor_id` from the caller rather than generating it internally | Callers can then construct both facts and write them atomically in a single transaction without a database round-trip to learn the generated key. The entity stays deterministic and testable with known identifiers. |
| A-123 | choice | Supersession is only permitted from `ACTIVE` status | A disputed, expired, or already-superseded fact was never the current truth; superseding it would imply it was. A correction on an UNCONFIRMED fact should delete it, not supersede it, since it was never confirmed as true. |
| A-124 | choice | `mark_deleted` blocks `SUPERSEDED` facts in addition to already-deleted ones | Deleting the retired half of a supersession chain would break the audit link. The old fact must stay in the database for as long as the new one lives. |
| A-125 | choice | `valid_until: None` means the fact is valid indefinitely | A mandatory expiry would require setting an arbitrary far-future sentinel for facts that do not expire (exam dates, permanent goals). `None` represents "no expiry" without encoding it as a magic value. |
| A-126 | choice | Both `Conversation` and `MemoryFact` expose a `scope` property that derives from the stored identifiers | Consistent with `KnowledgeBase`, `Document`, and `Chunk`. Any entity that belongs to a user and a Knowledge Base reports its own scope rather than requiring the caller to pair the identifiers by hand. |

## Step 1.5 — Graph entities

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-127 | choice | `GraphRelationship` provenance fields — `source_chunk_id`, `page_number`, `evidence` — are positional required fields with no defaults | The plan's requirement is "unrepresentable-if-absent at the type level". Required positional fields enforce this structurally: you cannot call the constructor without supplying them. A __post_init__ check alone could be bypassed by `dataclasses.replace`; required fields cannot. |
| A-128 | choice | `evidence` is `UntrustedText`, not a plain `str` | The evidence passage is a span extracted from document content. It carries the same injection risk as the source chunk's text and must not be interpolated into a prompt template without explicit `.value` access. |
| A-129 | choice | `GraphEntity` source provenance fields are optional | Structural nodes (KNOWLEDGE_BASE, DOCUMENT) exist in the schema independently of extraction and have no chunk provenance. Making the fields optional is the right trade-off; the per-type constraint belongs in the extraction service, not in the entity constructor. |
| A-130 | choice | Self-loops (`source_entity_id == target_entity_id`) are rejected at construction | A relationship that links an entity to itself is meaningless for any of the defined relationship types and most likely indicates an extraction error. |
| A-131 | choice | `weight` defaults to 1.0 but must be positive | An initial extraction gives equal weight to all edges. Algorithms that refine weights (community detection, PageRank-style scoring) may update it, but a zero or negative weight is not a valid graph weight in any standard formulation. |
| A-132 | choice | `extraction_confidence` is optional and independent of `weight` | Confidence is the model's estimate of correctness; weight is the traversal score. They start from different sources and are refined by different processes. Conflating them into one field would make it ambiguous which process last touched the value. |
| A-133 | choice | The boundary test now covers `app/domain/graph/` alongside the other domain subdirectories | Verified: the domain import audit still lists only `['__future__', 'app', 'dataclasses', 'enum', 'typing', 'uuid']`. `app.domain.graph.entities` imports nothing outside the domain. |

## Step 1.6 — Model and job entities

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-134 | assumption | The seven slots for `ModelRequest` are: system preamble, safety rules, task instructions, memory context, evidence, conversation history, query | The specification mentions a seven-slot structure and a prompt normalizer that maps it to a provider payload, but does not enumerate the slots in the sections available. The seven slots were derived from Phase 10's context builder description (instruction handling by priority level, followed by memory, evidence, history, and query). Confirm when Phase 10 is implemented. |
| A-135 | choice | `ConversationTurn` lives in `models/entities.py` alongside `ModelRequest`, not in `values.py` | It is a value type in terms of semantics but exists solely as a slot in `ModelRequest.conversation_history`. Placing it in `models/` makes the connection explicit. |
| A-136 | choice | `ModelRequest.query` is `str`, not `UntrustedText` | By the time a query reaches a `ModelRequest`, it has been through the query rewriter, which produces a normalised string. The context builder's responsibility is to use the rewritten form. Evidence and conversation history remain `UntrustedText` because they arrive from uncontrolled sources. |
| A-137 | choice | `ModelRequest.evidence` is `tuple[UntrustedText, ...]` | Retrieved document passages carry the same injection risk as the chunk text they came from. The prompt normalizer must handle them explicitly via `.value`, not by interpolation. |
| A-138 | choice | `ModelRequest.memory_context` is `tuple[str, ...]` | Memory facts are application-validated strings — their content is never directly from user input without a verification step. Treating them as trusted strings keeps the model prompt readable without hiding a real risk. |
| A-139 | choice | `ProcessingJob` placed in a new `app/domain/jobs/` subdirectory, not in `models/` | A job is a durability wrapper around async work, not a model artifact. Keeping them in separate packages makes the boundary visible in the import graph. |
| A-140 | choice | `attempt_count` increments on `claim`, not on `fail` | The count tracks how many attempts were *started*. A started attempt that crashes before reporting failure should still count. Incrementing on fail would undercount if the worker dies mid-run. |
| A-141 | choice | `fail` decides `FAILED` vs `DEAD_LETTER` by checking `attempt_count >= max_attempts` at the moment of failure, after claim has already incremented the count | This means the final attempt lands in `DEAD_LETTER` automatically — no separate transition is needed. `requeue` is then the path back to `PENDING` for intermediate failures, with a guard that rejects requeueing once the budget is spent. |
| A-142 | choice | `heartbeat` uses `dataclasses.replace` directly rather than `_transition` | Heartbeat does not change status — it extends `lease_expires_at` and updates `last_heartbeat_at`. Using `_transition` would require a `RUNNING → RUNNING` entry in the transition table, which would be misleading. |
| A-143 | choice | `scheduled_at` included on `ProcessingJob` for delayed jobs | Some jobs (summary rebuild, memory compaction) are enqueued with a future start time. `scheduled_at: None` means the job is immediately claimable; a set value means workers skip it until that time passes. |
| A-144 | choice | `payload: Mapping[str, str]` uses `collections.abc.Mapping` for a read-only view | The domain entity sees the payload as immutable. Callers pass a `dict[str, str]`, which satisfies `Mapping[str, str]`. The frozen dataclass prevents the field from being reassigned; the type annotation communicates that downstream code must not mutate it. |
| A-145 | correction | mypy reported "Incompatible types in assignment" because `ts` was reused across two `for` loops with different element types (`datetime` then `datetime | None`) | Python loop variables persist in scope after the loop ends, and mypy tracks the inferred type. Fixed by renaming to `req_ts` (required datetime) and `opt_ts` (optional datetime) in the respective loops. |
| A-146 | choice | `JobStatus.DEAD_LETTER → CANCELLED` is a permitted transition | An administrator may cancel a dead-lettered job rather than leaving it in the queue indefinitely. `DEAD_LETTER → PENDING` is not permitted — a dead-lettered job has exhausted its retry budget. |
| A-147 | choice | `requeue` blocks when `attempt_count >= max_attempts` rather than relying on the transition table alone | The enum cannot see `attempt_count`, so it marks `FAILED → PENDING` as valid universally. The entity guards the business rule: a failed job with no remaining attempts must not be requeued. The guard raises `InvariantViolationError` rather than `IllegalTransitionError` because the status transition itself is valid — it is the entity's internal state that forbids it. |
| A-148 | choice | `ModelResponse.content` is `UntrustedText` | Model output can reflect injected content absorbed from document passages or malicious conversation turns. Treating it as plain text would allow it to be interpolated into subsequent prompts or displayed without review. Downstream callers must access `.value` explicitly. |

## Step 1.7 — Repository ports

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-149 | choice | Ports placed in `app/domain/ports/`, not `app/application/ports/` | ARCHITECTURE.md section 4.1 explicitly lists ports in the Domain layer. The domain owns the contracts it depends on; infrastructure implements them by structural subtyping. The boundary test already walks all of `app/domain/` so no extra configuration was needed. |
| A-150 | choice | `KnowledgeBaseRepository.list_for_user` takes `user_id: UUID`, not `ScopeContext` | Listing KBs is how a session establishes which KB to work in — there is no KB id to put into a ScopeContext at that point. Documented as the first exception to the scope-first rule and tested explicitly: a test asserts the first non-self parameter is `user_id`, not `scope`. |
| A-151 | choice | `JobRepository` worker methods (`get`, `save`, `claim_next`) do not take `ScopeContext` | Workers pull from a shared queue across all users. Pre-scoping them would require manufacturing a scope for every job, coupling the worker to user management. `list_for_scope` still uses `ScopeContext` so the user-facing status path is correctly enforced. |
| A-152 | choice | All port methods are `async def` | D-25 requires an async data layer throughout. A sync implementation cannot satisfy an `async def` protocol method in mypy, so the constraint is enforced at type-check time rather than discovered at runtime. |
| A-153 | choice | `ConversationRepository` owns both `Conversation` and `Message` persistence | Messages are always accessed through their conversation. A separate `MessageRepository` would require callers to coordinate two repositories for every aggregate read, and would leave the conversation/message boundary visible to application-layer code that should not care about it. |
| A-154 | choice | `GraphRepository.delete_for_document` removes both entities and relationships in one call | A document deletion must clean up its extracted graph completely. Two separate delete methods would allow partial cleanup — entities removed but relationships left orphaned, or the reverse — and would require the caller to call both correctly every time. |
| A-155 | choice | Typed stub classes in `test_ports.py` rather than `@runtime_checkable` isinstance checks | `@runtime_checkable` only verifies that method names exist, not their signatures. Typed stubs are checked by mypy against the full protocol signature including parameter types and return types. The stubs also serve as working examples of what a conforming adapter looks like. |
| A-156 | choice | `inspect.signature` used in pytest to verify the scope-first rule at runtime | The scope-first constraint is a security property. mypy verification is necessary but not sufficient as a record — embedding it as a pytest assertion makes the invariant visible in the test suite, gives it a name, and produces a clear failure message if a future edit drops the `scope` parameter from a method. |

## Step 1.8 — Adapter ports

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-157 | choice | All 10 adapter ports placed in `app/domain/ports/adapters.py` alongside repositories | ARCHITECTURE.md places ports in the domain layer. A single file per concern (`repositories.py`, `adapters.py`) keeps the port surface browsable without scattering it across many files. |
| A-158 | choice | `PdfParserPort.parse` takes `scope: ScopeContext` as a keyword-only argument | The parser needs `user_id` and `knowledge_base_id` to produce correctly-scoped `DocumentPage` and `DocumentElement` objects. Making scope keyword-only reflects that it is a context parameter rather than part of the PDF data being processed. |
| A-159 | choice | `OcrPort.extract_text` takes `page: DocumentPage` rather than `scope: ScopeContext` directly | The page object already carries `user_id`, `knowledge_base_id`, `document_id`, and `page_number` — all the fields the OCR adapter needs to produce correctly-scoped elements. Passing scope separately would be redundant and would require the adapter to also receive document_id and page_number via additional parameters. |
| A-160 | choice | `EmbeddingPort` exposes separate `embed_documents` and `embed_query` methods | Some embedding models (BGE, E5) apply different instruction prefixes or pooling strategies for documents vs. queries. A single method would force the implementation to guess or accept a flag, both of which are error-prone. |
| A-161 | choice | `GraphPort` vocabulary is `neighbors` and `subgraph`, with no query language method | D-10 defers a graph database but requires the option to be available later. A port defined in graph-traversal vocabulary (`neighbors`, `subgraph`) means introducing a Neo4j adapter is a new file, not a change to callers. A method accepting a Cypher string would pin callers to Neo4j before it is even installed. |
| A-162 | choice | `StoragePort` and `CacheStore` do not take `ScopeContext` | Blob keys embed scope by convention (`{user_id}/{kb_id}/...`). Passing scope as a parameter would not add any enforcement — the adapter would still use the key to address the bucket, and an incorrect key is caught by the missing-object error, not by the type checker. Documented explicitly in the module docstring. |
| A-163 | choice | `ObservabilityPort.child` returns `ObservabilityPort` and binds values to every subsequent event | A use case calls `child(trace_id=..., request_id=...)` once at entry, then passes the child context to every stage. Stages call `emit` without knowing the trace ID. The alternative — threading `trace_id` through every emit call — causes every caller to manage a value it doesn't own. |
| A-164 | choice | `ObservabilityPort` methods are synchronous | Logging must not introduce `await` points inside a pipeline stage. structlog (D-26) is synchronous; an async port would force every implementation to use `asyncio.to_thread` for a library that doesn't need it. |
| A-165 | choice | `RerankerPort.rerank` returns scores in the same order as `candidates`, with no normalisation | The domain does not commit to a score range. Infrastructure determines the scale; calling code uses relative ordering. A normalised interface would hide implementation details that matter for debugging score distributions (A-047). |

## Step 1.9 — Model gateway port

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-166 | choice | `ModelProfile` placed in `model_gateway.py` alongside the protocols that reference it, not in `models/entities.py` | `ModelRequest` and `ModelResponse` are request/response data assembled and consumed per call. `ModelProfile` is static capability metadata about a provider. The two concerns are not naturally co-located; placing the profile next to the gateway port that uses it keeps the gateway's complete contract in one file. |
| A-167 | choice | Three protocol classes (`TextGenerationCapability`, `MultimodalCapability`, `ModelGatewayPort`) rather than one flat gateway protocol with all methods | Provider adapters implement one of the two narrow capability interfaces. The gateway implementation holds a registry of those adapters and itself implements `ModelGatewayPort`. Test stubs for individual providers satisfy a narrower protocol without implementing the full gateway contract. |
| A-168 | choice | `EmbeddingPort` and `RerankerPort` from `adapters.py` serve as the embedding and reranking capability interfaces; no parallel definitions added here | The plan names four capability interfaces; embeddings and reranking are pure-computation concerns with no private content and no privacy pre-flight. A second set of definitions in `model_gateway.py` would duplicate them with no additional constraint. |
| A-169 | choice | `ModelGatewayPort.profile_for` is synchronous | The capability registry is an in-memory mapping built at startup; the method is a dictionary lookup with no IO. A sync method avoids introducing unnecessary `await` points for code that may call `profile_for` in a guard check before building a large prompt. |
| A-170 | choice | The invariant `VISUAL_QUESTION in tasks → supports_images=True` is one-directional | A model may support image input for purposes other than VISUAL_QUESTION, so the reverse (`supports_images → VISUAL_QUESTION in tasks`) is not enforced. The enforced direction is the load-bearing one: a gateway that routes VISUAL_QUESTION to a provider without `supports_images=True` would fail at the provider call. |
| A-171 | discovery | `pytest-asyncio` was listed as a dev dependency but not installed, causing `--strict-config` to block all test runs with exit code 4 | Installed during this step. All 478 tests pass after installation. The root cause was a missing `pip install -e ".[dev]"` in this environment. |

## Step 1.10 — Composition root and wiring

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-172 | choice | `UseCase[_Req_contra, _Res_co]` Protocol placed in `app/application/use_case.py` to make the boundary test non-vacuous | The boundary test scans all non-empty files in `app/application/`. Before this step, all files there were empty `__init__.py` files, so the test passed vacuously. A `UseCase` Protocol is the natural first application-layer abstraction — all future command and query handlers will implement it. |
| A-173 | choice | TypeVars in `UseCase` use correct variance (`contravariant` for request, `covariant` for response) | mypy strict mode enforces variance in Protocol generic parameters. Invariant TypeVars produced a `[misc]` error in strict mode. The variance is also semantically correct: `execute` is a function type whose input is contravariant and output is covariant. |
| A-174 | choice | `Container` is a frozen dataclass with all 18 port fields typed to their Protocol types | A frozen dataclass gives named, typed access to every port without a mutable global. Request handlers receive the container through FastAPI state, not through module-level imports, which keeps the dependency graph explicit and the composition root the only place that chooses adapters. |
| A-175 | choice | `_Unimplemented` sentinel in `wire.py` raises `NotImplementedError` with the port name on `__getattr__`, not at `build_container` time | A startup crash would break the `test_lifespan_runs` test and make the app unusable for all endpoints that do not yet need a database. The sentinel approach lets the skeleton app start and serve the health endpoint; only requests that actually call a port method encounter the error. |
| A-176 | choice | `build_container` accepts `settings: Settings` now even though it is unused, suppressed with `# noqa: ARG001` | Callsites write `build_container(get_settings())`. Adding `settings` after the fact would require every callsite to change. The `# noqa` is local and documents why the argument exists. |

## Step 2.1 — Alembic setup and extension activation

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-177 | deviation | `psycopg` (psycopg3) used as the async driver, not `asyncpg` | The step description said "asyncpg driver" but `pyproject.toml` already specifies `psycopg[binary,pool]>=3.2`. `psycopg` is the modern psycopg3 package; SQLAlchemy 2.x uses it with `postgresql+psycopg://` for both sync and async engines. No additional dependency required. |
| A-178 | choice | `DATABASE_URL` read from `Settings().database.url.get_secret_value()` in `env.py`, not from `alembic.ini` | Credentials in ini files end up on disk and in log output. Reading from application settings keeps the URL in the `SecretStr` wrapper and applies all the same environment-variable resolution that the app uses. |
| A-179 | choice | `downgrade()` in `0001_activate_extensions.py` is a deliberate no-op | Dropping extensions while vector columns, rum indexes, and pg_cron jobs from later migrations still reference them would cascade-drop all those objects. The objects that use the extensions are cleaned up by their own migrations on downgrade. |
| A-180 | choice | Sequential numeric revision `0001` instead of alembic's default hex hash | Human-readable ordering across 20+ migrations. No `alembic revision --autogenerate` chains exist yet, so there is no collision risk from a fixed string. |
| A-181 | assumption | `rum` and `pg_cron` extensions must be enabled in Supabase before the migration runs | `vector` and `pg_trgm` are available by default on Supabase. `rum` and `pg_cron` may need explicit activation in the Supabase Dashboard → Database → Extensions panel. Unverified until the user runs `alembic upgrade head` against their project. |
| A-182 | choice | `known-third-party = ["alembic"]` added to ruff isort config in `pyproject.toml` | The `alembic/` directory at the repo root causes ruff/isort to treat the `alembic` package as first-party. The addition tells ruff to treat it as third-party (same group as `sqlalchemy`) so imports are sorted correctly in `alembic/env.py`. |

## Step 2.2 — Knowledge Base, Document & Page models

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-183 | choice | `test_metadata_starts_empty` removed from `test_alembic_setup.py` | `Base.metadata` is a process-level singleton. Importing the models package (which this step does, in the new test file) registers all three tables with it. Once any model is imported in the same pytest process, the assertion `len(Base.metadata.tables) == 0` becomes permanently false regardless of test ordering. |
| A-184 | choice | Table named `document_pages`, not `pages` | `pages` is too generic — the database will eventually contain graph entity pages, memory pages, etc. `document_pages` is unambiguous and self-describing in queries and FK targets. |
| A-185 | choice | `DocumentElement` model deferred to step 2.3 | Per plan: `document_elements` belongs with the chunk models because elements are the source units that chunks are built from; they land together with `chunks`, the pgvector column, and the tsvector trigger. |
| A-186 | choice | `import app.infrastructure.database.models` placed before `from app.*` in `alembic/env.py` | isort places bare `import` statements before `from` statements within the same package group. Placing it after would trigger ruff I001. Functionality is identical — Python caches modules, so the three first-party imports load each module at most once regardless of order. |
| A-187 | choice | `DocumentPageModel.knowledge_base_id` carries no FK constraint | The column is a denormalized scope field for row-level security and index coverage. The cascade from deleting a knowledge base is handled via `documents.knowledge_base_id → knowledge_bases.id ON DELETE CASCADE` followed by `document_pages.document_id → documents.id ON DELETE CASCADE`. An additional FK would create a redundant constraint and complicate bulk-load ordering. |
| A-188 | mypy fix | `isinstance` narrowing added before `.length` and `.timezone` attribute access in tests | `Column.type` is typed as `TypeEngine[Any]`, which has no `.length` or `.timezone` attributes. An `isinstance(col_type, sa.String)` / `isinstance(col_type, sa.DateTime)` check narrows the type so mypy can verify the attribute exists. |

## Step 2.3 — Chunk models, embedding column, tsvector column, versioning columns

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-189 | choice | `DocumentElementModel` placed in `chunk.py` alongside `ChunkModel` | Both are produced by the ingestion pipeline in the same step; they reference each other via FK (`source_element_id`, `chunk_elements`), so keeping them in one file avoids a circular-import problem between model files. |
| A-190 | choice | `VECTOR(384)` dimension hardcoded at schema level; `embedding_dimension` column records the actual per-row dimension | The schema dimension is fixed at migration time and changes only on a reindex migration. The per-row column records what was actually embedded, for migration-period coexistence where some rows were embedded with the old model and some with the new. |
| A-191 | choice | `chunks.tsv` is `TSVECTOR` maintained by the `chunks_tsv_update` trigger, not a PostgreSQL generated column | Trigger approach allows combining multiple columns with different language weights later (e.g., weighting heading text higher than body text) without a migration. Generated columns (`GENERATED ALWAYS AS`) cannot use dynamic configuration or combine multiple source columns with different weights. |
| A-192 | choice | `chunks.parent_chunk_id → chunks.id ON DELETE SET NULL` (self-referential) | If a parent chunk is deleted in isolation (unusual), its children survive with `parent_chunk_id = NULL` rather than being cascade-deleted. Normal deletion flows go through the document cascade, which deletes all chunks regardless. |
| A-193 | choice | `chunks.source_element_id → document_elements.id ON DELETE SET NULL` | The chunk can outlive its primary source element reference; the full element set is tracked via `chunk_elements`. Setting to NULL on element deletion preserves the chunk without orphan errors. |
| A-194 | bug fix | `server_default` for `TEXT[]` columns must use `sa.text("'{}'")`  not a plain string `"'{}'"` | Alembic SQL-quotes plain strings in `server_default`, turning `'{}'` into `'''{}'''`. PostgreSQL then parses `'{}'` (with embedded single quotes) as a string value rather than an array literal, which fails with "Array value must start with {". `sa.text()` bypasses the quoting layer and passes the expression through literally. |
| A-195 | bug fix | `import sqlalchemy as sa` added to `chunk.py` instead of `from sqlalchemy import text` | The `text: Mapped[str]` column attribute in `DocumentElementModel` and `ChunkModel` shadows the imported `text` function within the class body. Accessing it via `sa.text()` avoids the collision because `sa` (the module alias) is not a column name in either class. |
| A-196 | choice | `heading_path` stored as `TEXT[]`, not JSONB or delimited string | `TEXT[]` maps directly to `tuple[str, ...]` without serialization overhead, supports PostgreSQL array operators if needed, and is more idiomatic than JSONB for a fixed-element-type sequence. |
| A-197 | step | Step 2.4 — retrieval indexes migration `0004_retrieval_indexes.py` | HNSW on `chunks.embedding` (`vector_cosine_ops`, `m=16`, `ef_construction=128`); RUM on `chunks.tsv` (`rum_tsvector_ops`); six composite B-tree scoped indexes on `(user_id, knowledge_base_id, <col>)` for `document_id`, `chunk_type`, `index_version`, `language`, `ordinal`, `content_hash`. 10 unit tests. Migration applied at `0004 (head)`. |
| A-198 | choice | HNSW `m=16, ef_construction=128` | Balanced choice: good recall for text embeddings at student scale (5k–20k chunks), builds in seconds. `m=32` and higher `ef_construction` are reserved for production-scale recall tuning; a `REINDEX` applies them without touching table DDL. |
| A-199 | choice | Six composite index third columns: `document_id`, `chunk_type`, `index_version`, `language`, `ordinal`, `content_hash` | Covers document-scoped listing, modality type filtering, version-pinned retrieval for reindexing, language filtering, sequential ordering queries, and deduplication during re-ingestion. |

## Step 2.5 — Conversation, Message & Memory models

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-200 | step | Step 2.5 — four ORM models in `conversation.py`, migration `0005_conversations_messages_memory.py`, 33 unit tests, `0005 (head)` | `ConversationModel`, `MessageModel`, `ConversationRetrievalChunkModel`, `MemoryFactModel`. |
| A-201 | choice | `messages` model-metadata stored as four separate columns (`model_id`, `prompt_tokens`, `completion_tokens`, `finish_reason`), not a JSONB `model_metadata` blob | The plan described JSONB but the domain entity has individual typed fields. Individual columns are directly queryable (e.g. aggregate token usage), and the domain entity is the authoritative source. |
| A-202 | choice | `memory_facts.provenance` stored as `INTEGER` (the ordinal of the `MemoryProvenance` `IntEnum`) | `MemoryProvenance` is an `IntEnum` where the ordering is load-bearing (higher = more trusted). Storing the integer value makes trust-ordered queries and comparisons native to the column without a lookup table. |
| A-203 | choice | `active_figure_id` and `active_table_id` on `conversations` carry no FK constraint | The visual-element tables (figures, tables) are defined in Phase 6. Adding FK constraints now would introduce a circular dependency on tables that do not yet exist. FKs will be backfilled in Phase 6 if needed, or left as application-enforced references. |
| A-204 | choice | `PLC0415` added to the `tests/**` ruff per-file-ignores | In-method imports are used across all existing test files to control SQLAlchemy mapper registration order — the models register themselves on import, and test isolation sometimes requires controlling when that happens. The rule was already violated in `test_model_gateway.py` and `test_container.py`; adding the ignore resolves the whole class consistently. |

## Step 2.6 — Graph models and traversal indexes

| ID | Kind | Entry | Why |
|---|---|---|---|
| A-205 | step | Step 2.6 — two ORM models in `graph.py`, migration `0006_graph_entities_relationships.py`, 27 unit tests, `0006 (head)` | `GraphEntityModel` and `GraphRelationshipModel`. |
| A-206 | deviation | `canonical_name` (plan) renamed to `name` to match the domain entity | The domain entity uses `name`; the plan's `canonical_name` was a description of the semantics, not the actual field name. The scope+name index still serves as the canonical-name lookup index. |
| A-207 | deviation | `active_graph_version` omitted from `graph_entities` | Only `graph_version` was added, per user decision. `active_graph_version` is a KB-level property (already on `knowledge_bases`); duplicating it on every entity would create a consistency hazard with no retrieval benefit. |
| A-208 | choice | `graph_relationships.source_chunk_id` FK is `ON DELETE CASCADE` | Deleting the source chunk removes the provenance that justified the edge; the edge should not outlive its evidence. `SET NULL` is not available because the column is NOT NULL (provenance invariant). `RESTRICT` would block document-level cascade deletes unnecessarily. |
| A-209 | choice | `user_id`/`knowledge_base_id` denormalized onto `graph_relationships` | The domain entity already carries these fields; storing them directly avoids a join through `graph_entities` in every RLS policy and retrieval query. |

### Step 2.7 entries

| ID | Kind | Summary | Detail |
|---|---|---|---|
| A-210 | step | Step 2.7 — two ORM models in `job.py`, migration `0007_job_queue_cache.py`, 26 unit tests, `0007 (head)` | `ProcessingJobModel` and `CacheEntryModel`. |
| A-211 | deviation | `error_message` (plan) renamed to `failure_reason` to match the domain entity | The domain `ProcessingJob` entity uses `failure_reason`; aligning the column name eliminates a translation layer in the repository. |
| A-212 | choice | `scheduled_at` column added to `processing_jobs` | The domain entity carries `scheduled_at`; it enables deferred jobs (queued now, claimable only after a future time) without a schema change. The plan did not list it but it is present in the domain entity. |
| A-213 | choice | `(status, priority)` claim index landed in step 2.7 (not deferred) | The index exists exclusively to support `FOR UPDATE SKIP LOCKED` claim queries; shipping it now with the table keeps DDL and usage rationale co-located. Deferring to a later step would leave the table without its primary access path. |
| A-214 | correction | `postgresql_unlogged` is not a valid SQLAlchemy `Table` kwarg; `__table_args__` removed from `CacheEntryModel` | SQLAlchemy's `_validate_dialect_kwargs` raises `ArgumentError` for `postgresql_unlogged` because the PostgreSQL dialect does not register it as a supported Table-level option. The UNLOGGED flag is a DDL-only concern handled entirely by the migration's raw `CREATE UNLOGGED TABLE` statement. The ORM model carries no `__table_args__`; the docstring is the model-level signal. `test_table_is_declared_unlogged` updated to verify the docstring instead of `table.kwargs`. |

### Step 2.8 entries

| ID | Kind | Summary | Detail |
|---|---|---|---|
| A-215 | step | Step 2.8 — RLS policies migration `0008_rls_policies.py`, 16 unit tests, `0008 (head)` | `ENABLE ROW LEVEL SECURITY` + `FOR ALL` policy on all 12 scoped tables. No model file changes. |
| A-216 | choice | `FOR ALL` policy (single policy per table) rather than four operation-specific policies | A single `FOR ALL` with `USING` + `WITH CHECK` is the standard Supabase pattern and achieves the same security with less DDL. Separate per-operation policies are deferred to Phase 3 if more granular control is needed. |
| A-217 | choice | Bridge tables covered by EXISTS subquery to their scoped parent | `chunk_elements` joins through `chunks`; `conversation_retrieval_chunks` joins through `messages`. The parents carry `user_id` so the EXISTS check is equivalent to a direct `user_id = auth.uid()` filter without requiring `user_id` denormalization on the bridge tables. |
| A-218 | choice | `processing_jobs` and `cache_entries` left without RLS | These system tables carry no `user_id` and are not exposed through Supabase's auth layer. They will be locked down with a service-role bypass policy when Phase 3 introduces authentication. |
| A-219 | choice | No `FORCE ROW LEVEL SECURITY` applied | `FORCE ROW LEVEL SECURITY` would also apply policies to the table owner (`postgres`). Since no service-role bypass is wired yet and Phase 3 will add it explicitly, forcing at this stage would lock out legitimate internal operations. |

### Step 2.9 entries

| ID | Kind | Summary | Detail |
|---|---|---|---|
| A-220 | deviation | Plan specifies asyncpg driver; psycopg3 async used instead | `asyncpg` is not in `pyproject.toml` dependency groups; `psycopg[binary,pool]` (psycopg3) is installed and fully supports async via `create_async_engine("postgresql+psycopg://...")`. Adding asyncpg would be an unnecessary new dependency. `_normalise_url` converts bare `postgresql://` and `postgres://` to `postgresql+psycopg://`; existing `.env` URL is already in that form. |
| A-221 | choice | `session_factory` added to `Container` dataclass rather than stored separately on `app.state` | Consistent with the existing pattern — everything injected at the composition root lives in the Container. Phase 3 route handlers will read it through a FastAPI dependency without needing to know the engine exists. |
| A-222 | choice | Stub factory placed in `Container.session_factory` when `DATABASE_URL` is absent | `create_async_engine` with an empty URL raises `ArgumentError` immediately. The guard in `build_container` keeps the Container constructable during unit tests that don't configure a database, which matches the existing pattern for unimplemented adapters. |
| A-223 | choice | `ScopedRepository._user_filter` covers the listing case for `knowledge_bases` | `knowledge_bases` has `user_id` but no `knowledge_base_id` column. `_user_filter(KnowledgeBaseModel)` returns `user_id = :user_id`; `_scope_filter` would raise `AttributeError` on that model. Concrete `KnowledgeBaseRepository` methods that need the KB id match it against `id = scope.knowledge_base_id` directly. |
| A-224 | correction | `literal_binds` renders UUIDs without hyphens in SQLAlchemy 2.0 | SQLAlchemy's UUID literal rendering strips hyphens (e.g. `d682bd1f3a04...` not `d682bd1f-3a04-...`). Filter-binding tests now use `str(uuid).replace("-", "")` for comparison. |

### Step 2.10 entries

| ID | Kind | Summary | Detail |
|---|---|---|---|
| A-225 | deviation | `upsert_embedding` is not in the `ChunkRepository` protocol — step skipped | The Phase 1 protocol (`repositories.py`) defines only `get`, `save_batch`, `list_for_document`, and `delete_for_document`. The plan step mentioned `upsert_embedding` but it was never added to the Protocol. `save_batch` stores chunks without embeddings; the embedding worker populates them later outside the repository layer. |
| A-226 | choice | Repositories are NOT wired into Container; container holds stubs until Phase 3 | `SqlKnowledgeBaseRepository`, `SqlDocumentRepository`, and `SqlChunkRepository` require both a `ScopeContext` and an `AsyncSession`, which are per-request values. Putting them in the container as singletons would not work. They will be constructed in FastAPI request dependencies (Phase 3) from the container's `session_factory`. |
| A-227 | choice | `repositories/` package under `infrastructure/database/` with one file per repository | Three files (`knowledge_base.py`, `document.py`, `chunk.py`) plus `__init__.py`. Each file defines one concrete class and private mapping helpers (`_to_entity`, `_to_model`). Separates concerns without over-engineering. |
| A-228 | deviation | `DocumentElementModel` and `ChunkModel` tests use `AsyncMock` session, not SQLite | Both models contain PostgreSQL-specific column types (`ARRAY(Text())`, `Vector`, `TSVECTOR`) that aiosqlite cannot create or process. KB, Document, and Page tests use real SQLite; Element and Chunk tests verify SQL compilation and call counts via `AsyncMock`. |
| A-229 | correction | `AsyncSession.expire_all()` is synchronous — `await` raises `TypeError` | `expire_all()` marks objects expired in the identity map without touching the DB; it returns `None`, not a coroutine. Tests call `session.expire_all()` (no `await`). |
| A-230 | correction | SQLite strips timezone from `DateTime(timezone=True)` columns | SQLAlchemy's SQLite dialect does not preserve `tzinfo` on readback. All three repository mapping modules add a private `_utc(dt)` helper that calls `dt.replace(tzinfo=timezone.utc)` when `dt.tzinfo is None`. PostgreSQL always returns tz-aware datetimes so the helper is a no-op there. |
| A-231 | choice | `aiosqlite>=0.20` added to `[dev]` dependency group | Required async SQLite driver for `create_async_engine("sqlite+aiosqlite:///:memory:")` in the repository unit tests. Not a runtime dependency. |
| A-232 | choice | Every scoped method calls `ScopedRepository._require_scope(scope)` before touching the session | The protocol passes a `ScopeContext` per call, but the filters are built from the scope the repository was constructed with. Nothing reconciled the two, so a caller passing a different scope would silently query the bound one — and ruff flagged all 15 `scope` parameters as unused, which is the same fact stated as a lint. `_require_scope` delegates to `ScopeContext.require_ownership`, raising `ScopeViolationError` on any mismatch. The alternative considered and rejected was a per-file `ARG002` ignore, which would have left the parameter decorative. |
| A-233 | correction | `Model.__table__` is typed `FromClause`; `create_all(tables=...)` requires `Table` | Passing `__table__` directly is a type error under both mypy and Pyrefly even though it works at runtime. The `sqlite_session` fixture now looks each table up as `Base.metadata.tables[Model.__tablename__]`, which is typed `Table` and keeps the model imports load-bearing. |
| A-234 | correction | An async fixture is annotated with what it yields, not what it returns | `sqlite_session` was annotated `-> AsyncSession`; because it yields, the correct annotation is `AsyncIterator[AsyncSession]`, matching `get_session` in `session.py`. The wrong annotation failed `pytest_asyncio.fixture`'s overload resolution. |
| A-235 | correction | `Delete` is exported from the `sqlalchemy` namespace | `test_uses_delete_statement` reached it as `sa.sql.dml.Delete`, relying on a submodule another import happened to load. Imported as `from sqlalchemy import Delete` instead. |

### Step 2.11 entries

| ID | Kind | Summary | Detail |
|---|---|---|---|
| A-236 | choice | `SqlJobRepository` does not inherit from `ScopedRepository` | Worker methods (`get`, `save`, `claim_next`) have no `ScopeContext`; scoped construction would require it at build time. Plain class with just `AsyncSession` in its constructor. `list_for_scope` filters through JSONB payload access. |
| A-237 | choice | `list_for_scope` filters via `payload["knowledge_base_id"].as_string()` JSONB access | `ProcessingJobModel` has no `user_id` or `knowledge_base_id` columns; the KB id lives in the JSONB payload. SQLAlchemy's JSONB subscript API produces the correct PostgreSQL expression. PostgreSQL-specific; all job tests use `AsyncMock`. |
| A-238 | choice | `claim_next` reads `now` from `datetime.now(UTC)` internally rather than accepting it as a parameter | The protocol does not include a `now` parameter. The method stamps the claim atomically from inside the same transaction. Determinism in tests is achieved by mocking `session.execute` to return a pre-built pending model; the claim timestamp is not asserted. |
| A-239 | choice | `graph_version=1` set explicitly in `_entity_to_model` and `_rel_to_model` | The domain entities carry no `graph_version` field, so the repository cannot preserve the current DB value on update. Bumping the version is responsibility of the extraction pipeline, not the repository. Setting to 1 explicitly is safe for the current phase because no version management is wired yet. |
| A-240 | choice | `GraphRepository.delete_for_document` deletes graph_entities only; relationships cascade | The FK on `graph_relationships.source_entity_id` and `.target_entity_id` both carry `ondelete="CASCADE"`. One DELETE on `graph_entities WHERE source_document_id = ?` is enough; the DB removes orphaned relationships automatically. |
| A-241 | choice | SQLite tests for graph include `source_chunk_id` as a random UUID with no backing chunks row | SQLite does not enforce FK constraints by default (no `PRAGMA foreign_keys = ON`). The graph tables declare FKs to `chunks`, but `chunks` is not in the SQLite fixture because it uses `pgvector.Vector`. Random UUIDs satisfy the NOT NULL constraint without referential integrity. |
| A-242 | deviation | `pgvector` and `aiosqlite` needed to be installed manually before tests ran | Both packages were listed as dependencies (`pgvector>=0.4` in main, `aiosqlite>=0.20` in dev) but were absent from the active environment. Installed via `pip install pgvector aiosqlite` to unblock the test run. |
| A-243 | choice | `sqlite_session` fixture extended in-place rather than creating per-file fixtures | The eight SQLite-compatible tables share FK relationships (conversations → knowledge_bases, messages → conversations, graph_entities → knowledge_bases). One fixture that creates all eight avoids duplicating FK-ordered table lists across files and keeps test file preambles short. |
