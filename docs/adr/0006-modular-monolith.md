# ADR-0006 — Modular monolith, not microservices

**Status:** Accepted · 2 August 2026
**Phase:** 1
**Requirements:** FR-JOB-09, NFR-MNT-01, NFR-MNT-02

## Context

The system has recognisably separable concerns: interactive RAG, document processing, model
gateway. §67 names those as eventual service boundaries. §4 excludes microservices at the initial
stage.

Document ingestion is CPU- and GPU-heavy and long-running. Chat is latency-sensitive. Running both
in one process would let a 400-page OCR job starve interactive requests.

## Decision

A modular monolith with clean/hexagonal architecture, deployed as **two processes sharing one
codebase**:

- **API process** — REST, auth, interactive retrieval, orchestration, streaming
- **Worker process** — ingestion, OCR, embeddings, graph, compaction, deletion

They share domain and application code and communicate only through the job table. There is no
direct call path between them.

Module boundaries are enforced as layers and ports, so a service split later is a deployment change
rather than a rewrite.

## Alternatives

| Option | Why not |
|---|---|
| Microservices from the start | Excluded by §4. Buys operational cost and distributed-systems failure modes before there is load to justify either. |
| Single process | Ingestion would block chat — the one thing §7 explicitly separates processes to prevent. |
| Serverless functions | Model weights and warm models (`FR-PRF-02`) are incompatible with cold-start execution. |

## Consequences

**Gained.** One deployment, one migration story, one dependency set. In-process calls with no
serialization boundary. Refactoring across module boundaries stays cheap while the design is still
moving.

**Accepted cost.** The boundaries are conventions unless enforced. That is why the dependency rule
is an automated test (`NFR-MNT-01`) rather than a guideline — without it, a monolith becomes a ball
of mud and the eventual split becomes impossible.

## Revisit if

Operational load justifies a split, per §67 — sustained inference concurrency that warrants a
dedicated model-gateway service, or ingestion volume that warrants an independently scaled
document-processing service.
