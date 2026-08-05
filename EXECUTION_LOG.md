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
