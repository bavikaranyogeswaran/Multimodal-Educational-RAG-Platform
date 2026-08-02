# Use Cases

What a student can do, expressed as flows with testable acceptance criteria.

Each use case names the requirements it exercises (see [REQUIREMENTS.md](REQUIREMENTS.md)), the API
surface it touches, and the phase that delivers it (see [PLAN.md](PLAN.md)). Acceptance criteria are
written to be executable as tests, not read as prose.

## Conventions

- **`KB`** abbreviates `/api/v1/knowledge-bases/{kb_id}` in endpoint references.
- **Main flow** is the successful path. **Alternate flows** are valid variations. **Exception
  flows** are failures that must be handled rather than crash.
- Every use case has an implicit precondition — *the student is authenticated and owns the
  Knowledge Base* — enforced by `FR-AUTH-04` and `NFR-SEC-04`. It is restated only where a flow
  turns on it.
- Acceptance criteria marked **GATE** enforce a zero-tolerance release gate (`NFR-GATE-01` … `06`).

## Index

| UC | Title | Phase |
|---|---|---|
| [UC-01](#uc-01--sign-in) | Sign in | 3 |
| [UC-02](#uc-02--create-a-knowledge-base) | Create a Knowledge Base | 3 |
| [UC-03](#uc-03--manage-knowledge-bases) | Manage Knowledge Bases | 3 |
| [UC-04](#uc-04--upload-a-document) | Upload a document | 4 |
| [UC-05](#uc-05--monitor-document-processing) | Monitor document processing | 4 |
| [UC-06](#uc-06--inspect-extracted-tables-and-figures) | Inspect extracted tables and figures | 6 |
| [UC-07](#uc-07--ask-a-grounded-question) | Ask a grounded question | 11 |
| [UC-08](#uc-08--ask-about-a-selected-table-or-figure) | Ask about a selected table or figure | 11 |
| [UC-09](#uc-09--receive-an-abstention) | Receive an abstention | 11 |
| [UC-10](#uc-10--compare-across-documents) | Compare across documents | 13 |
| [UC-11](#uc-11--ask-a-question-with-conflicting-sources) | Ask a question with conflicting sources | 13 |
| [UC-12](#uc-12--resume-a-long-dormant-conversation) | Resume a long-dormant conversation | 14 |
| [UC-13](#uc-13--correct-a-stored-fact) | Correct a stored fact | 14 |
| [UC-14](#uc-14--review-and-delete-memories) | Review and delete memories | 14 |
| [UC-15](#uc-15--generate-a-summary) | Generate a summary | 15 |
| [UC-16](#uc-16--take-a-quiz) | Take a quiz | 15 |
| [UC-17](#uc-17--review-flashcards) | Review flashcards | 15 |
| [UC-18](#uc-18--build-a-study-plan) | Build a study plan | 15 |
| [UC-19](#uc-19--track-learning-progress) | Track learning progress | 15 |
| [UC-20](#uc-20--delete-a-document) | Delete a document | 16 |
| [UC-21](#uc-21--delete-a-knowledge-base) | Delete a Knowledge Base | 16 |
| [UC-22](#uc-22--navigate-a-citation-to-its-source) | Navigate a citation to its source | 19 |
| [UC-23](#uc-23--ask-a-relationship-or-prerequisite-question) | Ask a relationship or prerequisite question | 12 |
| [UC-24](#uc-24--explore-the-concept-graph) | Explore the concept graph | 12, 20 |

---

## UC-01 — Sign in

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 3, 18 |
| **Requirements** | FR-AUTH-01, FR-AUTH-02, FR-AUTH-03, FR-AUTH-12, NFR-SEC-04 |
| **API** | Supabase Auth; all `KB` routes thereafter |

**Preconditions** — The student has a Supabase Auth account.

**Main flow**
1. Student submits credentials to Supabase Auth.
2. Supabase returns an access token and refresh token.
3. Frontend stores the session and attaches the access token to subsequent requests.
4. Backend verifies the token signature and expiry on each request.
5. Backend resolves `user_id` from verified claims.

**Alternate flows**
- **A1** Session expired but refresh token valid → frontend refreshes silently, request proceeds.

**Exception flows**
- **E1** Invalid credentials → 401, no session created, no detail about which field was wrong.
- **E2** Expired or malformed token → 401; the request MUST NOT proceed with a partially resolved
  identity.

**Postconditions** — An authenticated session exists; `user_id` is resolvable on every request.

**Acceptance criteria**
- [ ] A request with no token, an expired token, or a token signed by another key is rejected.
- [ ] `user_id` is never read from a request body, query parameter or header.
- [ ] No teacher, administrator or moderator role exists or can be assigned (`FR-AUTH-12`).

---

## UC-02 — Create a Knowledge Base

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 3, 18 |
| **Requirements** | FR-OBJ-01, FR-KB-02, FR-KB-03, FR-KB-05 |
| **API** | `POST KB` |

**Preconditions** — Authenticated.

**Main flow**
1. Student supplies name, and optionally description, subject, learning goal, preferred language,
   explanation level and exam date.
2. Student chooses whether to enable concept-graph extraction.
3. Backend creates the Knowledge Base owned by the authenticated user, with
   `active_index_version` and `active_graph_version` initialised.
4. Backend returns the created Knowledge Base.

**Alternate flows**
- **A1** Graph extraction left disabled → Knowledge Base is fully functional; the offer remains
  visible so the capability is discoverable (`ADR-0008` consequence).

**Exception flows**
- **E1** Missing name → 422 with a field-level message.

**Postconditions** — An empty Knowledge Base exists, owned by the student.

**Acceptance criteria**
- [ ] The created record carries the authenticated `user_id`, not a client-supplied one.
- [ ] `graph_enabled` defaults to disabled and is settable at creation.
- [ ] A student cannot create a Knowledge Base owned by another user.

---

## UC-03 — Manage Knowledge Bases

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 3, 18 |
| **Requirements** | FR-KB-05, FR-AUTH-04, FR-AUTH-13, FR-GRA-12, NFR-SEC-13 |
| **API** | `GET KB`, `GET KB`, `PATCH KB`, `DELETE KB` |

**Preconditions** — Authenticated.

**Main flow**
1. Student lists their Knowledge Bases.
2. Student opens one and edits its settings — name, subject, learning goal, explanation level,
   exam date, `graph_enabled`.
3. Backend verifies ownership, applies the change and returns the updated record.

**Alternate flows**
- **A1** Student enables `graph_enabled` on a Knowledge Base with existing documents → a backfill
  job is enqueued for those documents (`FR-GRA-12`).
- **A2** Student disables `graph_enabled` → existing graph data is retained; no new extraction runs.

**Exception flows**
- **E1** Knowledge Base belongs to another user → **404, not 403**, so existence is not disclosed
  (`FR-AUTH-13`, `NFR-SEC-13`).

**Postconditions** — Settings are updated; any backfill is queued.

**Acceptance criteria**
- [ ] The list returns only Knowledge Bases owned by the requester. **GATE** (`NFR-GATE-01`)
- [ ] A request for another user's Knowledge Base returns 404 with no distinguishing detail.
- [ ] Enabling `graph_enabled` enqueues backfill exactly once, and re-enabling does not duplicate it.

---

## UC-04 — Upload a document

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 4, 18 |
| **Requirements** | FR-OBJ-02, FR-DOC-01 … FR-DOC-08, FR-JOB-07, NFR-SEC-15, NFR-PERF-13 |
| **API** | `POST KB/documents` |

**Preconditions** — Authenticated; Knowledge Base exists and is owned by the student.

**Main flow**
1. Student selects a PDF or image.
2. Frontend performs basic validation — type and size — before transmitting.
3. Backend verifies Knowledge Base ownership.
4. Backend validates the file by magic bytes, size and page count.
5. Backend creates a document record with status `PENDING`.
6. Backend stores the original privately at
   `{user_id}/{knowledge_base_id}/{document_id}/original.pdf`.
7. Backend enqueues a `DOCUMENT_INGESTION` job.
8. Backend returns the document ID and status promptly.

**Alternate flows**
- **A1** Image rather than PDF → same flow; page classification treats it as a single scanned page.

**Exception flows**
- **E1** File type mismatches its magic bytes → 415; nothing is stored, no record is created.
- **E2** File exceeds the size or page-count limit → 413 with the limit stated.
- **E3** Storage write fails → the document record is not left in `PENDING` with no file; the
  operation fails atomically.
- **E4** Upload targets a Knowledge Base the student does not own → 404.

**Postconditions** — Document record exists at `PENDING`; original is stored privately; ingestion
job is queued.

**Acceptance criteria**
- [ ] The response returns before parsing or OCR begins (`NFR-PERF-13` ≤ 1.5 s p95).
- [ ] A file renamed to `.pdf` but not a PDF is rejected by magic-byte validation.
- [ ] The stored object is not publicly readable; access requires a signed URL. **GATE**
- [ ] A failed storage write leaves no orphaned document record.

---

## UC-05 — Monitor document processing

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 4, 5, 18 |
| **Requirements** | FR-DOC-09, FR-DOC-10, FR-DOC-11, FR-IDX-09, NFR-REL-07, NFR-REL-08, NFR-UX-01, NFR-UX-07 |
| **API** | `GET KB/documents/{document_id}/status` |

**Preconditions** — A document exists in `PENDING` or `PROCESSING`.

**Main flow**
1. Frontend polls document status.
2. Backend returns the current status and per-stage progress — pages classified, pages OCR'd,
   tables extracted, visuals extracted, chunks created, embeddings generated, graph built.
3. Status advances `PENDING` → `PROCESSING` → `COMPLETED`.
4. On `COMPLETED`, the document becomes retrievable.

**Alternate flows**
- **A1** `graph_enabled` is off → the graph stage is reported as skipped, not pending.
- **A2** Graph building continues after the document is searchable → the document is usable while
  the graph completes at `BACKGROUND` priority.

**Exception flows**
- **E1** A page fails OCR → the page is recorded as failed, the document continues, and the failure
  is surfaced per page rather than failing the whole document.
- **E2** Ingestion fails irrecoverably → status `FAILED` with a reason the student can act on; no
  partial content is retrievable (`NFR-REL-07`).
- **E3** Worker crashes mid-job → the lease expires, another worker reclaims the job, and processing
  resumes at page granularity rather than restarting (`NFR-REL-08`).

**Postconditions** — Document reaches a terminal status; on `COMPLETED` its content is searchable.

**Acceptance criteria**
- [ ] Content from a document not at `COMPLETED` is never returned by retrieval (`FR-IDX-09`).
- [ ] A killed worker does not strand the job; it is reclaimed and completed.
- [ ] Re-running ingestion on the same document does not duplicate chunks or embeddings
      (`NFR-REL-01`).
- [ ] A `FAILED` document can be reprocessed without re-upload (`FR-DOC-11`).

---

## UC-06 — Inspect extracted tables and figures

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 6, 19 |
| **Requirements** | FR-TBL-01 … FR-TBL-06, FR-VIS-01 … FR-VIS-08, NFR-DAT-05 |
| **API** | `GET KB/documents/{document_id}` |

**Preconditions** — Document is `COMPLETED`.

**Main flow**
1. Student opens a processed document.
2. Frontend lists extracted tables and visual objects with page numbers.
3. Student opens a table and sees its title, caption, headers, rows and units, alongside the
   original crop.
4. Student opens a figure and sees its crop, caption, OCR'd labels and surrounding text.

**Alternate flows**
- **A1** A large table split across row groups → each group displays the repeated title, headers and
  units, so no group is headerless (`FR-TBL-05`).
- **A2** A chart → axis labels, units, legend and visible trend are shown alongside the crop.

**Exception flows**
- **E1** Table extraction confidence is low → the item is shown with its confidence rather than
  hidden, so the student can judge it.

**Postconditions** — None; this is a read.

**Acceptance criteria**
- [ ] Every table and visual object resolves to a document, page and bounding box (`NFR-DAT-05`).
- [ ] No table row group is stored or displayed without its headers and units (`FR-TBL-06`).
- [ ] A generated visual description is labelled as derived, not presented as source text
      (`FR-VIS-07`).

---

## UC-07 — Ask a grounded question

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 9–11, 19 |
| **Requirements** | FR-OBJ-03, FR-OBJ-05, FR-OBJ-10, FR-CNV-05, FR-CNV-08, FR-QRY-01, FR-RET-02, FR-EVD-04, FR-GEN-02 … FR-GEN-12, FR-CIT-01 … FR-CIT-06, FR-VAL-01 … FR-VAL-07 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — At least one document is `COMPLETED`.

**Main flow**
1. Student sends a question in a conversation.
2. Backend authenticates, verifies ownership, and persists the user message **before** generation.
3. Backend loads conversation context and relevant memory.
4. Backend rewrites the question into a standalone retrieval query if it is a follow-up.
5. Backend classifies the query and checks the exact-answer cache.
6. Backend generates bounded query variants where useful.
7. Backend runs scoped dense and keyword retrieval, fuses with RRF, deduplicates and reranks.
8. Backend selects evidence dynamically, expands parents where needed, and compresses extractively.
9. Backend builds structured citations and constructs the prompt.
10. Backend generates the answer through the Model Gateway, streaming tokens.
11. Backend validates schema, citations, grounding and numbers.
12. Backend persists the answer, its citations and model metadata.
13. Student sees prose with inline citation markers.

**Alternate flows**
- **A1** Follow-up referring to earlier context → rewriting resolves the reference; both original and
  rewritten queries are stored (`FR-QRY-02`).
- **A2** Exact quotation or identifier → expansion is skipped (`FR-QRY-07`).
- **A3** Cache hit on an identical question in identical state → the cached answer is returned.
- **A4** Validation returns `REPAIRABLE` → one targeted repair, then return.

**Exception flows**
- **E1** No evidence passes threshold → UC-09.
- **E2** Validation returns `REJECTED` after repair → the answer is not shown; the student is told
  the response could not be verified.
- **E3** Model provider unavailable → an approved fallback, or a clear error. Never a silent
  substitution (`NFR-REL-06`).
- **E4** Client disconnects mid-stream → generation is cancelled (`NFR-PERF-18`).

**Postconditions** — User message and assistant message persisted with citations; conversation state
and rolling summary updated.

**Acceptance criteria**
- [ ] Every factual claim carries at least one citation (`FR-GEN-05`).
- [ ] Every citation resolves to a chunk that was in the model's context for **this** request.
      **GATE** (`NFR-GATE-03`)
- [ ] An answer citing a non-existent or out-of-scope identifier is rejected by validation. **GATE**
- [ ] Retrieval never returns content from another Knowledge Base or user. **GATE**
      (`NFR-GATE-01`, `NFR-GATE-02`)
- [ ] Numbers and units in the answer match the source evidence exactly (`FR-GEN-06`).
- [ ] The user message is persisted even if generation subsequently fails.
- [ ] Time to first token ≤ 2.5 s p95 for a `DIRECT` query (`NFR-PERF-01`).

---

## UC-08 — Ask about a selected table or figure

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 11, 19 |
| **Requirements** | FR-OBJ-04, FR-QRY-05, FR-VIS-06, FR-VIS-07, FR-CNV-07, FR-PRF-08, FR-PRF-09, NFR-PERF-02 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — Document is `COMPLETED` and contains the selected object.

**Main flow**
1. Student selects a table or figure region in the PDF viewer.
2. Frontend records the selection as conversation active state.
3. Student asks a question about it.
4. Backend classifies the query as `TABLE` or `VISUAL` and takes the early-exit path — direct object
   retrieval, skipping graph retrieval and query expansion.
5. For a visual question, backend sends the **actual image crop** with OCR labels, caption, nearby
   text and retrieved evidence to a multimodal model.
6. Backend validates and streams the answer with citations pointing at the selected object.

**Alternate flows**
- **A1** Follow-up such as "why does it flatten?" → rewriting resolves the pronoun against the active
  selection (`FR-CNV-07`).
- **A2** Table question → structured table JSON is used rather than an image.

**Exception flows**
- **E1** Selected region matches no extracted object → the system falls back to page-level retrieval
  and says which page it used, rather than inventing an object.
- **E2** No multimodal model is configured or permitted for this provider → a clear capability error;
  the system does not silently answer from the text description alone.

**Postconditions** — Conversation active object updated; answer persisted with a citation to the
object.

**Acceptance criteria**
- [ ] A visual question sends the real crop, not only the stored description (`FR-VIS-06`).
- [ ] The stored description alone is never treated as the sole source of truth (`FR-VIS-07`).
- [ ] Graph retrieval and query expansion do not run on this path (`FR-PRF-08`, `FR-PRF-09`).
- [ ] Time to first token ≤ 2.0 s p95 (`NFR-PERF-02`).

---

## UC-09 — Receive an abstention

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 11, 19 |
| **Requirements** | FR-OBJ-10, FR-GEN-08, FR-VAL-05, NFR-REL-10, NFR-UX-02 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — Student asks something the corpus does not answer.

**Main flow**
1. Retrieval returns no candidate above threshold, or validation classifies claims as
   `NOT_SUPPORTED`.
2. Backend produces a response with `insufficient_evidence = true`.
3. Frontend renders it **visually distinct** from an ordinary answer.
4. The response states what was searched and suggests narrowing or uploading material.

**Alternate flows**
- **A1** Partial evidence exists → the supported part is answered with citations and the unsupported
  part is named explicitly, rather than the whole answer being withheld.

**Exception flows**
- **E1** The model answers anyway from parametric knowledge → validation classifies the claims as
  unsupported and the answer is rejected or repaired.

**Postconditions** — The exchange is persisted as an abstention, not an error.

**Acceptance criteria**
- [ ] An abstention is a normal outcome — not an HTTP error, not a retry (`NFR-REL-10`).
- [ ] An abstention is visually distinguishable from an answer (`NFR-UX-02`).
- [ ] A question whose answer is absent from the corpus but present in model training data produces
      an abstention, not a confident answer.

---

## UC-10 — Compare across documents

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 13, 19 |
| **Requirements** | FR-HOP-01 … FR-HOP-09, NFR-PERF-04, NFR-PERF-05, NFR-PERF-06, NFR-REL-05 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — At least two documents are `COMPLETED`.

**Main flow**
1. Student asks a question requiring several documents.
2. Backend classifies it as `MULTI_DOCUMENT`, `COMPARISON`, `AGGREGATION` or `MULTI_HOP`.
3. Backend decomposes it into dependency-aware sub-questions.
4. Backend selects likely documents, then retrieves precise chunks within them.
5. Backend runs the full pipeline per sub-question.
6. Backend classifies coverage and re-retrieves only for unmet sub-questions.
7. Backend selects evidence optimising jointly for sub-question and document coverage.
8. Backend generates cited sub-answers, then synthesizes a final answer preserving original
   citations.
9. Backend validates completeness and bridge claims.

**Alternate flows**
- **A1** Coverage complete after one round → no further retrieval.
- **A2** Progress events stream during decomposition and retrieval so the interface is not silent.

**Exception flows**
- **E1** A sub-question remains `UNSUPPORTED` after the round limit → the final answer names the gap
  explicitly rather than papering over it.
- **E2** Round or sub-question limit reached → retrieval terminates; the answer reflects what was
  found (`NFR-REL-05`).

**Postconditions** — Answer persisted with citations traceable to their original documents.

**Acceptance criteria**
- [ ] Retrieval terminates within 3 rounds and 8 sub-questions regardless of coverage
      (`FR-HOP-07`).
- [ ] Citations in the synthesized answer resolve to the original source chunks, not to sub-answers.
- [ ] First progress event ≤ 1 s p95; complete answer ≤ 30 s p95 (`NFR-PERF-04`, `NFR-PERF-06`).

---

## UC-11 — Ask a question with conflicting sources

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 13, 19 |
| **Requirements** | FR-HOP-05, FR-HOP-10, FR-VAL-03, NFR-UX-03 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — Two documents state different things about the same point.

**Main flow**
1. Student asks about the point.
2. Retrieval surfaces evidence from both documents.
3. Coverage classification marks the evidence `CONFLICTING`.
4. Generation presents both positions with their citations and states that the sources disagree.
5. Frontend renders the disagreement as a conflict rather than resolving it.

**Alternate flows**
- **A1** One source is clearly more recent and says so in-document → the difference is noted, but the
  system still does not silently discard the other.

**Exception flows**
- **E1** The model blends the two into a false consensus → validation detects contradiction between
  the answer and at least one cited source and triggers repair.

**Postconditions** — Answer persisted showing both positions with separate citations.

**Acceptance criteria**
- [ ] Conflicting sources are reported explicitly and never averaged or blended (`FR-HOP-10`).
- [ ] Both positions carry their own citations.
- [ ] The interface presents the conflict rather than picking a winner (`NFR-UX-03`).

---

## UC-12 — Resume a long-dormant conversation

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 14, 19 |
| **Requirements** | FR-OBJ-06, FR-MEM-01 … FR-MEM-09, FR-MEM-14 … FR-MEM-19, NFR-PERF-08 |
| **API** | `GET KB/conversations/{conversation_id}`, `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — A conversation exists with substantial history, some of it compacted into
episodes and durable facts.

**Main flow**
1. Student reopens a conversation after weeks.
2. Backend loads Tier 0 active state, Tier 1 recent raw turns and the Tier 2 rolling summary.
3. Student asks a question referring to something discussed long ago.
4. Backend performs exact structured-fact lookup, then dense and keyword memory search, fuses with
   RRF, reranks and resolves conflicts.
5. Relevant historical memory joins the context; the full history does not.
6. The answer reflects the earlier discussion without re-reading every message.

**Alternate flows**
- **A1** The reference is to an exact identifier such as an exam date → keyed lookup, not semantic
  search (`FR-MEM-19`).
- **A2** Thresholds are crossed during the session → compaction runs afterwards, not mid-turn.

**Exception flows**
- **E1** A retrieved memory is `SUPERSEDED` → it is excluded; only `ACTIVE` memory enters context.
- **E2** No relevant memory found → the turn proceeds on document evidence alone.

**Postconditions** — Conversation continues coherently; compaction may be queued.

**Acceptance criteria**
- [ ] Full message history is never placed into the prompt (`FR-MEM-01`).
- [ ] Original messages remain intact after compaction (`FR-MEM-16`, `NFR-DAT-09`).
- [ ] Memory retrieval is scoped to `user_id`, `knowledge_base_id` and `ACTIVE`. **GATE**
      (`NFR-GATE-02`)
- [ ] Memory retrieval ≤ 250 ms p95 (`NFR-PERF-08`).
- [ ] Conversation memory and document evidence are retrieved from separate indexes
      (`FR-MEM-09`).

---

## UC-13 — Correct a stored fact

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 14 |
| **Requirements** | FR-MEM-10, FR-MEM-11, FR-MEM-12, FR-MEM-13, NFR-DAT-10 |
| **API** | `POST KB/conversations/{conversation_id}/stream`, `PATCH KB/memory/{memory_id}` |

**Preconditions** — A durable fact is stored — for example an exam date.

**Main flow**
1. Student states a correction, in conversation or through the memory interface.
2. Backend recognises the conflict with the existing fact.
3. The existing record is marked `SUPERSEDED`; a new record is created `ACTIVE`.
4. Both records retain provenance and validity dates.
5. Subsequent turns use the corrected value.

**Alternate flows**
- **A1** The assistant inferred the original value rather than being told it → the correction wins
  outright; assistant inference ranks lowest (`FR-MEM-11`).
- **A2** The correction is ambiguous → the record is marked `DISPUTED` rather than guessed at.

**Exception flows**
- **E1** Instructions embedded in an uploaded document attempt to write memory → ignored. Document
  text is untrusted data (`NFR-SEC-07`). **GATE**

**Postconditions** — Old record `SUPERSEDED` and retained; new record `ACTIVE`.

**Acceptance criteria**
- [ ] The superseded record is retained with status, not overwritten (`NFR-DAT-10`).
- [ ] A recent explicit user correction outranks an earlier statement and any assistant inference.
- [ ] Assistant guesses are never stored as confirmed facts (`FR-MEM-12`).
- [ ] Text inside a PDF cannot cause a memory write. **GATE**

---

## UC-14 — Review and delete memories

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 14, 20 |
| **Requirements** | FR-MEM-20, FR-MEM-10, NFR-PRV-07, NFR-GATE-04 |
| **API** | `GET KB/memory`, `PATCH KB/memory/{memory_id}`, `DELETE KB/memory/{memory_id}` |

**Preconditions** — Durable memories exist.

**Main flow**
1. Student opens memory management.
2. Frontend lists durable facts with type, key, value, status and source message.
3. Student edits, supersedes or deletes a record.
4. Backend applies the change and reindexes memory retrieval.

**Alternate flows**
- **A1** Student opens the source message a memory was derived from.
- **A2** Student browses episodes and their summaries.

**Exception flows**
- **E1** Deleting a memory another is derived from → the derived summary is rebuilt rather than left
  referring to deleted content.

**Postconditions** — Memory state reflects the student's edits.

**Acceptance criteria**
- [ ] A deleted memory is never returned by retrieval through any path. **GATE** (`NFR-GATE-04`)
- [ ] Deletion is complete, not a soft flag that leaves the record retrievable (`NFR-PRV-07`).
- [ ] Every listed memory shows its provenance.

---

## UC-15 — Generate a summary

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 15, 20 |
| **Requirements** | FR-OBJ-07, FR-STU-01, FR-STU-02, FR-VAL-08 |
| **API** | `POST KB/summaries`, `GET KB/summaries` |

**Preconditions** — At least one document is `COMPLETED`.

**Main flow**
1. Student selects scope — document, chapter or section — and a summary type.
2. Backend retrieves the relevant parent sections.
3. Backend generates the summary, batching where the scope is large.
4. Backend validates the output against the standard validators.
5. Summary is persisted with citations and returned.

**Alternate flows**
- **A1** Scope exceeds a single context window → batched generation, then a consolidation pass that
  preserves citations from each batch.
- **A2** Type is a formula list or definitions → output is structured rather than prose.

**Exception flows**
- **E1** Validation fails after one repair → the summary is not persisted and the student is told.

**Postconditions** — Summary persisted with citations, retrievable later.

**Acceptance criteria**
- [ ] Summaries retain citations to source sections (`FR-STU-02`).
- [ ] A batched summary's citations resolve to the correct original sections.
- [ ] Generated content passes the same validators as answers (`FR-VAL-08`).

---

## UC-16 — Take a quiz

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 15, 20 |
| **Requirements** | FR-OBJ-07, FR-STU-03, FR-STU-04, FR-STU-05, FR-PRG-01 |
| **API** | `POST KB/quizzes`, `GET KB/quizzes/{quiz_id}`, `POST KB/quizzes/{quiz_id}/attempts` |

**Preconditions** — At least one document is `COMPLETED`.

**Main flow**
1. Student requests a quiz over a scope, optionally choosing question types and difficulty.
2. Backend generates structured questions, each carrying `source_chunk_id`, `document_id` and
   `page_number`.
3. Backend validates the quiz schema and that each answer is supported by its cited source.
4. Student answers the questions.
5. Backend scores the attempt **deterministically in application code**.
6. Student sees the score, explanations and links to source pages.
7. Learning progress and weak topics are updated.

**Alternate flows**
- **A1** Chart or table interpretation questions → the crop is shown with the question.
- **A2** Incorrect answers → the concepts are queued as flashcard candidates (`FR-STU-06`).

**Exception flows**
- **E1** A generated question's answer is not entailed by its cited source → the question is dropped
  before the quiz is shown.

**Postconditions** — Attempt recorded; progress and weak topics updated.

**Acceptance criteria**
- [ ] Scoring is deterministic and does not involve a model (`FR-STU-05`).
- [ ] Every question resolves to a source chunk, document and page.
- [ ] Repeating an identical attempt yields an identical score.

---

## UC-17 — Review flashcards

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 15, 20 |
| **Requirements** | FR-OBJ-07, FR-STU-06, FR-STU-07, FR-PRG-01 |
| **API** | `POST KB/flashcards`, `GET KB/flashcards`, `POST KB/flashcards/{card_id}/reviews` |

**Preconditions** — Definitions, key concepts, weak topics or incorrect quiz answers exist.

**Main flow**
1. Student generates or opens a deck.
2. Cards are drawn from definitions, key concepts, weak topics and previously incorrect answers.
3. Student reviews cards and records recall outcomes.
4. Review history is persisted and feeds weak-topic tracking.

**Alternate flows**
- **A1** Student opens a card's source page to re-read the material.

**Exception flows**
- **E1** A source chunk is deleted → affected cards are removed or marked orphaned rather than left
  citing nothing.

**Postconditions** — Review history recorded; weak topics updated.

**Acceptance criteria**
- [ ] Every card retains source provenance (`FR-STU-07`).
- [ ] Incorrect quiz answers produce flashcard candidates.
- [ ] Deleting a source document leaves no card citing deleted content (`NFR-DAT-06`).

---

## UC-18 — Build a study plan

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 15, 20 |
| **Requirements** | FR-OBJ-07, FR-STU-08, FR-STU-09 |
| **API** | `POST KB/study-plans`, `GET KB/study-plans`, `PATCH KB/study-plans/{plan_id}/tasks/{task_id}` |

**Preconditions** — At least one document is `COMPLETED`; the student knows their exam date and
available hours.

**Main flow**
1. Student supplies exam date, available hours per week, chapters to cover and priority topics.
2. **Application code** computes the schedule — dates, workload distribution, sequencing.
3. The model phrases each task in readable language, and does nothing else.
4. Plan and tasks are persisted and displayed as a schedule.
5. Student marks tasks complete as they progress.

**Alternate flows**
- **A1** Weak topics exist from quiz history → they are weighted more heavily in the schedule.
- **A2** Exam date changes → the schedule is recomputed; completed tasks are preserved.

**Exception flows**
- **E1** Available hours are insufficient for the scope → the plan states the shortfall rather than
  silently compressing the workload into an impossible schedule.

**Postconditions** — Study plan and tasks persisted.

**Acceptance criteria**
- [ ] Dates and workload are computed in application code, never by the model (`FR-STU-09`).
- [ ] Identical inputs produce an identical schedule.
- [ ] Changing the exam date recomputes future tasks without discarding completed ones.

---

## UC-19 — Track learning progress

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 15, 20 |
| **Requirements** | FR-OBJ-09, FR-PRG-01, FR-PRG-02 |
| **API** | `GET KB/progress` |

**Preconditions** — Quiz attempts, flashcard reviews or completed study tasks exist.

**Main flow**
1. Student opens the progress dashboard.
2. Backend returns structured data — topic mastery, quiz performance, flashcard review history,
   completed chapters, weak concepts, study-plan completion, last review date.
3. Frontend visualises mastery and highlights weak topics.

**Alternate flows**
- **A1** Student drills from a weak topic straight into a targeted quiz or flashcard deck.

**Exception flows**
- **E1** No activity yet → an empty state that explains how progress accumulates, not a blank page.

**Postconditions** — None; this is a read.

**Acceptance criteria**
- [ ] Progress is computed from structured tables, never from a prose conversation summary
      (`FR-PRG-02`).
- [ ] Weak topics derive from actual quiz and flashcard outcomes.

---

## UC-20 — Delete a document

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 16, 18 |
| **Requirements** | FR-DEL-01 … FR-DEL-04, FR-DEL-06, NFR-DAT-06, NFR-DAT-07, NFR-SEC-11 |
| **API** | `DELETE KB/documents/{document_id}` |

**Preconditions** — Document exists and is owned by the student.

**Main flow**
1. Student confirms deletion.
2. Backend verifies ownership and marks the document `DELETING`.
3. **Retrieval is blocked immediately.**
4. A `DELETE_DOCUMENT` job removes storage files, chunks and embeddings, tables and visuals, and
   document-supported graph edges.
5. Graph entities still supported by other documents are preserved.
6. Index version is incremented and caches are invalidated.
7. The document record is deleted.

**Alternate flows**
- **A1** Document is mid-ingestion → in-flight jobs are cancelled before deletion proceeds.

**Exception flows**
- **E1** Deletion interrupted partway → the job is idempotent and resumes to a terminal state
  (`NFR-REL-09`).
- **E2** Storage delete fails → the job retries; the document is not marked deleted while files
  remain.

**Postconditions** — All content and derived data for the document are gone; shared graph entities
survive.

**Acceptance criteria**
- [ ] Content is unreachable from the moment `DELETING` is set, before the job completes
      (`NFR-SEC-11`). **GATE**
- [ ] No orphaned chunks, embeddings, citations, graph edges or crops remain (`NFR-DAT-06`).
- [ ] Graph entities supported by another document are not deleted (`NFR-DAT-07`).
- [ ] Cached answers citing the document are invalidated. **GATE** (`NFR-GATE-05`)
- [ ] Re-running the deletion job is safe.

---

## UC-21 — Delete a Knowledge Base

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 16, 18 |
| **Requirements** | FR-DEL-05, FR-DEL-06, NFR-PRV-05, NFR-PRV-07 |
| **API** | `DELETE KB` |

**Preconditions** — Knowledge Base exists and is owned by the student.

**Main flow**
1. Student confirms deletion, acknowledging it is irreversible.
2. Backend marks the Knowledge Base deleting and blocks retrieval.
3. A `DELETE_KNOWLEDGE_BASE` job recursively removes documents, conversations, memories, generated
   study content, graph data, storage files, embeddings and caches.
4. The Knowledge Base record is deleted.

**Alternate flows**
- **A1** Jobs are in flight for the Knowledge Base → they are cancelled before deletion proceeds.

**Exception flows**
- **E1** Interrupted → resumes idempotently to a terminal state.

**Postconditions** — Nothing belonging to the Knowledge Base remains in any store.

**Acceptance criteria**
- [ ] Derived data is removed alongside canonical data — embeddings, full-text vectors, graph edges,
      cached answers, crops, memory (`NFR-PRV-05`).
- [ ] No content is retrievable after deletion, through any path. **GATE** (`NFR-GATE-04`)
- [ ] Other Knowledge Bases owned by the same student are unaffected.

---

## UC-22 — Navigate a citation to its source

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 19 |
| **Requirements** | FR-CIT-05, FR-ING-21, NFR-UX-04 |
| **API** | `GET KB/documents/{document_id}` |

**Preconditions** — An answer with citations is displayed.

**Main flow**
1. Student clicks a citation marker such as `[S1]`.
2. Frontend opens the cited document in the PDF.js viewer.
3. Viewer navigates to the cited page.
4. Viewer highlights the cited bounding box.

**Alternate flows**
- **A1** Citation refers to a table or figure → the object's region is highlighted rather than a text
  span.
- **A2** Citation spans pages → the viewer opens at the first page and indicates the span.

**Exception flows**
- **E1** The source document was deleted since the answer was generated → the student is told the
  source is no longer available; the viewer does not open a blank document.
- **E2** Signed URL expired → a fresh URL is requested transparently.

**Postconditions** — None; this is navigation.

**Acceptance criteria**
- [ ] A citation is reachable in one interaction from the claim it supports (`NFR-UX-04`).
- [ ] The highlighted region matches the stored bounding box.
- [ ] A citation to a deleted document degrades gracefully.

---

## UC-23 — Ask a relationship or prerequisite question

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 12, 19 |
| **Requirements** | FR-OBJ-08, FR-QRY-05, FR-RET-12 … FR-RET-16, FR-GRA-13, NFR-GATE-06 |
| **API** | `POST KB/conversations/{conversation_id}/stream` |

**Preconditions** — `graph_enabled` is set and graph building has completed for at least one
document.

**Main flow**
1. Student asks a relationship-shaped question — "what do I need to understand before this?",
   "where else is this discussed?", "how does this relate to that?".
2. Backend classifies it as `RELATIONSHIP`, `PREREQUISITE` or `CONCEPT_MAP`.
3. Backend extracts candidate entities and resolves them to canonical graph nodes.
4. Backend runs one-hop traversal, collecting edges and their source chunk IDs.
5. Backend **loads the original evidence passages** for those edges.
6. Graph results form a ranked list fused with dense and keyword results via RRF.
7. Answer is generated citing the source passages, not the triples.

**Alternate flows**
- **A1** `graph_enabled` is off → the question is answered through ordinary retrieval, and the
  student is offered graph extraction.
- **A2** Entities do not resolve to graph nodes → the query falls back to standard retrieval.

**Exception flows**
- **E1** Graph building has not finished → the question is answered from available retrieval, and
  the partial graph state is disclosed rather than silently producing a thin answer.

**Postconditions** — Answer persisted with citations to source passages.

**Acceptance criteria**
- [ ] Graph triples alone are never presented as evidence; the source passage is retrieved and cited
      (`FR-RET-16`).
- [ ] Traversal is scoped by `user_id` and `knowledge_base_id`. **GATE** (`NFR-GATE-02`)
- [ ] Every edge used carries provenance. **GATE** (`NFR-GATE-06`)
- [ ] Graph retrieval supplements rather than replaces dense and keyword retrieval
      (`FR-RET-12`).

---

## UC-24 — Explore the concept graph

| | |
|---|---|
| **Actor** | Student |
| **Phase** | 12, 20 |
| **Requirements** | FR-OBJ-08, FR-VIZ-01 … FR-VIZ-05, NFR-PERF-14, NFR-CAP-04 |
| **API** | `GET KB/graph`, `GET KB/graph/entities/{entity_id}` |

**Preconditions** — `graph_enabled` is set and graph data exists.

**Main flow**
1. Student selects a concept or chapter.
2. Backend returns a bounded set of nodes and edges — approximately 30–50.
3. Cytoscape.js renders the graph.
4. Student clicks a concept and sees its evidence and source page.
5. Student expands one-hop neighbours from a node.
6. Student asks a question about a node, entering UC-23.

**Alternate flows**
- **A1** Student switches to a prerequisite view showing `PREREQUISITE_OF` edges only.
- **A2** Student opens the source page for an edge's evidence, entering UC-22.

**Exception flows**
- **E1** The neighbourhood exceeds the node cap → the most confident edges are returned and the
  truncation is indicated, rather than silently dropping nodes.
- **E2** `graph_enabled` is off or the graph is empty → an empty state offering to enable extraction.

**Postconditions** — None; this is exploration.

**Acceptance criteria**
- [ ] The complete Knowledge Base graph is never rendered at once (`FR-VIZ-03`, `NFR-CAP-04`).
- [ ] Every node exposes its evidence and a link to its source page.
- [ ] Graph query returning ≤ 50 nodes completes in ≤ 500 ms p95 (`NFR-PERF-14`).
- [ ] Nodes and edges from another Knowledge Base never appear. **GATE** (`NFR-GATE-02`)

---

## Coverage of primary objectives

The nine student capabilities in §2, each mapped to the use case that delivers it.

| §2 capability | Use case |
|---|---|
| Create a Knowledge Base for a topic | UC-02 |
| Upload textbooks, notes, papers, revision material | UC-04 |
| Ask questions about uploaded content | UC-07 |
| Select a page, table, diagram, chart or figure | UC-08 |
| Receive an explanation supported by citations | UC-07, UC-22 |
| Continue the conversation over weeks or months | UC-12 |
| Generate summaries, quizzes, flashcards and study plans | UC-15, UC-16, UC-17, UC-18 |
| Explore relationships through a concept graph | UC-23, UC-24 |
| Track weak and completed topics | UC-19 |

## Release gate coverage

Each zero-tolerance gate is exercised by at least one use case.

| Gate | Exercised by |
|---|---|
| NFR-GATE-01 — cross-user leakage | UC-03, UC-04, UC-07 |
| NFR-GATE-02 — cross-Knowledge-Base leakage | UC-07, UC-12, UC-23, UC-24 |
| NFR-GATE-03 — fabricated citation acceptance | UC-07 |
| NFR-GATE-04 — deleted memory retrieval | UC-14, UC-21 |
| NFR-GATE-05 — unauthorized cache reuse | UC-20 |
| NFR-GATE-06 — graph edge without provenance | UC-23 |
