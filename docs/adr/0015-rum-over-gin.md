# ADR-0015 — `rum` over GIN for full-text indexes

**Status:** Accepted · 2 August 2026 · Refines §65
**Phase:** 2, 9
**Requirements:** FR-IDX-07, FR-RET-01, NFR-PERF-07

## Context

§65 specifies "PostgreSQL full-text search" without naming an index type. GIN is the default choice
for `tsvector`.

Keyword retrieval carries specific weight in this design. §27 relies on it for exact names, formula
notation, identifiers, rare technical terms and table values — the cases where dense retrieval is
weakest. Ranking quality on that path matters more than it would in a general search feature.

Two facts shaped the choice:

- **GIN does not store lexeme positions.** Ranking with `ts_rank_cd` requires fetching each
  candidate row from the heap, so ranking cost scales with match count.
- **`ts_rank` is not BM25.** It has no term-frequency saturation and no document-length
  normalisation, so a long chunk mentioning a term repeatedly outranks a short, precise one.

ParadeDB's `pg_search` provides genuine BM25 inside PostgreSQL and would be the better answer — but
it is **not among Supabase Cloud's 64 approved extensions**. Neither is `pgvectorscale`. `rum` and
`pgroonga` are both available.

## Decision

Use `rum` indexes for all `tsvector` columns.

RUM stores lexeme positions inside the index and can rank within it, so `ts_rank_cd` avoids heap
access. Ordering quality improves and ranking latency drops.

The `ts_rank` / BM25 gap is **mitigated by design rather than by the index**: §28 fuses ranked lists
using Reciprocal Rank Fusion, which consumes **ranks, not scores**. Poor score calibration matters
much less when only the ordering feeds fusion — RRF was already the right architecture for this, and
it happens to absorb this limitation.

## Alternatives

| Option | Why not |
|---|---|
| GIN (the default) | No in-index ranking; `ts_rank_cd` requires heap access per candidate |
| `pg_search` (ParadeDB BM25) | Genuinely better ranking. Not available on Supabase Cloud. |
| `pgroonga` | Available, but aimed at CJK and multi-language search; the corpus is English-only (D-18) |
| Elasticsearch / OpenSearch | Excluded by §4 |
| Trigram similarity (`pg_trgm`) alone | Good for fuzzy matching, wrong tool for ranked full-text retrieval |

## Consequences

**Gained.** Faster and better-ordered `ts_rank_cd`, contributing to the retrieval half of
`NFR-PERF-07`. No deviation from §65 — this is still PostgreSQL full-text search.

**Accepted cost.** RUM indexes are larger on disk and slower to build than GIN, and they perform
poorly under update-heavy workloads. Neither matters here: chunks are **write-once** after
ingestion, which is precisely the workload RUM is designed for. Index size counts against the
database budget in `NFR-CAP-02` and should be measured in Phase 7.

## Revisit if

`pg_search` becomes available on Supabase Cloud — in which case real BM25 is worth a migration, and
this ADR is superseded. Or index size becomes a database capacity problem, in which case GIN is the
fallback and RRF absorbs the ranking difference.
