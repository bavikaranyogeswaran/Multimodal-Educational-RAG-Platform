# Architecture Decision Records

One decision per file. Each records the context that forced the decision, the alternatives that were
genuinely considered, the consequences accepted, and — importantly — **the condition under which the
decision should be revisited**. A decision without a revisit condition is a belief, not a decision.

## Format

```
# ADR-000N — Title
Status · Phase · Requirements
## Context      what forced a choice
## Decision     what was chosen
## Alternatives what was rejected and why
## Consequences what this costs and buys
## Revisit if   the falsifying condition
```

Status values: **Accepted** · **Superseded by ADR-N** · **Pending results**.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-no-pymupdf.md) | No PyMuPDF — licensing | Accepted |
| [0002](0002-self-hosted-paddleocr.md) | Self-hosted PaddleOCR, not cloud OCR | Accepted |
| [0003](0003-no-llm-orchestration-frameworks.md) | No LangChain, LangGraph or LlamaIndex | Accepted |
| [0004](0004-selective-graph-rag.md) | Selective, not global, GraphRAG | Accepted |
| [0005](0005-postgresql-as-queue-and-cache.md) | PostgreSQL as job queue and cache, not Redis | Accepted |
| [0006](0006-modular-monolith.md) | Modular monolith, not microservices | Accepted |
| [0007](0007-hyde-disabled-by-default.md) | HyDE disabled by default | Accepted |
| [0008](0008-graph-extraction-opt-in.md) | Graph extraction opt-in per Knowledge Base | Accepted |
| [0009](0009-provider-agnostic-model-gateway.md) | Provider-agnostic model gateway | Accepted |
| [0010](0010-one-hop-traversal-depth.md) | One-hop initial graph traversal depth | Accepted |
| [0011](0011-quantization-benchmark.md) | Benchmark local model quantization | Pending results |
| [0012](0012-postgresql-graph-adapter.md) | PostgreSQL graph adapter, Neo4j deferred | Accepted |
| [0013](0013-cloudflare-r2-object-storage.md) | Cloudflare R2 over Supabase Storage | Accepted |
| [0014](0014-page-renders-as-cache.md) | Page renders as regenerable cache | Accepted |
| [0015](0015-rum-over-gin.md) | `rum` over GIN for full-text indexes | Accepted |

ADRs 0001–0011 record decisions made in the system design specification. ADRs 0012–0015 record
decisions made during the database stack review, and deviate from the specification as written —
each states the deviation explicitly.
