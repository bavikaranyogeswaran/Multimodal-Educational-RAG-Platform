# ADR-0010 — One-hop initial graph traversal depth

**Status:** Accepted · 2 August 2026
**Phase:** 12
**Requirements:** FR-RET-15, FR-RET-16

## Context

Graph retrieval could traverse to arbitrary depth. Each additional hop expands the neighbourhood
combinatorially, and in a concept graph extracted from a textbook, two-hop neighbours are frequently
related to the seed concept only in the loosest sense — "photosynthesis → chloroplast → cell
membrane → osmosis" is a real path that is not a real relationship.

Deeper traversal also degrades precision at the reranker: it arrives with more candidates, most of
them weakly relevant, which is exactly the condition under which cross-encoders get expensive
without getting better.

Separately, genuine multi-step reasoning is already handled by a *different and better* mechanism —
sub-question decomposition with dependency ordering (`FR-HOP-02`), which reasons about what needs
answering rather than about what happens to be adjacent in a graph.

## Decision

Initial traversal depth is **one hop**. Deeper traversal is added only when evaluation demonstrates
a specific need.

Graph triples are never sufficient on their own — the edge's source passage is loaded from
PostgreSQL and passed to the reranker and model (`FR-RET-16`).

## Alternatives

| Option | Why not |
|---|---|
| Two or three hops by default | Combinatorial expansion, weak-relevance edges, slower reranking, no evidence it helps |
| Unbounded traversal with scoring cutoff | Adds a tuning surface with no baseline to tune against |
| No traversal — direct edge lookup only | Slightly cheaper, but loses "what else is this connected to", which is the point |

## Consequences

**Gained.** Fast, precise, and — critically — implementable as a single join. That property is what
makes ADR-0012 viable: one hop does not require a graph database.

**Accepted cost.** Some relationship questions that genuinely need two hops will under-retrieve via
the graph path. Multi-hop decomposition covers most of these by a different route.

## Revisit if

Phase 17 multi-hop evaluation shows graph-edge retrieval accuracy is the limiting factor on
relationship questions, and that the gap is specifically depth rather than extraction quality. Note
that increasing depth may also change ADR-0012, since recursive CTEs degrade past roughly three
levels on a large graph.
