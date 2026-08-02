# ADR-0004 — Selective, not global, GraphRAG

**Status:** Accepted · 2 August 2026
**Phase:** 12
**Requirements:** FR-OBJ-14, FR-RET-12, FR-RET-13, FR-RET-16

## Context

Global GraphRAG builds a community-summarised knowledge graph over an entire corpus and routes
every query through graph structure. It is powerful for corpus-wide sensemaking — "what are the
main themes across these documents".

Most questions in this system are not that. They are "what does this page say", "explain this
figure", "what is the definition of X". A graph adds nothing to those and costs latency on every
one of them.

## Decision

Graph retrieval is an **additional path selected by query classification**, never the default
retriever. It runs for relationship, prerequisite, cross-chapter, figure-to-concept, concept-map
and related-document questions (`FR-RET-13`).

Graph results join the other ranked lists through RRF rather than replacing them. Graph triples
alone are never sufficient evidence — the source passage is loaded from PostgreSQL and passed to the
reranker and model (`FR-RET-16`).

## Alternatives

| Option | Why not |
|---|---|
| Global GraphRAG over every query | Expensive to build, expensive per query, and worse than vector retrieval for the majority of student questions |
| No graph at all | Loses prerequisite chains, cross-chapter connections and concept maps — all explicit §2 objectives |
| Graph as the primary retriever with vector as fallback | Inverts the cost profile; most queries would pay for structure they do not use |

## Consequences

**Gained.** Graph cost is paid only by queries that need it. The graph only has to be good at
relationship questions, not at everything. Extraction can be opt-in (ADR-0008) precisely because
the system is fully functional without it.

**Accepted cost.** Query classification becomes load-bearing — a relationship question routed away
from the graph gets a worse answer, and this failure is silent. Phase 17 must measure it.

## Revisit if

Phase 17 evaluation shows classification is systematically routing relationship-shaped questions
away from the graph path, or that graph-eligible questions are common enough that always consulting
the graph would be cheaper than classifying.
