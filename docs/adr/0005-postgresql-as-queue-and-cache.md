# ADR-0005 — PostgreSQL as job queue and cache, not Redis

**Status:** Accepted · 2 August 2026
**Phase:** 2, 4, 16
**Requirements:** FR-JOB-01, FR-CCH-06, FR-CCH-07, NFR-REL-01, NFR-REL-02

## Context

The system needs a background job queue (ingestion, OCR, embeddings, graph building, compaction,
deletion) and a cache (parsing results, OCR output, embeddings, retrieval results, validated
answers). The conventional answer is Redis, usually with Celery.

§4 excludes Redis "unless a proven bottleneck requires it", and §67 restates that as a measurement
gate rather than a preference.

## Decision

PostgreSQL for both.

**Queue** — a `processing_jobs` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`, ordered by
priority then creation time, with `heartbeat_at` for lease reclamation, `attempt_count` for bounded
retry, and `INTERACTIVE` / `NORMAL` / `BACKGROUND` priorities.

**Cache** — an `UNLOGGED` `cache_entries` table with a partial index on expiry, swept by `pg_cron`.
`UNLOGGED` skips write-ahead logging entirely: much faster writes, contents lost on crash, which is
exactly correct for a cache.

## Alternatives

| Option | Why not |
|---|---|
| Redis + Celery | Excluded by §4 until measured. Adds a service, a serialization format, and a second failure mode. |
| `pgmq` | No native priority or heartbeat, which the §12 job model requires. Availability on Supabase Cloud unconfirmed. |
| Procrastinate | PostgreSQL-native and well built, but gives less control over the ~150 lines §12 already specifies. |
| `arq` / Dramatiq / RQ | All require Redis. |

## Consequences

**Gained.** One fewer system to run and monitor. Jobs are transactional with the data they operate
on — enqueueing a job and writing the row it refers to happen in one transaction, so a job can
never reference a record that was rolled back. Queue state is inspectable with ordinary SQL.

**Accepted cost.** Throughput ceiling is lower than Redis — irrelevant at this scale, relevant
eventually. Workers poll rather than receive push notifications.

**Known limitation (R-02).** `pg_cron` runs inside the database and does **not** count as external
activity for Supabase's inactivity pause. It is fine for cache sweeping and compaction scheduling,
but it cannot serve as a keepalive.

## Revisit if

Measurement — not intuition — shows PostgreSQL is the bottleneck for queue throughput or cache
latency. §67 makes this an explicit gate.
