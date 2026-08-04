# Multimodal Educational Tutor RAG

A private, student-facing, multimodal Retrieval-Augmented Generation platform. Students create
dedicated Knowledge Bases for a subject, course or examination, upload educational documents, and
study the material through grounded, cited conversations.

Built as a clean modular monolith. Deterministic orchestration — no agents, no planning loops.

> PostgreSQL preserves the truth, retrieval assembles the evidence, the model explains it, and
> validation determines whether the explanation is safe to return.

## Status

**Phase 0 — foundation.** Nothing is runnable yet. See [PLAN.md](PLAN.md) for the phase breakdown
and current progress.

## What it does

- PDF and image ingestion, native-text and scanned, with layout-aware parsing and OCR
- Table, chart, diagram and figure understanding as first-class retrievable objects
- Hybrid dense + keyword retrieval, Reciprocal Rank Fusion, cross-encoder reranking
- Selective Graph RAG for relationship, prerequisite and cross-chapter questions
- Multi-hop and multi-document retrieval with coverage-aware evidence selection
- Source-grounded answers with claim-level citations, validated before they are returned
- Hierarchical long-term conversational memory across weeks or months
- Summaries, quizzes, flashcards, study plans and progress tracking
- Provider-agnostic model execution, defaulting to local inference

Strict Knowledge Base isolation is the core security boundary — every record, query and citation is
scoped to a `(user_id, knowledge_base_id)` pair.

## Documentation

| Document | Purpose |
|---|---|
| [PLAN.md](PLAN.md) | Phased implementation plan and decisions log |
| [REQUIREMENTS.md](REQUIREMENTS.md) | Functional and non-functional requirements register |
| [USE_CASES.md](USE_CASES.md) | Use cases with flows and acceptance criteria |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, dependency rules and data flows |
| [EXECUTION_LOG.md](EXECUTION_LOG.md) | Assumptions and judgement calls made during each step |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Repository layout

```
backend/     FastAPI application, workers and domain code
  app/
    api/             presentation — routes, schemas, dependencies, middleware
    application/     use-case orchestration
    domain/          entities and interfaces; imports no framework or SDK
    infrastructure/  adapters implementing the domain interfaces
    workers/         background job processes
    configuration/   typed settings
  tests/
  alembic/
  scripts/
frontend/    React + TypeScript + Vite client
docs/adr/    architecture decision records
```

Dependencies point inward. Domain code does not import FastAPI, SQLAlchemy, Neo4j or any provider
SDK — enforced by a test.

## Stack

React · TypeScript · Vite · CSS Modules · TanStack Query · Zod · PDF.js · Cytoscape.js
FastAPI · Pydantic · SQLAlchemy · psycopg · Alembic · HTTPX
Supabase (Auth, PostgreSQL) · pgvector · PostgreSQL full-text search · Cloudflare R2
pypdf · pdfplumber · pypdfium2 · Pillow · PaddleOCR
BAAI/bge-small-en-v1.5 · cross-encoder/ms-marco-MiniLM-L6-v2 · Gemma 3 4B via Ollama
Pytest · Vitest · Playwright

## Scope

Excluded by design: autonomous agents, planning loops, tool-calling, LangChain/LangGraph/LlamaIndex,
text-to-speech, multi-user collaboration, public sharing, microservices, Kubernetes, Kafka,
Elasticsearch, Redis, and global GraphRAG over every query.
