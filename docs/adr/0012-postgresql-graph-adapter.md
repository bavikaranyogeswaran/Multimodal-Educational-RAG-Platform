# ADR-0012 — PostgreSQL graph adapter, Neo4j deferred

**Status:** Accepted · 2 August 2026 · **Deviates from §22 and §65 as written**
**Phase:** 1, 12
**Requirements:** FR-GRA-09, FR-GRA-10, FR-GRA-11, FR-GRA-13, FR-JOB-11, NFR-POR-03, NFR-GATE-06

## Context

§22 names Neo4j as the graph projection and §65 lists it in the stack. But three statements in the
same specification undercut the need for it at this stage:

- **§34:** "Initial traversal depth is one hop." One hop is a single join on `graph_relationships`.
- **§57:** initial graph views are limited to approximately 30–50 nodes. That is a bounded recursive
  CTE, not a graph workload.
- **§22:** "Neo4j can be rebuilt from PostgreSQL." The specification already declares it derived and
  disposable.

Investigation surfaced four further facts:

| Finding | Consequence |
|---|---|
| Neo4j AuraDB Free auto-pauses after **72 hours** of inactivity, is permanently deleted after 90 days paused, and offers no backups or dumps on the free plan | A development database that disappears over a long weekend |
| Node limits are documented inconsistently — the FAQ says 200k nodes / 400k relationships, the product page says 50k / 175k | Cannot size against it reliably |
| **Apache AGE is not among Supabase Cloud's 64 approved extensions** | The cleanest option — Cypher inside PostgreSQL, one database, no sync — is unavailable |
| **KùzuDB was archived in October 2025**, team acqui-hired | Rejected as an embedded alternative |

There is also a structural argument. `FR-RET-16` requires that every graph result load its source
passage from PostgreSQL before reaching the reranker. With Neo4j that is a cross-system round trip
on every graph query. With a PostgreSQL adapter it is a join in the same query.

## Decision

Implement `GraphPort` with a **PostgreSQL adapter**. One-hop traversal is a join; concept-map views
are a recursive CTE bounded at 50 nodes.

`SYNC_NEO4J` remains a recognised job type per §12, as a documented no-op (`FR-JOB-11`).

`GraphPort` is expressed in **traversal vocabulary** — `neighbors(entity, depth, types)`,
`subgraph(seed, max_nodes)` — never in a vendor query language, so a Neo4j adapter can be added
later without touching a single caller (`NFR-POR-03`).

## Alternatives

| Option | Why not |
|---|---|
| Neo4j AuraDB Free now, as specified | 72-hour pause, no backups, inconsistent limits, a sync job and a dual-write consistency surface — all to serve traversal that is currently one hop |
| Apache AGE inside PostgreSQL | The best answer on the merits. Not available on Supabase Cloud. |
| Memgraph | Requires RAM sized to the graph and commercial licensing for real use |
| FalkorDB | Redis-module based; pulls in the dependency §4 excludes |
| KùzuDB | Abandoned October 2025 |
| Both adapters now | Doubles Phase 12 and leaves two traversal implementations to keep consistent |

## Consequences

**Gained.**

- One fewer datastore, no synchronization job, no dual-write consistency surface
- Scope filters come from the same repository base as every other query, which makes §64's "graph
  query without scope filters" test structurally hard to fail (`FR-GRA-13`)
- Graph edges and their evidence passages are joinable in a single query
- No 72-hour pause, no free-tier deletion risk on a derived store
- Provenance can be enforced by a `NOT NULL` constraint rather than by application discipline,
  which is a stronger guarantee for `NFR-GATE-06`

**Accepted cost.**

- No Cypher. Traversal logic is SQL, which is more verbose for path queries.
- Recursive CTEs degrade past roughly three levels on a large graph — acceptable at one hop, a real
  constraint if ADR-0010 is ever revised upward.
- Deviates from §22 and §65 as literally written. The deviation is recorded here rather than hidden.

## Revisit if

Phase 17 evaluation shows one-hop traversal is insufficient **and** the fix is depth rather than
extraction quality (see ADR-0010), or graph size grows past what bounded recursive CTEs serve within
`NFR-PERF-14`. Either condition triggers implementing the Neo4j adapter behind the existing port —
a contained change, by construction.
