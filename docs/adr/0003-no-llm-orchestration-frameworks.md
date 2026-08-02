# ADR-0003 — No LangChain, LangGraph or LlamaIndex

**Status:** Accepted · 2 August 2026
**Phase:** all
**Requirements:** FR-OBJ-12, NFR-MNT-01, NFR-MNT-05

## Context

LangChain, LangGraph and LlamaIndex are the default reach for a RAG system. They provide document
loaders, splitters, retrievers, chains, agent loops and provider abstractions.

This pipeline is deterministic and carries substantial custom behaviour that is not incidental —
it is the point of the system:

- Mandatory `user_id` and `knowledge_base_id` predicates **inside** every retrieval query, before
  ranking (`NFR-SEC-02`)
- Claim-level citation validation against the evidence set supplied to that specific request
  (`NFR-SEC-09`)
- Multimodal elements as first-class retrievable objects with bounding boxes
- Graph edges that are rejected at write time without provenance (`FR-GRA-08`)
- Coverage-aware multi-hop evidence assembly with explicit conflict preservation

## Decision

No orchestration framework. Retrieval, fusion, reranking, evidence selection, context construction,
generation and validation are written directly against the domain ports.

## Alternatives

| Option | Why not |
|---|---|
| LangChain | Retriever abstractions do not naturally express a mandatory scope predicate; the security property would live in a wrapper the framework is free to bypass. Frequent breaking changes. |
| LlamaIndex | Opinionated index ownership conflicts with the canonical-PostgreSQL principle (§5). Its index becomes a second source of truth. |
| LangGraph | Explicitly excluded — agent graphs are the thing §4 rules out. |
| A thin framework for provider calls only | This is exactly what the Model Gateway is (ADR-0009), written to our own contract. |

## Consequences

**Accepted cost.** More code. No free ecosystem integrations. Every splitter, retriever and fusion
step is ours to write and test.

**Gained.** Each stage is independently testable without running the pipeline (`NFR-MNT-05`). The
security properties live in the repository layer where they can be enforced structurally rather
than in a wrapper. No framework upgrade churn on a multi-month build.

## Revisit if

Never for orchestration — the deterministic pipeline is a design requirement, not a convenience.
A **narrow, single-purpose utility** may be vendored if it is genuinely better than writing it
(a tokenizer, a table-to-markdown converter), provided it does not own control flow.
