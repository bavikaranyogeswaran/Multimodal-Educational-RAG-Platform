# Requirements Register

Functional and non-functional requirements for the Multimodal Educational Tutor RAG platform,
extracted from the 68-section system design specification.

> **Status:** complete. Functional requirements (step 0.8) and non-functional requirements with
> release gates (step 0.9). Latency and capacity targets are provisional until measured in Phase 17
> — see [Performance](#performance-nfr).

## Conventions

- **IDs are domain-prefixed** (`FR-RET-04`) rather than flat-numbered, so requirements can be
  inserted without renumbering and so a test or use case referencing one is self-describing.
  IDs are permanent — a withdrawn requirement is marked `WITHDRAWN`, never reused.
- **Spec** traces the requirement to its source section. A requirement with no section reference is
  derived from a recorded decision in [PLAN.md](PLAN.md); its decision ID is given instead.
- **Phase** is the phase that implements it, per [PLAN.md](PLAN.md).
- **MUST** requirements are binding. **SHOULD** requirements are expected but may be deferred with
  a recorded reason. **MUST NOT** requirements are prohibitions and are tested as such.

## Domain index

| Prefix | Domain | Spec sections |
|---|---|---|
| [OBJ](#product-objectives) | Product objectives | §1–§4 |
| [AUTH](#authentication--authorization) | Authentication and authorization | §3, §10 |
| [KB](#knowledge-base) | Knowledge Base | §5, §9 |
| [DOC](#document-upload) | Document upload | §11 |
| [JOB](#background-jobs) | Background jobs | §7, §12 |
| [ING](#ingestion-parsing-classification-and-ocr) | Ingestion, parsing, classification, OCR | §13–§16 |
| [TBL](#table-processing) | Table processing | §17 |
| [VIS](#figure-chart-and-diagram-processing) | Figure, chart, diagram processing | §18 |
| [CHK](#chunking) | Chunking | §19 |
| [IDX](#embedding-and-indexing) | Embedding and indexing | §20 |
| [GRA](#graph-construction-and-storage) | Graph construction and storage | §21, §22 |
| [CNV](#conversations) | Conversations | §23, §41 |
| [QRY](#query-understanding) | Query understanding | §24–§26 |
| [RET](#retrieval-and-ranking) | Retrieval and ranking | §27–§29, §34 |
| [EVD](#evidence-selection) | Evidence selection | §30–§33 |
| [CTX](#context-construction-and-instruction-handling) | Context and instruction handling | §36, §37 |
| [GEN](#grounded-generation) | Grounded generation | §38 |
| [CIT](#citations) | Citations | §40 |
| [VAL](#generation-validation) | Generation validation | §39 |
| [HOP](#multi-hop-and-multi-document-retrieval) | Multi-hop and multi-document retrieval | §35 |
| [MEM](#long-term-memory) | Long-term memory | §42–§45 |
| [STU](#study-content-generation) | Study-content generation | §46 |
| [PRG](#learning-progress) | Learning progress | §47 |
| [MDL](#model-gateway) | Model gateway | §48–§54 |
| [PRF](#performance) | Performance | §55 |
| [CCH](#caching) | Caching | §56 |
| [VIZ](#concept-graph-visualization) | Concept graph visualization | §57 |
| [DEL](#deletion-and-lifecycle) | Deletion and lifecycle | §58 |
| [API](#api-design) | API design | §61 |
| [OBS](#observability) | Observability | §62 |
| [EVL](#evaluation-and-security-testing) | Evaluation and security testing | §63, §64 |
| [UI](#frontend) | Frontend | §7 |

### Non-functional domains

| Prefix | Domain | Spec sections |
|---|---|---|
| [NFR-SEC](#security-nfr) | Security | §5, §10, §64 |
| [NFR-PRV](#privacy-nfr) | Privacy and data boundary | §52, §62 |
| [NFR-PERF](#performance-nfr) | Performance and latency | §55, §62 |
| [NFR-REL](#reliability-nfr) | Reliability | §12, §39, §53, §58 |
| [NFR-DAT](#data-integrity-nfr) | Data integrity | §5, §20, §21, §22 |
| [NFR-OBS](#observability-nfr) | Observability | §62 |
| [NFR-MNT](#maintainability-nfr) | Maintainability | §8, §48, §51 |
| [NFR-POR](#portability-nfr) | Portability | §48, §51, §67 |
| [NFR-CAP](#capacity-nfr) | Capacity | §67 |
| [NFR-UX](#usability-nfr) | Usability and accessibility | §7 |
| [NFR-GATE](#release-gates) | **Release gates — zero tolerance** | §64 |

---

## Product objectives

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-OBJ-01 | A student MUST be able to create a Knowledge Base for a topic. | §2 | 3 |
| FR-OBJ-02 | A student MUST be able to upload textbooks, lecture notes, research papers or revision material. | §2 | 4 |
| FR-OBJ-03 | A student MUST be able to ask questions about uploaded content. | §2 | 11 |
| FR-OBJ-04 | A student MUST be able to select a page, table, diagram, chart or figure and ask about it. | §2 | 19 |
| FR-OBJ-05 | The system MUST return explanations supported by citations. | §2 | 11 |
| FR-OBJ-06 | A student MUST be able to continue a conversation over weeks or months. | §2 | 14 |
| FR-OBJ-07 | A student MUST be able to generate summaries, quizzes, flashcards and study plans. | §2 | 15 |
| FR-OBJ-08 | A student MUST be able to explore relationships through a concept graph. | §2 | 12, 20 |
| FR-OBJ-09 | A student MUST be able to track weak and completed topics. | §2 | 15 |
| FR-OBJ-10 | The system MUST distinguish, in its output, between facts supported by uploaded documents, conversation context used to resolve references, stored user preferences and decisions, model inference, and insufficient evidence. | §2 | 11 |
| FR-OBJ-11 | The system MUST answer from retrieved evidence rather than unsupported model memory. | §2 | 11 |
| FR-OBJ-12 | Orchestration MUST be deterministic. The system MUST NOT implement autonomous agents, agent planning loops, or tool-calling agents. | §4 | all |
| FR-OBJ-13 | The system MUST NOT implement text-to-speech, multi-user collaboration, public document sharing, or institutional dashboards. | §3, §4 | all |
| FR-OBJ-14 | The system MUST NOT run full global GraphRAG over every query. | §4 | 12 |
| FR-OBJ-15 | The default deployment MUST use local language-model inference so private documents need not be sent to external providers. | §1 | 8 |

---

## Authentication and authorization

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-AUTH-01 | Authentication MUST be managed by Supabase Auth. | §10, §65 | 3 |
| FR-AUTH-02 | The backend MUST verify the access token on every authenticated request. | §10 | 3 |
| FR-AUTH-03 | The backend MUST resolve the authenticated `user_id` from the verified token, never from client-supplied data. | §10 | 3 |
| FR-AUTH-04 | The backend MUST check Knowledge Base ownership before any KB-scoped operation. | §10 | 3 |
| FR-AUTH-05 | The validated scope MUST be passed to repositories; repositories MUST NOT be callable without it. | §10 | 1, 2 |
| FR-AUTH-06 | Scope filters MUST be applied inside SQL, vector and graph queries — not applied to results afterwards. | §10 | 2, 9, 12 |
| FR-AUTH-07 | Permission filtering MUST occur before similarity ranking or graph traversal. | §10 | 9, 12 |
| FR-AUTH-08 | PostgreSQL Row-Level Security MUST be enabled on every scoped table. | §10 | 2 |
| FR-AUTH-09 | Original documents and derived crops MUST be stored in private buckets, never public. | §10 | 4 |
| FR-AUTH-10 | File access MUST be granted only through expiring signed URLs. | §10 | 4 |
| FR-AUTH-11 | Citations MUST be authorization-checked against the requesting user and Knowledge Base. | §10, §40 | 11 |
| FR-AUTH-12 | The user-facing product MUST expose only the student role. Teacher, administrator and moderator roles MUST NOT exist. | §3 | 3 |
| FR-AUTH-13 | Access to a Knowledge Base the user does not own SHOULD return not-found rather than forbidden, so existence is not disclosed. | D-01 | 3 |

---

## Knowledge Base

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-KB-01 | A Knowledge Base MUST be the primary organizational, retrieval and security boundary. | §5, §9 | 1, 2 |
| FR-KB-02 | A Knowledge Base MUST store: `id`, `user_id`, `name`, `description`, `subject`, `learning_goal`, `preferred_language`, `explanation_level`, `optional_exam_date`, `active_index_version`, `active_graph_version`, `created_at`, `updated_at`. | §9 | 2 |
| FR-KB-03 | A Knowledge Base MUST additionally carry a `graph_enabled` flag controlling whether graph extraction runs. | D-19 | 2 |
| FR-KB-04 | Every scoped record MUST carry `user_id` and `knowledge_base_id`. This includes documents, pages, elements, chunks, embeddings, tables, figures, graph entities, graph relationships, conversations, messages, memories, summaries, quizzes, flashcards, study plans, progress records and cached results. | §5 | 2 |
| FR-KB-05 | A student MUST be able to create, list, read, update and delete their own Knowledge Bases. | §9, §61 | 3 |
| FR-KB-06 | PostgreSQL MUST be the canonical source of truth. | §5 | 2 |
| FR-KB-07 | All derived data — vector indexes, full-text indexes, graph projection, conversation summaries, embeddings and caches — MUST be rebuildable from canonical records. | §5 | 2, 7, 12 |

---

## Document upload

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-DOC-01 | A student MUST be able to upload a PDF or image into a selected Knowledge Base. | §11 | 4 |
| FR-DOC-02 | The frontend MUST perform basic validation before upload. | §11 | 18 |
| FR-DOC-03 | The backend MUST verify Knowledge Base ownership before accepting an upload. | §11 | 4 |
| FR-DOC-04 | The backend MUST validate file type by magic bytes, not by extension or client-declared MIME type alone. | §11 | 4 |
| FR-DOC-05 | A document record MUST be created before the file is stored. | §11 | 4 |
| FR-DOC-06 | The original file MUST be stored privately at `{user_id}/{knowledge_base_id}/{document_id}/original.pdf`. | §11 | 4 |
| FR-DOC-07 | A processing job MUST be created after successful storage. | §11 | 4 |
| FR-DOC-08 | The upload endpoint MUST return the document ID and status promptly; OCR and indexing MUST continue in the background. | §11 | 4 |
| FR-DOC-09 | Document processing status MUST be one of `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `DELETING`. | §11 | 2, 4 |
| FR-DOC-10 | Document status MUST be queryable, with per-stage progress. | §11, §61 | 4 |
| FR-DOC-11 | A failed document MUST record the failure reason and be re-processable without re-upload. | §12 | 4 |

---

## Background jobs

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-JOB-01 | PostgreSQL MUST act as the job queue. Redis, Celery, Kafka and external brokers MUST NOT be introduced. | §4, §12 | 4 |
| FR-JOB-02 | A job record MUST store `id`, `job_type`, `status`, `priority`, `payload_json`, `attempt_count`, `locked_by`, `locked_at`, `heartbeat_at`, `last_error`, `created_at`, `completed_at`. | §12 | 2 |
| FR-JOB-03 | Job types MUST include `DOCUMENT_INGESTION`, `OCR_PAGE`, `GENERATE_EMBEDDINGS`, `BUILD_GRAPH`, `SYNC_NEO4J`, `COMPACT_MEMORY`, `REBUILD_SUMMARY`, `DELETE_DOCUMENT`, `DELETE_KNOWLEDGE_BASE`. | §12 | 2 |
| FR-JOB-04 | Workers MUST claim jobs using `SELECT … FOR UPDATE SKIP LOCKED`. | §12 | 4 |
| FR-JOB-05 | Job priorities MUST be `INTERACTIVE`, `NORMAL`, `BACKGROUND`, ordered by priority then creation time. | §12 | 4 |
| FR-JOB-06 | Interactive requests MUST take priority over OCR, graph rebuilding and bulk compaction. | §12 | 4 |
| FR-JOB-07 | Workers MUST maintain a heartbeat; expired leases MUST be reclaimable by another worker. | §12 | 4 |
| FR-JOB-08 | Failed jobs MUST be retried with a bounded attempt count and dead-lettered on exhaustion. | §12 | 4 |
| FR-JOB-09 | The API and the worker MUST run as separate processes sharing the same domain and application code, so ingestion does not block chat. | §7 | 4 |
| FR-JOB-10 | Jobs MUST be idempotent — re-running a job MUST NOT duplicate derived records. | §58 | 4, 5 |
| FR-JOB-11 | `SYNC_NEO4J` MUST remain a recognised job type but is a documented no-op while the graph is PostgreSQL-backed. | D-10 | 12 |

---

## Ingestion, parsing, classification and OCR

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-ING-01 | The ingestion pipeline MUST proceed: file validation → page classification → layout-aware parsing → text, table and visual extraction → normalization → hierarchical chunking → embeddings → full-text indexes → graph extraction → mark searchable. | §13 | 5–7 |
| FR-ING-02 | Parsing MUST use `pypdf` for metadata and basic native text, `pdfplumber` for layout, blocks and tables, `pypdfium2` for page and region rendering, and Pillow for image operations. | §14 | 5 |
| FR-ING-03 | OpenCV MUST be used only where preprocessing is genuinely necessary, not as a default dependency of every page. | §14 | 5 |
| FR-ING-04 | PyMuPDF MUST NOT be used, because its licensing may be unsuitable for some distribution models. | §14 | 0 (ADR-001) |
| FR-ING-05 | Pages MUST be classified as native-text, scanned, mixed or complex. | §15 | 5 |
| FR-ING-06 | Native-text pages MUST be processed to text blocks, reading order and bounding boxes without OCR. | §15 | 5 |
| FR-ING-07 | Scanned pages MUST be rendered with `pypdfium2` and processed with PaddleOCR, producing text, boxes and confidence. | §15 | 5 |
| FR-ING-08 | Mixed pages MUST combine native text extraction, separate figure and table extraction, and OCR over visual regions only. | §15 | 5 |
| FR-ING-09 | Primary OCR MUST be self-hosted PaddleOCR, default configuration PP-OCRv6 family. | §14 | 5 |
| FR-ING-10 | Baidu Cloud OCR MUST NOT be the default, because it introduces external data transfer, quotas, pricing exposure, privacy and data-residency concerns. | §14 | 0 (ADR-002) |
| FR-ING-11 | PaddleOCR-VL MUST be available as a fallback for complex layouts. | §14, §15 | 5 |
| FR-ING-12 | PaddleOCR-VL MUST be triggered only for difficult pages — dense tables, formulas, multiple columns, rotated content, complex reading order, or low ordinary OCR confidence. It MUST NOT run on every page. | §15 | 5 |
| FR-ING-13 | Tesseract MAY exist as an emergency fallback but MUST NOT be the primary OCR engine. | §14 | 5 |
| FR-ING-14 | The parser MUST produce structured elements, not flattened text. | §16 | 5 |
| FR-ING-15 | Element types MUST include `HEADING`, `PARAGRAPH`, `LIST`, `TABLE`, `FIGURE`, `CHART`, `DIAGRAM`, `FORMULA`, `CAPTION`. | §16 | 5 |
| FR-ING-16 | Each element MUST store `id`, `user_id`, `knowledge_base_id`, `document_id`, `page_number`, `element_type`, `text`, `bounding_box`, `heading_path`, `reading_order`, `confidence`, `processing_method`, `created_at`. | §16 | 2, 5 |
| FR-ING-17 | Layout preservation MUST prevent table rows mixing with paragraphs, multi-column text being read out of order, captions separating from figures, and headings losing their section hierarchy. | §16 | 5 |
| FR-ING-18 | Text extracted from uploaded documents MUST be marked untrusted at extraction time, so downstream prompt assembly can neutralise embedded instructions. | §38 | 5 |
| FR-ING-19 | Page renders MUST be treated as regenerable cache with a TTL, not as canonical permanent storage. | D-13 | 4, 5 |
| FR-ING-20 | Per-page OCR MUST be independently re-runnable without reprocessing the whole document. | §12 | 5 |
| FR-ING-21 | The frontend MUST use PDF.js for document rendering. | §14, §65 | 19 |

---

## Table processing

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-TBL-01 | Tables MUST be first-class retrievable and citable objects, not inline text. | §17 | 6 |
| FR-TBL-02 | Table processing MUST proceed: detect → extract title and caption → extract headers, rows and units → store the original crop → convert to JSON → convert to Markdown → optionally convert to HTML → create retrieval-oriented text → generate embedding. | §17 | 6 |
| FR-TBL-03 | Each table MUST store the original crop, structured JSON, Markdown, optional HTML, embedding text, caption, surrounding text, page and bounding box, and extraction confidence. | §17 | 2, 6 |
| FR-TBL-04 | Retrieval-oriented table text MUST express column names and per-row values in prose form suitable for embedding. | §17 | 6 |
| FR-TBL-05 | Large tables MUST be split by row group, with each group repeating the table title, column headers, units, relevant row labels and source page. | §17 | 6 |
| FR-TBL-06 | Table rows MUST NOT be embedded without their headers. | §17 | 6 |

---

## Figure, chart and diagram processing

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-VIS-01 | Visual objects MUST be extracted as separate records. | §18 | 6 |
| FR-VIS-02 | Visual processing MUST proceed: extract crop → locate caption → attach surrounding paragraphs → OCR labels → generate factual description → store page and bounding box → link to related chunks and concepts. | §18 | 6 |
| FR-VIS-03 | Chart records MUST be able to store `title`, `chart_type`, `x_axis_label`, `y_axis_label`, `units`, `legend`, `data_labels`, `visible_trend`, `caption`, `ocr_text`, `surrounding_text`, `confidence`. | §18 | 2, 6 |
| FR-VIS-04 | Diagram records MUST be able to store labels, visible components, arrows, visible relationships, caption, surrounding text and confidence. | §18 | 2, 6 |
| FR-VIS-05 | OCR MUST be used to extract visible labels only. It MUST NOT be treated as independently understanding a chart or diagram. | §18 | 6 |
| FR-VIS-06 | For an actual visual question, the system MUST send the real image crop together with OCR labels, caption, nearby text and retrieved evidence to a multimodal model. | §18 | 11 |
| FR-VIS-07 | A previously generated visual description MUST NOT be treated as the sole source of truth. | §18 | 6, 11 |
| FR-VIS-08 | Figure and table numbering present in the document (for example "Figure 4.2") MUST be extracted and stored so it can be referenced and selected. | §18, §40 | 6 |

---

## Chunking

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-CHK-01 | Chunking MUST be layout-aware, semantic and hierarchical. | §19 | 7 |
| FR-CHK-02 | Child chunks MUST target 300–500 tokens, with a maximum of approximately 700 and overlap where necessary. Overlap is configured at 70 tokens (D-29); §19 suggests approximately 50. | §19, D-29 | 7 |
| FR-CHK-03 | Parent chunks MUST target 800–1,500 tokens. | §19 | 7 |
| FR-CHK-04 | Splitting MUST follow the priority: chapter boundary, section boundary, subsection boundary, paragraph boundary, and sentence boundary only when unavoidable. | §19 | 7 |
| FR-CHK-05 | Chunk types MUST include `TEXT`, `TABLE`, `FIGURE`, `CHART`, `DIAGRAM`, `FORMULA`, `DEFINITION`, `EXAMPLE`. | §19 | 7 |
| FR-CHK-06 | Different modalities MUST remain separate chunks but MUST be linked. | §19 | 7 |
| FR-CHK-07 | Chunk metadata MUST include `user_id`, `knowledge_base_id`, `document_id`, `parent_chunk_id`, `page_start`, `page_end`, `chapter`, `section`, `heading_path`, `element_type`, `bounding_box`, `language`, `processing_status`. | §19 | 2, 7 |

---

## Embedding and indexing

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-IDX-01 | The default embedding model MUST be `BAAI/bge-small-en-v1.5`. | §20, §65 | 7 |
| FR-IDX-02 | Embeddings MUST be generated for text child chunks, table structured text, figure and chart descriptions, captions, selected conversation-memory records and episode summaries. | §20 | 7, 14 |
| FR-IDX-03 | PostgreSQL MUST store chunk content, metadata, the pgvector embedding and the full-text search vector. | §20 | 2, 7 |
| FR-IDX-04 | Changing the answer-generation model MUST NOT require re-embedding documents. | §20 | 8 |
| FR-IDX-05 | Changing the embedding model MUST create a new index version. | §20 | 7 |
| FR-IDX-06 | Index versioning MUST record `embedding_model_id`, `embedding_dimension`, `embedding_version` and `active_index_version`. | §20 | 2, 7 |
| FR-IDX-07 | Full-text indexes MUST use `rum` rather than GIN, so lexeme positions are stored and ranking occurs inside the index. | D-12 | 2 |
| FR-IDX-08 | Vector queries MUST always include metadata filters; an unfiltered similarity search MUST NOT be possible through the repository layer. | §59 | 2, 9 |
| FR-IDX-09 | Content MUST NOT be retrievable until its document reaches `COMPLETED`. | §27 | 7 |

---

## Graph construction and storage

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-GRA-01 | Graph building MUST occur after parsing and chunk creation. | §21 | 12 |
| FR-GRA-02 | Graph extraction MUST proceed: parent section → model extracts candidate entities and relationships → output validated → names normalized and deduplicated → canonical records written to PostgreSQL → validated projection synchronized. | §21 | 12 |
| FR-GRA-03 | Node types MUST include `KnowledgeBase`, `Document`, `Chapter`, `Section`, `Concept`, `Figure`, `Table`. | §21 | 12 |
| FR-GRA-04 | Relationship types MUST include `CONTAINS`, `PART_OF`, `DEFINED_IN`, `RELATED_TO`, `PREREQUISITE_OF`, `COMPARES_WITH`, `EXPLAINED_BY`, `SHOWN_IN`, `REFERENCES`. | §21 | 12 |
| FR-GRA-05 | `graph_entities` MUST store `id`, `user_id`, `knowledge_base_id`, `document_id`, `entity_type`, `canonical_name`, `description`, `source_chunk_id`, `page_number`, `confidence`, `graph_version`. | §22 | 2 |
| FR-GRA-06 | `graph_relationships` MUST store `id`, `user_id`, `knowledge_base_id`, `document_id`, `source_entity_id`, `target_entity_id`, `relationship_type`, `evidence`, `source_chunk_id`, `page_number`, `confidence`, `graph_version`. | §21, §22 | 2 |
| FR-GRA-07 | Every graph relationship MUST carry source evidence. Model output MUST NOT be inserted blindly. | §21 | 12 |
| FR-GRA-08 | An edge without provenance MUST be rejected at write time. | §21, §64 | 12 |
| FR-GRA-09 | PostgreSQL MUST be the canonical graph store. | §22 | 2, 12 |
| FR-GRA-10 | The graph MUST support one-hop traversal, relationship retrieval, cross-document discovery and concept-map visualization. | §22 | 12 |
| FR-GRA-11 | Any graph projection MUST be fully rebuildable from PostgreSQL. | §22 | 12 |
| FR-GRA-12 | Graph extraction MUST run only when the Knowledge Base has `graph_enabled` set; enabling it later MUST trigger a backfill job over existing documents. | D-19 | 12 |
| FR-GRA-13 | Graph traversal queries MUST be scoped by `user_id` and `knowledge_base_id` in the same way as all other repository queries. | §10, §64 | 12 |

---

## Conversations

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-CNV-01 | Complete conversation history MUST be retained in PostgreSQL. | §41 | 2, 9 |
| FR-CNV-02 | `conversations` MUST store `id`, `user_id`, `knowledge_base_id`, `title`, `rolling_summary`, `summary_version`, `active_document_id`, `active_page`, `active_figure_id`, `active_table_id`, `created_at`, `updated_at`. | §41 | 2 |
| FR-CNV-03 | `messages` MUST store `id`, `conversation_id`, `user_id`, `knowledge_base_id`, `role`, `content`, `rewritten_query`, `status`, `token_count`, `model_provider`, `model_name`, `prompt_version`, `created_at`. | §41 | 2 |
| FR-CNV-04 | `message_citations` MUST store `message_id`, `chunk_id`, `document_id`, `page_number`, `citation_order`, `evidence_hash`. | §41 | 2 |
| FR-CNV-05 | The user message MUST be stored before model generation begins. | §41 | 9 |
| FR-CNV-06 | Message status MUST be one of `RECEIVED`, `PROCESSING`, `COMPLETED`, `FAILED`. | §41 | 2, 9 |
| FR-CNV-07 | The conversation MUST track active document, page, figure and table so follow-up questions can be resolved against a selection. | §41, §24 | 9 |
| FR-CNV-08 | The question-answer flow MUST follow the §23 order: authenticate → validate ownership → persist user message → load context and memory → rewrite → classify → check cache → expand → retrieve → fuse → deduplicate → rerank → select evidence → expand parents → compress → build citations → generate → validate → repair once → persist → update state → stream. | §23 | 9–11 |
| FR-CNV-09 | A student MUST be able to create, list, rename and delete conversations. | §61 | 9, 19 |

---

## Query understanding

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-QRY-01 | Follow-up questions MUST be rewritten into standalone retrieval queries using conversation context and the active selection. | §24 | 9 |
| FR-QRY-02 | Both the original question and the rewritten retrieval query MUST be stored. | §24 | 9 |
| FR-QRY-03 | Queries MUST be classified into `DIRECT`, `EXACT_TERM`, `TABLE`, `VISUAL`, `RELATIONSHIP`, `PREREQUISITE`, `CONCEPT_MAP`, `COMPARISON`, `MULTI_DOCUMENT`, `MULTI_HOP`, `AGGREGATION`, `SUMMARY`, `QUIZ_GENERATION`. | §25 | 9 |
| FR-QRY-04 | Query routing MUST be deterministic. It MUST NOT be implemented as an agent. | §25 | 9 |
| FR-QRY-05 | Routing MUST direct a selected-table question to direct table lookup, a selected-chart question to the visual fast path, a relationship question to selective Graph RAG, a multi-document question to the multi-hop strategy, and an exact quotation to retrieval without expansion. | §25 | 9 |
| FR-QRY-06 | Multi-query expansion MUST generate 2–3 variants for a maximum of 4 total queries, at temperature 0. | §26 | 9 |
| FR-QRY-07 | Expansion MUST be skipped for exact quotations, exact identifiers, selected tables, selected figures, direct chapter summarization and already-resolved source scopes. | §26 | 9 |
| FR-QRY-08 | HyDE MUST NOT be enabled by default, because generated hypothetical answers can introduce incorrect terminology. | §26 | 0 (ADR-007) |

---

## Retrieval and ranking

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-RET-01 | Each query variant MUST run dense vector retrieval and PostgreSQL full-text retrieval. | §27 | 9 |
| FR-RET-02 | Every retrieval query MUST filter on `user_id`, `knowledge_base_id` and `processing_status = COMPLETED`. | §27 | 9 |
| FR-RET-03 | Optional filters MUST be supported for `document_id`, `chapter`, `section`, `page_number`, `element_type`, `table_id`, `figure_id` and `language`. | §27 | 9 |
| FR-RET-04 | Ranked lists MUST be merged using Reciprocal Rank Fusion, `RRF(d) = Σ 1 / (k + rank_r(d))`. | §28 | 9 |
| FR-RET-05 | The RRF `k` constant MUST default to 60 and MUST be configurable. | §28, D-20 | 0.6, 9 |
| FR-RET-06 | Fusion MUST accept original-query dense, original-query keyword, expanded-query dense, expanded-query keyword, graph, visual and table result lists. | §28 | 9, 12 |
| FR-RET-07 | First-stage retrieval MUST optimize recall, with dense and keyword top-k of 25–30 per query and an RRF candidate pool of 40–60 unique candidates. | §29 | 9 |
| FR-RET-08 | The candidate pool MUST be reranked with `cross-encoder/ms-marco-MiniLM-L6-v2`. | §29, §65 | 9 |
| FR-RET-09 | The reranker MUST evaluate question and candidate evidence together, over approximately 30–50 candidates. | §29 | 9 |
| FR-RET-10 | The reranker MUST receive the resolved standalone question, not every expanded query variant. | §29 | 9 |
| FR-RET-11 | The number of retrieved candidates MUST NOT determine the number of chunks sent to the model. | §5 | 10 |
| FR-RET-12 | Selective Graph RAG MUST be an additional retrieval path, never the default retriever. | §34 | 12 |
| FR-RET-13 | Graph retrieval MUST be used for concept relationships, prerequisites, cross-chapter connections, figure-to-concept links, concept-map requests, related-document discovery, and "where else is this discussed" questions. | §34 | 12 |
| FR-RET-14 | Graph retrieval MUST proceed: extract candidate entities → resolve canonical nodes → one-hop traversal → collect edges and source chunk IDs → load original evidence from PostgreSQL → create graph result list → fuse using RRF. | §34 | 12 |
| FR-RET-15 | Initial traversal depth MUST be one hop. Deeper traversal MUST be added only when evaluation demonstrates a need. | §34 | 12 |
| FR-RET-16 | Graph triples alone MUST NOT be treated as sufficient evidence; the attached source passage MUST be retrieved and presented to the reranker and model. | §34 | 12 |
| FR-RET-17 | Dense and keyword searches across query variants SHOULD run concurrently. | §55 | 9 |

---

## Evidence selection

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-EVD-01 | The system MUST NOT send a fixed number of chunks to the model. | §30 | 10 |
| FR-EVD-02 | Evidence count SHOULD follow: direct factual 1–2, definition 1–3, comparison 2–5, multi-hop coverage-based, selected chart image plus caption plus 1–2 passages. | §30 | 10 |
| FR-EVD-03 | Evidence selection MUST consider reranker score, relative score margin, token budget, evidence diversity, source coverage and modality requirements. | §30 | 10 |
| FR-EVD-04 | Evidence items MUST be at least 1 and at most 8 for ordinary queries. | §30 | 10 |
| FR-EVD-05 | Reranker thresholds MUST NOT be treated as universal constants; they MUST be configurable and calibrated against evaluation data. | §30, D-20 | 0.6, 17 |
| FR-EVD-06 | Before generation, the system MUST remove exact duplicate chunks, strongly overlapping passages, parent-child duplicates, repeated table rows, duplicate visual descriptions and repeated graph evidence. | §31 | 10 |
| FR-EVD-07 | Diversity rules MUST cap child chunks per parent at two, chunks per page at three, and chunks per document at a configured maximum, and SHOULD prefer distinct sources for comparisons. | §31 | 10 |
| FR-EVD-08 | The highest-ranked primary evidence MUST always be preserved through deduplication and diversity filtering. | §31 | 10 |
| FR-EVD-09 | Parent context MUST be loaded only when the child chunk is incomplete — specifically when it begins mid-explanation, contains a pronoun referring to earlier text, is a table needing its caption, is a formula needing its definition, or is a figure needing nearby explanation. | §32 | 10 |
| FR-EVD-10 | Every child chunk MUST NOT be replaced with its full parent by default. | §32 | 10 |
| FR-EVD-11 | Contextual compression MUST prefer extractive sentence selection. | §33 | 10 |
| FR-EVD-12 | Compression MUST preserve negations, conditions, qualifiers, numerical values, units, table headers, figure labels and citation offsets. | §33 | 10 |
| FR-EVD-13 | For tables, compression MUST retain the title, headers, units and relevant rows. | §33 | 10 |
| FR-EVD-14 | For graph evidence, compression MUST retain the relationship, the evidence passage and its provenance. | §33 | 10 |
| FR-EVD-15 | Generative compression MUST be used sparingly and MUST be disabled by default, because it may distort values or weaken citation alignment. | §33 | 10 |

---

## Context construction and instruction handling

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-CTX-01 | The context builder MUST assemble the prompt in the order: system and security policies, task objective, mandatory requirements, active Knowledge Base state, pinned durable memory, relevant historical memory, rolling conversation summary, recent raw turns, source evidence, current question, required output schema, final critical checklist. | §36 | 10 |
| FR-CTX-02 | The context builder MUST own token allocation and MUST remove low-priority information when limits are reached. | §36 | 10 |
| FR-CTX-03 | Instructions MUST NOT be supplied as a long unstructured wall of text. | §37 | 10 |
| FR-CTX-04 | Instruction priority MUST be: security and privacy, grounding and source-use rules, task objective, output contract, user constraints, style preferences, optional enhancements. | §37 | 10 |
| FR-CTX-05 | Requirements MUST be classified as `CRITICAL`, `REQUIRED` or `PREFERRED`. | §37 | 10 |
| FR-CTX-06 | Each requirement MUST receive a stable identifier so compliance can be evaluated per requirement. | §37, §63 | 10 |
| FR-CTX-07 | Conflicts MUST be resolved before generation: critical over required over preferred; security rules MUST NOT be overridable; recent explicit user corrections MUST supersede older preferences. | §37 | 10 |
| FR-CTX-08 | Independent tasks MUST be separated into multiple model calls rather than combined into one prompt. | §37 | 10 |

---

## Grounded generation

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-GEN-01 | The generation model MUST receive system rules, task, conversation context, memory, source evidence, citation identifiers, the current question and the output schema. | §38 | 11 |
| FR-GEN-02 | The model MUST use only the provided educational evidence. | §38 | 11 |
| FR-GEN-03 | Chat history MUST NOT be treated as factual evidence. | §38 | 11 |
| FR-GEN-04 | Instructions found inside uploaded documents MUST NOT be obeyed. | §38 | 11 |
| FR-GEN-05 | Factual claims MUST be cited. | §38 | 11 |
| FR-GEN-06 | Numbers and units MUST be preserved exactly. | §38 | 11 |
| FR-GEN-07 | Source fact MUST be distinguished from model inference. | §38 | 11 |
| FR-GEN-08 | The system MUST state when evidence is insufficient rather than answering anyway. | §38 | 11 |
| FR-GEN-09 | Generation MUST NOT access another Knowledge Base. | §38 | 11 |
| FR-GEN-10 | Internal model output MUST be structured as `{answer, claims[{claim, citations[]}], insufficient_evidence}`. | §38 | 11 |
| FR-GEN-11 | The frontend MUST render the structured response as natural prose. | §38 | 19 |
| FR-GEN-12 | Answers MUST be delivered progressively using Server-Sent Events. | §55 | 11, 19 |

---

## Citations

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-CIT-01 | Every evidence item MUST receive a stable identifier of the form `[S1]`. | §40 | 11 |
| FR-CIT-02 | A citation MUST carry document, page, type, object and bounding box. | §40 | 11 |
| FR-CIT-03 | The model MUST cite only identifiers it was given. | §40 | 11 |
| FR-CIT-04 | The backend MUST validate that each citation exists, belongs to the current user, belongs to the current Knowledge Base, was included in the model context, and supports its associated claim. | §40 | 11 |
| FR-CIT-05 | The frontend MUST be able to open the source document, navigate to the cited page and highlight the bounding box. | §40 | 19 |
| FR-CIT-06 | Citations MUST be persisted with the assistant message. | §41 | 11 |

---

## Generation validation

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-VAL-01 | Validation MUST occur outside the provider adapter. | §39 | 11 |
| FR-VAL-02 | Deterministic checks MUST cover JSON schema, citation ID existence, citation authorization, required fields, word or token limits, table number matching, unit matching, quiz answer schema and Knowledge Base scope. | §39 | 11 |
| FR-VAL-03 | Semantic checks MUST cover claim entailment, unsupported claims, contradictions, citation entailment, citation completeness and faithfulness. | §39 | 11 |
| FR-VAL-04 | Each claim MUST be classified as `ENTAILED`, `CONTRADICTED` or `NOT_SUPPORTED`. | §39 | 11 |
| FR-VAL-05 | Validation MUST produce one of `VALID`, `REPAIRABLE`, `INSUFFICIENT_EVIDENCE`, `REJECTED`. | §39 | 11 |
| FR-VAL-06 | A failed answer MUST receive exactly one targeted repair attempt. Infinite regeneration loops MUST NOT be permitted. | §39 | 11 |
| FR-VAL-07 | An answer MUST NOT be returned merely because it looks plausible. | §5 | 11 |
| FR-VAL-08 | Generated study content MUST pass the same validators before persistence. | §46 | 15 |

---

## Multi-hop and multi-document retrieval

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-HOP-01 | Multi-hop handling MUST trigger on `MULTI_DOCUMENT`, `MULTI_HOP`, `AGGREGATION` and `COMPARISON` classifications. | §35 | 13 |
| FR-HOP-02 | The system MUST create dependency-aware sub-questions carrying a `depends_on` list. | §35 | 13 |
| FR-HOP-03 | Each sub-question MUST receive query expansion, dense search, keyword search, selective graph search, RRF and its own reranking. | §35 | 13 |
| FR-HOP-04 | The system MUST first select likely documents using titles, summaries, metadata, document embeddings, graph links and shared entities, then retrieve precise chunks inside each selected document. | §35 | 13 |
| FR-HOP-05 | Evidence coverage MUST be classified as `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED` or `CONFLICTING`. | §35 | 13 |
| FR-HOP-06 | Only sub-questions with missing evidence MUST trigger another retrieval round. | §35 | 13 |
| FR-HOP-07 | Retrieval MUST be limited to a maximum of 3 rounds and 8 sub-questions, and MUST stop when all required evidence is found or when no new evidence appears. | §35 | 13 |
| FR-HOP-08 | The final evidence set MUST optimize collectively for sub-question coverage, required-document coverage, relevance, provenance, source diversity, low redundancy and token cost. | §35 | 13 |
| FR-HOP-09 | Synthesis MUST generate cited answers per sub-question, synthesize the final answer from supported sub-answers, preserve original source citations, and validate completeness and bridge claims. | §35 | 13 |
| FR-HOP-10 | Conflicting sources MUST be reported explicitly and MUST NOT be blended into false consensus. | §35 | 13 |

---

## Long-term memory

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-MEM-01 | Historical conversation content MUST be stored externally and queried as a database. It MUST NOT be placed into the prompt wholesale. | §42 | 14 |
| FR-MEM-02 | Memory MUST be layered as Tier 0 active state, Tier 1 recent raw turns, Tier 2 current episode summary, Tier 3 retrieved historical episodes, Tier 4 structured durable facts, Tier 5 long-range summaries. | §42 | 14 |
| FR-MEM-03 | All original messages MUST remain the canonical source of truth. | §42 | 14 |
| FR-MEM-04 | Structured durable memory MUST store preferences, decisions, constraints, identifiers, goals, exam dates, selected technologies and weak topics. | §42 | 14 |
| FR-MEM-05 | A durable memory record MUST carry `memory_type`, `key`, a structured `value`, `status`, `source_message_id` and `confidence`. | §42 | 2, 14 |
| FR-MEM-06 | Messages MUST be groupable into meaningful conversation episodes. | §42 | 14 |
| FR-MEM-07 | Summaries MUST be hierarchical: raw messages → episode summaries → monthly summaries → Knowledge Base summary → optional user-level preference summary. | §42 | 14 |
| FR-MEM-08 | Old messages and episode summaries MUST be indexed in pgvector and PostgreSQL full-text search. | §42 | 14 |
| FR-MEM-09 | Conversation-memory retrieval MUST be separate from educational-document retrieval. | §42 | 14 |
| FR-MEM-10 | Memory status MUST be one of `ACTIVE`, `SUPERSEDED`, `DISPUTED`, `UNCONFIRMED`, `EXPIRED`, `DELETED`. | §43 | 2, 14 |
| FR-MEM-11 | Conflict priority MUST be: recent explicit user correction, then verified application event, then earlier user statement, then assistant inference. | §43 | 14 |
| FR-MEM-12 | Assistant guesses MUST NOT be permanently stored as confirmed facts. | §43 | 14 |
| FR-MEM-13 | Every memory MUST include provenance and MAY include `valid_from`, `valid_until`, `last_confirmed_at`, `expires_at` and `source_message_id`. | §43 | 2, 14 |
| FR-MEM-14 | Compaction MUST run when thresholds are crossed — unsummarized messages 20, unsummarized tokens 8,000, active context tokens 12,000, topic change, conversation inactivity, task completion — and MUST NOT run after every message. | §44 | 14 |
| FR-MEM-15 | Compaction MUST proceed: identify old messages outside the recent window → exclude low-value acknowledgements → group into a coherent episode → extract durable facts → generate episode summary → validate summary → store links to source messages → update rolling summary. | §44 | 14 |
| FR-MEM-16 | Original messages MUST NOT be deleted merely because they were summarized. | §44 | 14 |
| FR-MEM-17 | Memory retrieval MUST proceed: exact structured-fact lookup → dense memory search → keyword memory search → RRF fusion → reranking → conflict resolution → top relevant memories added to context. | §45 | 14 |
| FR-MEM-18 | Memory retrieval MUST be scoped by `user_id`, `knowledge_base_id` and `memory_status = ACTIVE`. | §45 | 14 |
| FR-MEM-19 | Exact identifiers such as exam dates or order numbers MUST use keyed lookup rather than semantic similarity. | §45 | 14 |
| FR-MEM-20 | A student MUST be able to view, edit, supersede and delete their durable memories. | §61, §7 | 14, 20 |

---

## Study-content generation

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-STU-01 | Students MUST be able to generate brief summaries, detailed summaries, examination notes, definitions, key concepts, formula lists and section outlines. | §46 | 15 |
| FR-STU-02 | Summaries MUST be generated from selected parent sections, processed in batches when necessary, and MUST retain citations. | §46 | 15 |
| FR-STU-03 | Quiz question types MUST include multiple choice, true/false, short answer, fill in the blank, chart interpretation and table interpretation. | §46 | 15 |
| FR-STU-04 | Quiz output MUST be structured JSON including `question`, `options`, `correct_answer`, `explanation`, `difficulty`, `source_chunk_id`, `document_id`, `page_number`. | §46 | 15 |
| FR-STU-05 | Quiz scoring MUST be deterministic. | §46 | 15 |
| FR-STU-06 | Flashcards MUST be generatable from definitions, key concepts, weak topics and incorrect quiz answers. | §46 | 15 |
| FR-STU-07 | Each flashcard MUST retain source provenance. | §46 | 15 |
| FR-STU-08 | Study plans MUST take exam date, available hours, selected chapters and priority topics as input. | §46 | 15 |
| FR-STU-09 | Study-plan dates and workload MUST be calculated in application code. The model MUST only phrase the tasks. | §46 | 15 |

---

## Learning progress

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-PRG-01 | Dedicated tables MUST store topic mastery, quiz performance, flashcard review history, completed chapters, weak concepts, study-plan completion and last review date. | §47 | 2, 15 |
| FR-PRG-02 | Learning progress MUST be structured data, not a prose conversation summary. | §47 | 15 |

---

## Model gateway

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-MDL-01 | All model execution MUST go through the Model Gateway. | §48 | 8 |
| FR-MDL-02 | The gateway MUST route: application → gateway → task router → capability registry → provider adapter. | §48 | 8 |
| FR-MDL-03 | The application MUST NOT call provider SDKs directly. | §48 | 8 |
| FR-MDL-04 | Adapter interfaces MUST exist for Ollama, OpenAI-compatible endpoints, Gemini, Anthropic, vLLM and llama.cpp-compatible servers. | §48 | 8 |
| FR-MDL-05 | Ollama and the OpenAI-compatible adapter MUST be implemented; Gemini and Anthropic adapters MAY remain interface-only until credentials exist. | D-17 | 8 |
| FR-MDL-06 | Separate interfaces MUST exist for text generation, multimodal generation, embeddings and reranking. | §49 | 8 |
| FR-MDL-07 | Capability metadata MUST record `text_generation`, `image_input`, `structured_output`, `streaming`, `prompt_caching`, `batch_generation`, `maximum_context_tokens`, `maximum_output_tokens`, `data_boundary`. | §49 | 8 |
| FR-MDL-08 | Model tasks MUST include `QUERY_REWRITE`, `QUERY_EXPANSION`, `ANSWER_GENERATION`, `VISUAL_QUESTION`, `MULTI_HOP_DECOMPOSITION`, `SUMMARIZATION`, `QUIZ_GENERATION`, `MEMORY_EXTRACTION`, `GRAPH_EXTRACTION`, `FAITHFULNESS_CHECK`. | §50 | 8 |
| FR-MDL-09 | The default answer model MUST be Gemma 3 4B through Ollama, with Gemma 3 multimodal capability for visual questions, a fast text model for query rewriting, and a fast verifier or conditional main model for verification. | §50, §65 | 8 |
| FR-MDL-10 | The configured model MUST be replaceable without changing retrieval or business logic. | §50 | 8 |
| FR-MDL-11 | Internal model keys `default_text_model`, `default_vision_model`, `query_rewrite_model` and `faithfulness_model` MUST be used. | §51 | 0.6, 8 |
| FR-MDL-12 | Provider-specific model names MUST NOT be scattered through application code. | §51 | 8 |
| FR-MDL-13 | Model configuration MUST be possible at deployment level and task level, and MAY be possible at Knowledge Base level. | §51 | 8 |
| FR-MDL-14 | Ordinary users MUST NOT be able to enter arbitrary provider endpoints in the initial version. | §51 | 8 |
| FR-MDL-15 | Each provider MUST declare a data boundary and whether private documents may be sent to it. | §52 | 8 |
| FR-MDL-16 | Before sending a prompt, the gateway MUST check whether private documents, memory or personal identifiers may be sent to the selected provider. | §52 | 8 |
| FR-MDL-17 | The system MUST NOT silently fall back from a local model to an external provider. | §52 | 8 |
| FR-MDL-18 | Fallback MUST proceed: primary model → capability check → provider call → retryable failure check → one retry → approved fallback. | §53 | 8 |
| FR-MDL-19 | Retryable errors MUST include timeout, temporary network error, rate limit and provider service error. | §53 | 8 |
| FR-MDL-20 | Non-retryable errors MUST include authentication failure, unsupported image, invalid configuration, context overflow and prohibited data boundary, and MUST fail without retry. | §53 | 8 |
| FR-MDL-21 | Every fallback MUST be logged. | §53 | 8 |
| FR-MDL-22 | The gateway MUST accept one provider-neutral prompt structure: system policy, task, conversation context, memory, source evidence, current question, output schema. | §54 | 8 |
| FR-MDL-23 | Adapters MUST translate the neutral structure into provider-specific formats. | §54 | 8 |
| FR-MDL-24 | Model-specific prompt profiles MAY adjust evidence placement, final instruction repetition, native JSON mode, system-message usage and token limits. | §54 | 8 |
| FR-MDL-25 | Business rules MUST remain provider-independent. | §54 | 8 |
| FR-MDL-26 | Every model invocation MUST be recorded with provider, model, token counts, throughput, fallback usage, cache-hit status and context size. | §62 | 8 |

---

## Performance

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-PRF-01 | Each task MUST use the smallest capable model — small models for simple facts and query rewriting, stronger models for complex synthesis, multimodal models only for visual questions. | §55 | 8, 16 |
| FR-PRF-02 | Configured models MUST be loaded at startup and receive a small warm-up request. | §55 | 8 |
| FR-PRF-03 | Local model quantization MUST be benchmarked at 4-bit, 5-bit and 8-bit against answer correctness, citation accuracy, tokens per second, time to first token and memory use. | §55 | 16 |
| FR-PRF-04 | Prompts MUST NOT include full conversation history, all retrieved candidates, duplicate evidence, unnecessary full parent sections, repeated policies or irrelevant graph edges. | §55 | 10, 16 |
| FR-PRF-05 | Output length MUST be limited per task. | §55 | 16 |
| FR-PRF-06 | Embeddings, reranking pairs, visual descriptions and independent sub-question checks MUST be batched. | §55 | 16 |
| FR-PRF-07 | Cheap validators MUST always run; semantic entailment checks MUST run only for high-risk or complex answers. | §55 | 16 |
| FR-PRF-08 | A selected table MUST take a direct table retrieval path, skipping graph retrieval and query expansion. | §55 | 16 |
| FR-PRF-09 | A selected figure MUST take an image and caption retrieval path, skipping broad search. | §55 | 16 |
| FR-PRF-10 | An exact identifier MUST take an exact structured lookup path. | §55 | 16 |
| FR-PRF-11 | The system MUST apply concurrency control: maximum active generations, per-user request limits, queue size, timeouts, cancellation on disconnect and backpressure. | §55 | 16 |

---

## Caching

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-CCH-01 | A cache abstraction MUST expose `get`, `set` and `invalidate`. | §56 | 16 |
| FR-CCH-02 | Cacheable items MUST include PDF parsing, OCR results, table extraction, visual descriptions, embeddings, document summaries, query rewrites, query expansions, retrieval results, reranker results and validated generated outputs. | §56 | 16 |
| FR-CCH-03 | The final-answer cache key MUST include `user_id`, `knowledge_base_id`, `conversation_id`, `conversation_state_hash`, `query_hash`, `selected_object_id`, `index_version`, `provider`, `model`, `prompt_version` and `generation_policy_version`. | §56 | 16 |
| FR-CCH-04 | Caches MUST be invalidated when documents are added, deleted or reprocessed; when embedding indexes change; when graph versions change; when prompts change; when models change; and when conversation state changes. | §56 | 16 |
| FR-CCH-05 | Semantic answer caching MUST NOT be part of the initial version. | §56 | 16 |
| FR-CCH-06 | The cache store MUST be PostgreSQL-backed. Redis MUST NOT be introduced unless a measured bottleneck requires it. | §4, §56, §67 | 16 |
| FR-CCH-07 | The cache table MUST be `UNLOGGED`, and expired entries MUST be swept on a schedule. | D-14 | 2, 16 |

---

## Concept graph visualization

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-VIZ-01 | Selecting a concept or chapter MUST return a limited set of nodes and edges for rendering. | §57 | 12 |
| FR-VIZ-02 | Initial graph views MUST be limited to approximately 30–50 nodes. | §57 | 12 |
| FR-VIZ-03 | The complete Knowledge Base graph MUST NOT be rendered at once. | §57 | 12, 20 |
| FR-VIZ-04 | Users MUST be able to click a concept, view its evidence, open the source page, expand one-hop neighbours, ask a question about a node, and view prerequisite or related concepts. | §57 | 20 |
| FR-VIZ-05 | The graph MUST be rendered with Cytoscape.js. | §57, §65 | 20 |

---

## Deletion and lifecycle

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-DEL-01 | Deletion MUST be asynchronous and idempotent. | §58 | 16 |
| FR-DEL-02 | Document deletion MUST proceed: verify ownership → mark `DELETING` → block retrieval → delete storage files → delete chunks and embeddings → delete tables and visuals → delete document-supported graph edges → preserve entities supported elsewhere → synchronize the graph projection → increment index version → invalidate caches → delete the document record. | §58 | 16 |
| FR-DEL-03 | Retrieval MUST be blocked as soon as deletion begins. | §58 | 16 |
| FR-DEL-04 | Graph entities still supported by other documents MUST be preserved when one document is deleted. | §58 | 16 |
| FR-DEL-05 | Knowledge Base deletion MUST apply the same process recursively to documents, conversations, memories, generated study content, graph data, storage files, embeddings and caches. | §58 | 16 |
| FR-DEL-06 | Deleted content MUST NOT be retrievable through search, citation, cache or memory. | §58, §64 | 16 |

---

## API design

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-API-01 | The API MUST be versioned under `/api/v1`. | §61 | 3 |
| FR-API-02 | Endpoints MUST exist for Knowledge Bases, documents and document status, conversations and messages, conversation streaming, graph and graph entities, summaries, quizzes, flashcards, study plans, and memory. | §61 | 3, and each feature phase |
| FR-API-03 | All routes MUST validate Knowledge Base ownership. | §61 | 3 |
| FR-API-04 | Conversation responses MUST be streamable over Server-Sent Events. | §6, §61 | 11 |
| FR-API-05 | Errors MUST be mapped to consistent HTTP responses without leaking internal detail. | §8 | 3 |

---

## Observability

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-OBS-01 | Each request MUST receive a trace ID. | §62 | 3 |
| FR-OBS-02 | The system MUST measure `authentication_ms`, `memory_retrieval_ms`, `query_rewrite_ms`, `query_expansion_ms`, `embedding_ms`, `dense_retrieval_ms`, `keyword_retrieval_ms`, `graph_retrieval_ms`, `rrf_ms`, `reranking_ms`, `context_building_ms`, `model_queue_ms`, `time_to_first_token_ms`, `generation_ms`, `validation_ms`, `total_ms`. | §62 | 3, 17 |
| FR-OBS-03 | Model metrics MUST record provider, model, input tokens, output tokens, tokens per second, fallback used, cache hit and context tokens. | §62 | 8, 17 |
| FR-OBS-04 | Operational metrics MUST record p50, p95 and p99 latency, queue depth, timeout rate, error rate, cancellation rate, processing-job failures and OCR failures. | §62 | 17 |
| FR-OBS-05 | Logs MUST NOT contain full private documents or prompts by default. | §62 | 3, 17 |

---

## Evaluation and security testing

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-EVL-01 | Retrieval and generation MUST be evaluated separately. | §63 | 17 |
| FR-EVL-02 | Retrieval evaluation MUST measure Recall@k, Precision@k, MRR, NDCG, relevant-document coverage, relevant-page coverage, table and visual retrieval accuracy, and graph-edge retrieval accuracy. | §63 | 17 |
| FR-EVL-03 | Reranking evaluation MUST measure recall before reranking, Recall@5 after reranking, MRR improvement, candidate-pool size and reranking latency. | §63 | 17 |
| FR-EVL-04 | Generation evaluation MUST measure answer correctness, faithfulness, citation entailment, citation completeness, unsupported-claim rate, contradiction rate, numerical accuracy, table accuracy, visual interpretation accuracy and abstention accuracy. | §63 | 17 |
| FR-EVL-05 | Multi-hop evaluation MUST measure decomposition correctness, sub-question completeness, required-document coverage, hop completion rate, evidence-set sufficiency, cross-document synthesis accuracy and conflict preservation. | §63 | 17 |
| FR-EVL-06 | Memory evaluation MUST measure fact-retention accuracy, memory retrieval Recall@k, supersession accuracy, stale-memory rate, incorrect-memory insertion, cross-Knowledge-Base leakage and deletion completeness. | §63 | 17 |
| FR-EVL-07 | Instruction-following evaluation MUST measure compliance per requirement, position sensitivity, conflict resolution, schema validity and repair success rate. | §63 | 17 |
| FR-EVL-08 | Security testing MUST cover cross-user access, cross-Knowledge-Base retrieval, unauthorized citation IDs, prompt injection inside a PDF, malicious memory-writing instructions, cached-answer reuse across users, signed-URL expiration, deleted-document retrieval, external-provider privacy violation, and graph queries without scope filters. | §64 | 17, and each feature phase |
| FR-EVL-09 | Evaluation results MUST be persisted so changes can be compared across runs. | §59 | 17 |
| FR-EVL-10 | The gold evaluation set MUST include labelled questions across every query class, with gold chunk and page identifiers. | §63, D-22 | 17 |

### Measured baselines

Run each `scripts/evaluate_*.py` against a live knowledge base and record the summary scores
here. `scripts/_eval_store.py` persists every run as timestamped JSON under
`evaluation/results/<script>/`; the git SHA in each file identifies which code version produced
the numbers. Update the **Measured** column and the **SHA** when a run replaces a prior
baseline. A blank **Measured** cell means the script has not yet been run against live data.

**Gold set:** `evaluation/gold/data-science-in-the-cloud.json` (18 pairs, 5 classes).

#### Retrieval — `evaluate_retrieval.py`

| Metric | Target | Measured | SHA |
|---|---|---|---|
| Page recall | ≥ 0.80 | — | — |
| MRR | ≥ 0.70 | — | — |
| NDCG@10 | ≥ 0.70 | — | — |
| Phrase coverage | ≥ 0.85 | — | — |

#### Reranking contribution — `evaluate_reranking.py`

| Metric | Target | Measured | SHA |
|---|---|---|---|
| Δ NDCG (reranked − RRF-only) | > 0 | — | — |
| Δ MRR (reranked − RRF-only) | > 0 | — | — |
| Δ Recall (reranked − RRF-only) | ≥ 0 | — | — |

#### Generation — `evaluate_generation.py`

| Metric | Target | Measured | SHA |
|---|---|---|---|
| Phrase coverage | ≥ 0.80 | — | — |
| Citation grounding | ≥ 0.85 | — | — |
| Abstain correct rate (unanswerable pairs) | 1.0 | — | — |
| False-abstain rate (answerable pairs) | 0.0 | — | — |
| Parse failure rate | 0.0 | — | — |

#### Multi-hop — `evaluate_multi_hop.py`

| Metric | Target | Measured | SHA |
|---|---|---|---|
| Phrase coverage | ≥ 0.75 | — | — |
| Sub-question supported rate | ≥ 0.70 | — | — |
| Mean sub-questions per query | — | — | — |

#### Instruction-following — `evaluate_instruction_following.py`

| Metric | Target | Measured | SHA |
|---|---|---|---|
| Schema valid rate | 1.0 | — | — |
| Label range valid rate | 1.0 | — | — |
| Length within limit rate | ≥ 0.95 | — | — |
| All claims cited rate | 1.0 | — | — |

#### Threshold calibration — `calibrate_thresholds.py`

| Setting | Current default | Calibrated | SHA |
|---|---|---|---|
| `EVIDENCE_RELATIVE_SCORE_MARGIN` | 0.35 | — | — |
| Retrieval p95 latency vs NFR-PERF-07 (≤ 800 ms) | provisional | — | — |

---

## Frontend

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| FR-UI-01 | The frontend MUST provide authentication screens. | §7 | 18 |
| FR-UI-02 | The frontend MUST provide Knowledge Base management. | §7 | 18 |
| FR-UI-03 | The frontend MUST provide document uploads with processing status. | §7 | 18 |
| FR-UI-04 | The frontend MUST provide a chat interface. | §7 | 19 |
| FR-UI-05 | The frontend MUST display streaming answers progressively. | §7 | 19 |
| FR-UI-06 | The frontend MUST provide PDF viewing. | §7 | 19 |
| FR-UI-07 | The frontend MUST provide citation navigation to page and bounding box. | §7 | 19 |
| FR-UI-08 | The frontend MUST allow table and figure selection as the subject of a question. | §7 | 19 |
| FR-UI-09 | The frontend MUST provide concept graph visualization. | §7 | 20 |
| FR-UI-10 | The frontend MUST provide quizzes and flashcards. | §7 | 20 |
| FR-UI-11 | The frontend MUST provide study-plan display. | §7 | 20 |
| FR-UI-12 | The frontend MUST provide memory-management controls. | §7 | 20 |
| FR-UI-13 | Insufficient-evidence and conflicting-source responses MUST be rendered distinctly from ordinary answers. | §35, §38 | 19 |
| FR-UI-14 | The frontend MUST be built with React, TypeScript, Vite, CSS Modules, TanStack Query and Zod. | §65 | 18 |

---
---

# Non-functional requirements

---

## Security {#security-nfr}

Knowledge Base isolation is the central security property. Every requirement here is testable, and
the six that admit no failures at all are promoted to [release gates](#release-gates).

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-SEC-01 | Row-Level Security MUST be enabled on every table carrying `user_id`, and MUST be verified by a test that enumerates tables and asserts policy presence. A new scoped table without RLS MUST fail the test suite. | §10 | 2 |
| NFR-SEC-02 | Scope filters MUST be applied within the query that ranks or traverses, never as a post-filter on results. Post-filtering MUST NOT be used as a substitute. | §10 | 9, 12 |
| NFR-SEC-03 | The repository layer MUST make an unscoped query structurally impossible — a query without a `ScopeContext` MUST fail to compile or fail at construction, not at review time. | §10 | 1, 2 |
| NFR-SEC-04 | `user_id` MUST be derived only from a verified access token, never from a request body, query parameter, header or client-supplied claim. | §10 | 3 |
| NFR-SEC-05 | Signed URLs MUST carry a bounded expiry, and expiry MUST be short enough that a leaked URL has limited value. Default MUST NOT exceed 1 hour. | §10, §64 | 4 |
| NFR-SEC-06 | Storage buckets MUST deny public access; every object read MUST require a signed URL issued after a backend ownership check. | §10 | 4 |
| NFR-SEC-07 | Text extracted from uploaded documents MUST be treated as untrusted data throughout the pipeline. Instructions found in that text MUST NOT influence system behaviour, prompt structure, memory writes or tool selection. | §38, §64 | 5, 11, 14 |
| NFR-SEC-08 | Every cache key that can return generated content MUST include `user_id` and `knowledge_base_id`, so a cache hit cannot cross a tenancy boundary. | §56, §64 | 16 |
| NFR-SEC-09 | Citation identifiers MUST be validated against the evidence set actually supplied to the model for that specific request. A citation naming a real but uncontextualised chunk MUST be rejected. | §40 | 11 |
| NFR-SEC-10 | Graph traversal MUST apply the same scope predicates as relational retrieval; a traversal path MUST NOT be able to reach a node outside the caller's Knowledge Base. | §64 | 12 |
| NFR-SEC-11 | Content belonging to a document or Knowledge Base in `DELETING` state MUST be unreachable through search, citation, cache, memory or graph from the moment deletion begins. | §58, §64 | 16 |
| NFR-SEC-12 | Secrets MUST NOT appear in source control, logs, error responses or client-visible payloads. | §62 | 0.6 |
| NFR-SEC-13 | Error responses MUST NOT disclose the existence of resources the caller does not own. | §10 | 3 |
| NFR-SEC-14 | The ten §64 security scenarios MUST each have a dedicated automated test, and those tests MUST run in the standard suite rather than on request. | §64 | 3–17 |
| NFR-SEC-15 | Uploaded files MUST be validated by magic bytes and constrained by size and page count before any parsing library touches them. | §11 | 4 |

---

## Privacy and data boundary {#privacy-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-PRV-01 | Every model provider MUST declare a `data_boundary`, and the gateway MUST refuse to send private documents, memory or personal identifiers to a provider whose boundary forbids them. | §52 | 8 |
| NFR-PRV-02 | The system MUST NOT fall back from a local provider to an external provider automatically. Such a fallback MUST raise rather than proceed. | §52 | 8 |
| NFR-PRV-03 | Logs MUST NOT contain full document text, full prompts, full model outputs or memory contents by default. Enabling verbose capture MUST be an explicit, non-default configuration. | §62 | 3, 17 |
| NFR-PRV-04 | Personal or document-derived data MUST NOT be placed in URL paths, query strings or referrer-exposed positions. | §10 | 3, 4 |
| NFR-PRV-05 | Deletion MUST remove derived data as well as canonical data — embeddings, full-text vectors, graph edges, cached answers, crops and memory records. | §58 | 16 |
| NFR-PRV-06 | The system's custody posture MUST be documented honestly. Under the current deployment the corpus resides with third-party providers; documentation MUST state this rather than implying local-only custody. | R-01 | 0.11 |
| NFR-PRV-07 | A student MUST be able to delete their own content, and deletion MUST be complete rather than a soft flag that leaves data retrievable. | §58 | 16 |
| NFR-PRV-08 | Evaluation and observability records MUST store identifiers and metrics, not document content. | §62, §63 | 17 |

---

## Performance and latency {#performance-nfr}

The specification states no latency targets. The budgets below are **derived from the described
pipeline** on the target hardware (local NVIDIA GPU for inference, embeddings and reranking;
Supabase Cloud PostgreSQL over the network). They are **provisional** and MUST be recalibrated
against measured p50/p95/p99 in Phase 17 (D-23).

### Derivation — `DIRECT` query, time to first token

Every database round trip crosses the internet under the current hosting choice, which is the
single largest non-model contributor.

| Stage | Budget | Basis |
|---|---|---|
| Authentication | 5 ms | Local JWT verification, cached JWKS |
| Conversation context + memory load | 120 ms | 1–2 Supabase round trips |
| Query rewrite | 500 ms | ~30 output tokens on a small local model; skipped when the question is already standalone |
| Classification | 5 ms | Deterministic rules, no model call |
| Cache lookup | 40 ms | 1 round trip |
| Query embedding | 15 ms | `bge-small-en-v1.5`, 384-dim, GPU |
| Dense + keyword retrieval | 200 ms | Parallel across variants; pgvector HNSW and `rum` |
| RRF fusion | 5 ms | In-process |
| Cross-encoder reranking | 80 ms | 40 pairs batched, MiniLM-L6, GPU |
| Evidence selection, parent expansion, compression | 150 ms | Extractive; at most one extra round trip |
| Context construction | 10 ms | In-process |
| Prompt prefill to first token | 700 ms | ~2,500-token prompt on Gemma 3 4B, GPU |
| **Total** | **~1.8 s typical** | **2.5 s p95 allowing for variance** |

### Hardware ceiling

Measured in step 0.3: **NVIDIA RTX 3050 6 GB Laptop, driver 555.97, compute capability 8.6.**

6 GB is the binding constraint on the whole design. The allocation (D-27):

| Component | Device | VRAM |
|---|---|---|
| Gemma 3 4B, quantized, + KV cache | GPU | ~3.5 GB |
| `bge-small-en-v1.5` | GPU | 0.13 GB (measured) |
| `ms-marco-MiniLM-L6-v2` | GPU | 0.09 GB (measured) |
| PaddleOCR PP-OCRv6 and VL | **CPU** | — |
| **Remaining headroom** | | **~2.3 GB** |

Ingestion budgets below assume CPU OCR. Chat budgets (`NFR-PERF-01` … `NFR-PERF-10`) are unaffected
— the GPU is not contended by the worker.

### Budgets

| ID | Requirement | Target | Phase |
|---|---|---|---|
| NFR-PERF-01 | Time to first token, `DIRECT` and `EXACT_TERM` queries | ≤ 2.5 s p95 | 17 |
| NFR-PERF-02 | Time to first token, `TABLE` and `VISUAL` queries taking an early-exit path | ≤ 2.0 s p95 | 17 |
| NFR-PERF-03 | Complete answer, ordinary single-hop query | ≤ 6 s p95 | 17 |
| NFR-PERF-04 | First progress event, `MULTI_HOP` and `MULTI_DOCUMENT` queries | ≤ 1 s p95 | 17 |
| NFR-PERF-05 | Time to first token of the synthesized answer, `MULTI_HOP` | ≤ 12 s p95 | 17 |
| NFR-PERF-06 | Complete answer, `MULTI_HOP` at maximum rounds | ≤ 30 s p95 | 17 |
| NFR-PERF-07 | Retrieval through reranking, excluding generation | ≤ 800 ms p95 | 17 |
| NFR-PERF-08 | Memory retrieval | ≤ 250 ms p95 | 17 |
| NFR-PERF-09 | Validation, deterministic checks only | ≤ 100 ms p95 | 17 |
| NFR-PERF-10 | Ingestion, native-text page | ≤ 1 s p95 | 17 |
| NFR-PERF-11 | Ingestion, scanned page via PP-OCRv6 **on CPU** (D-27) | ≤ 15 s p95 | 5, 17 |
| NFR-PERF-12 | Ingestion, complex page via PaddleOCR-VL fallback **on CPU** (D-28) | ≤ 120 s p95 | 5, 17 |
| NFR-PERF-21 | Full-document ingestion, 400-page scanned textbook | ≤ 2 h | 5, 17 |
| NFR-PERF-22 | Full-document ingestion, 400-page native-text PDF | ≤ 20 min | 5, 17 |
| NFR-PERF-13 | Upload endpoint response, excluding background processing | ≤ 1.5 s p95 | 4 |
| NFR-PERF-14 | Concept graph query returning ≤ 50 nodes | ≤ 500 ms p95 | 17 |

### Performance behaviours

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-PERF-15 | Interactive requests MUST NOT be blocked by ingestion, OCR, graph building or compaction. | §7, §12 | 4 |
| NFR-PERF-16 | Configured models MUST be warm before the first user request is served. | §55 | 8 |
| NFR-PERF-17 | The PaddleOCR-VL fallback MUST be invoked on a minority of pages. If it exceeds 20% of pages on a representative document, the classifier MUST be treated as miscalibrated. | §15 | 5, 17 |
| NFR-PERF-18 | A client disconnect MUST cancel in-flight generation rather than completing work nobody will receive. | §55 | 16 |
| NFR-PERF-19 | The system MUST apply backpressure rather than queueing without bound when concurrent generation capacity is exhausted. | §55 | 16 |
| NFR-PERF-20 | Latency MUST be attributable — every budget above MUST map to instrumented stages so a regression identifies its own cause. | §62 | 3, 17 |

---

## Reliability {#reliability-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-REL-01 | Every background job MUST be idempotent; re-running it MUST NOT duplicate derived records or corrupt state. | §12, §58 | 4 |
| NFR-REL-02 | A worker crash MUST NOT strand a job. Expired leases MUST be reclaimable by another worker without manual intervention. | §12 | 4 |
| NFR-REL-03 | Job failures MUST be bounded by an attempt count and dead-lettered rather than retried indefinitely. | §12 | 4 |
| NFR-REL-04 | Answer repair MUST be attempted at most once. Regeneration loops MUST NOT be possible. | §39 | 11 |
| NFR-REL-05 | Multi-hop retrieval MUST terminate — bounded by 3 rounds and 8 sub-questions regardless of coverage outcome. | §35 | 13 |
| NFR-REL-06 | Provider failure MUST degrade explicitly: an approved fallback, or a clear error. Silent substitution MUST NOT occur. | §53 | 8 |
| NFR-REL-07 | A document that fails processing MUST NOT leave partial content retrievable. | §11 | 5, 7 |
| NFR-REL-08 | Ingestion MUST be resumable at page granularity so a failure late in a long document does not discard completed work. | §12 | 5 |
| NFR-REL-09 | Deletion MUST be resumable and idempotent, and MUST reach a terminal state even if interrupted partway. | §58 | 16 |
| NFR-REL-10 | Insufficient evidence MUST be a normal, correct outcome — never an error, and never grounds for answering from model memory. | §38, §39 | 11 |
| NFR-REL-11 | Database migrations MUST run to completion or roll back cleanly; a partially applied migration MUST NOT be a reachable state. | §65 | 2 |
| NFR-REL-12 | External service unavailability — Supabase, R2 or the model provider — MUST produce an actionable error rather than a stack trace or a hang. | §53 | 3, 4, 8 |

---

## Data integrity {#data-integrity-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-DAT-01 | PostgreSQL MUST remain the single canonical store. No derived system may hold data that cannot be reconstructed from it. | §5 | 2 |
| NFR-DAT-02 | Rebuildability MUST be demonstrable, not assumed — a test MUST reconstruct vector indexes, full-text indexes and the graph projection from canonical records. | §5, §22 | 7, 12 |
| NFR-DAT-03 | Embedding indexes MUST be versioned, and a retrieval query MUST NOT mix embeddings from different versions. | §20 | 7 |
| NFR-DAT-04 | Graph records MUST be versioned, and a traversal MUST NOT mix graph versions. | §21, §22 | 12 |
| NFR-DAT-05 | Every chunk, table, visual object and graph edge MUST be traceable to a source document, page and bounding box. | §16, §21, §40 | 5, 6, 12 |
| NFR-DAT-06 | Deleting a document MUST NOT orphan chunks, embeddings, citations, graph edges or crops. | §58 | 16 |
| NFR-DAT-07 | Deleting a document MUST NOT delete graph entities that remain supported by other documents. | §58 | 16 |
| NFR-DAT-08 | Numerical values and units MUST survive extraction, chunking, compression and generation unaltered. | §33, §38 | 6, 10, 11 |
| NFR-DAT-09 | Original messages MUST be immutable once persisted; summaries and derived memory MUST NOT overwrite them. | §42, §44 | 14 |
| NFR-DAT-10 | Conflicting memory MUST be preserved with status rather than silently overwritten, so supersession is auditable. | §43 | 14 |
| NFR-DAT-11 | Schema changes MUST be expressed as versioned migrations. Manual schema edits MUST NOT be a supported workflow. | §65 | 2 |

---

## Observability {#observability-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-OBS-01 | Every request MUST be traceable end to end by a single trace ID, including work performed by background workers on its behalf. | §62 | 3 |
| NFR-OBS-02 | All 16 §62 stage timings MUST be recorded for every interactive request, not sampled. | §62 | 3, 17 |
| NFR-OBS-03 | Every model invocation MUST be recorded, including invocations that failed, fell back or were served from cache. | §62 | 8 |
| NFR-OBS-04 | Latency MUST be reported as p50, p95 and p99. A mean alone MUST NOT be used to assess a budget. | §62 | 17 |
| NFR-OBS-05 | Evaluation results MUST be persisted per run so regressions between changes are detectable. | §63 | 17 |
| NFR-OBS-06 | Retrieval decisions MUST be inspectable after the fact — which candidates were retrieved, how they ranked, which were selected, and why an answer abstained. | §62, §63 | 9, 17 |

---

## Maintainability {#maintainability-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-MNT-01 | Dependencies MUST point inward. Domain code MUST NOT import FastAPI, SQLAlchemy, provider SDKs or any infrastructure library, enforced by an automated test rather than review. | §8 | 1 |
| NFR-MNT-02 | The presentation layer MUST NOT contain retrieval, OCR or provider-specific logic. | §8 | 3 |
| NFR-MNT-03 | Provider-specific model names MUST NOT appear outside provider configuration. | §51 | 8 |
| NFR-MNT-04 | Tuning constants — RRF `k`, top-k values, candidate pool size, reranker thresholds, evidence limits, chunk sizes, compaction thresholds — MUST be named configuration, never literals in application code. | D-20 | 0.6 |
| NFR-MNT-05 | Each retrieval, evidence and validation stage MUST be independently testable without running the full pipeline. | §63 | 9–11 |
| NFR-MNT-06 | Prompts MUST be versioned, and the version MUST be recorded with every generated message. | §41, §56 | 11 |
| NFR-MNT-07 | Public API request and response schemas MUST be defined once and mirrored in the frontend by generated or hand-checked Zod schemas that are tested against the backend contract. | §65 | 18 |
| NFR-MNT-08 | A requirement in this register MUST be referenceable by ID from tests and use cases, and requirement IDs MUST NOT be reused after withdrawal. | — | all |

---

## Portability {#portability-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-POR-01 | Replacing the answer-generation model MUST require configuration change only — no change to retrieval, evidence, validation or business logic. | §50 | 8 |
| NFR-POR-02 | Replacing the object storage provider MUST require implementing one port, with no change to callers. | D-08 | 4 |
| NFR-POR-03 | Introducing a dedicated graph database later MUST require implementing `GraphPort`, with no change to callers. `GraphPort` MUST therefore be expressed in traversal terms, not in any vendor query language. | D-10 | 1, 12 |
| NFR-POR-04 | Replacing the authentication provider MUST require implementing one dependency, with RLS predicates reading a session-scoped identity rather than a vendor-specific function directly in every policy. | R-01 | 2, 3 |
| NFR-POR-05 | The development environment MUST work on Windows without containers. | — | 0 |
| NFR-POR-06 | Changing the embedding model MUST be a configuration change plus a reindex job, never a schema migration. | §20 | 7 |

---

## Capacity {#capacity-nfr}

| ID | Requirement | Target | Phase |
|---|---|---|---|
| NFR-CAP-01 | Permanent object storage per ingested 400-page textbook — original plus table and figure crops, excluding regenerable page renders | ≤ 100 MB | 5, 6 |
| NFR-CAP-02 | Database footprint per ingested 400-page textbook, including chunks, elements, embeddings and indexes | ≤ 40 MB | 7 |
| NFR-CAP-03 | Page renders MUST be regenerable and MUST expire, rather than accumulating permanently | TTL-bounded | 5, 16 |
| NFR-CAP-04 | Concept graph responses MUST be bounded regardless of Knowledge Base size | ≤ 50 nodes | 12 |
| NFR-CAP-05 | Evidence sent to the model MUST be bounded regardless of retrieval pool size | ≤ 8 items, ordinary queries | 10 |
| NFR-CAP-06 | Storage and database growth MUST be observable, so a free-tier ceiling is approached with warning rather than discovered on failure | instrumented | 17 |
| NFR-CAP-07 | Conversation and retrieval-log tables MUST be designed partition-ready so growth is addressable without a schema rewrite | design-time | 2 |

---

## Usability and accessibility {#usability-nfr}

| ID | Requirement | Spec | Phase |
|---|---|---|---|
| NFR-UX-01 | Long-running operations — upload processing, multi-hop retrieval, graph building — MUST show progress rather than an indefinite spinner. | §7 | 18–20 |
| NFR-UX-02 | An abstention MUST be visually distinct from an answer, so a student is not misled into treating "insufficient evidence" as a conclusion. | §38 | 19 |
| NFR-UX-03 | Conflicting sources MUST be presented as a conflict, not resolved silently in the interface. | §35 | 19 |
| NFR-UX-04 | Citations MUST be reachable in one interaction from the claim they support. | §40 | 19 |
| NFR-UX-05 | The interface MUST meet WCAG 2.1 AA for contrast, keyboard navigation and focus management. | — | 20 |
| NFR-UX-06 | The interface MUST be usable at tablet width; the PDF viewer and graph view MUST degrade rather than break. | — | 20 |
| NFR-UX-07 | Processing failures MUST explain what failed and what the student can do, not surface an internal error code alone. | §11 | 18 |

---

## Release gates

These six admit **no failures**. Each is an automated test that fails the suite on any non-zero
result. They are drawn directly from §64 and are not negotiable against schedule.

| ID | Gate | Threshold | Enforcing test | Phase |
|---|---|---|---|---|
| NFR-GATE-01 | Cross-user data leakage | **0** | A second user's token MUST NOT reach any record, file, citation, cached answer, memory or graph node belonging to the first, across every endpoint. | 3, 17 |
| NFR-GATE-02 | Cross-Knowledge-Base leakage | **0** | Retrieval, graph traversal, memory lookup and citation resolution within one Knowledge Base MUST NOT surface content from another owned by the same user. | 9, 12, 14, 17 |
| NFR-GATE-03 | Fabricated citation acceptance | **0** | An answer citing an identifier that does not exist, was not in context, or belongs to another scope MUST be rejected by validation and MUST NOT reach the student. | 11, 17 |
| NFR-GATE-04 | Deleted memory retrieval | **0** | A memory record in `DELETED` state, and any content belonging to a deleted document or Knowledge Base, MUST NOT be retrievable through any path. | 14, 16, 17 |
| NFR-GATE-05 | Unauthorized cache reuse | **0** | A cached answer MUST NOT be served to a different user, a different Knowledge Base, or across an index, prompt, model or conversation-state change. | 16, 17 |
| NFR-GATE-06 | Graph edge without provenance | **0** | An edge lacking `source_chunk_id`, `page_number` or evidence MUST be rejected at write time and MUST NOT exist in the store. | 12, 17 |

**Gate discipline.** A gate failure blocks release regardless of feature completeness. Gates are
checked continuously from the phase that introduces the surface, not deferred to Phase 17 — Phase 17
consolidates them into a single suite and adds the evaluation metrics around them.

---

## Coverage confirmation

All 68 specification sections are represented above.

| Sections | Covered by |
|---|---|
| §1, §2, §3, §4 | OBJ, AUTH |
| §5 | KB, RET, VAL |
| §6 | API |
| §7 | JOB, UI |
| §8 | API |
| §9 | KB |
| §10 | AUTH |
| §11 | DOC |
| §12 | JOB |
| §13, §14, §15, §16 | ING |
| §17 | TBL |
| §18 | VIS |
| §19 | CHK |
| §20 | IDX |
| §21, §22 | GRA |
| §23 | CNV |
| §24, §25, §26 | QRY |
| §27, §28, §29 | RET |
| §30, §31, §32, §33 | EVD |
| §34 | RET |
| §35 | HOP |
| §36, §37 | CTX |
| §38 | GEN |
| §39 | VAL |
| §40 | CIT |
| §41 | CNV |
| §42, §43, §44, §45 | MEM |
| §46 | STU |
| §47 | PRG |
| §48, §49, §50, §51, §52, §53, §54 | MDL |
| §55 | PRF |
| §56 | CCH |
| §57 | VIZ |
| §58 | DEL |
| §59, §60 | KB, ING, IDX, CCH |
| §61 | API |
| §62 | OBS |
| §63, §64 | EVL |
| §65 | ING, IDX, RET, MDL, VIZ, UI |
| §66 | — repository structure, realised in Phase 0.1 |
| §67 | — scaling path, recorded in ARCHITECTURE.md |
| §68 | CNV, HOP — the end-to-end flow is the composition of all of the above |
