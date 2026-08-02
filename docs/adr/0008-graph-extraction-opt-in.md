# ADR-0008 — Graph extraction opt-in per Knowledge Base

**Status:** Accepted · 2 August 2026
**Phase:** 12
**Requirements:** FR-KB-03, FR-GRA-12

## Context

§21 specifies graph extraction over parent sections. A 400-page textbook produces roughly 250
parent sections, each requiring a model call to extract candidate entities and relationships. On a
local Gemma 3 4B that is on the order of eight minutes of GPU time per document — during which the
GPU is unavailable for the answer model and the reranker.

Most student questions never touch the graph (ADR-0004). Paying that cost on every upload, for
every student, to serve a minority of queries is the wrong default.

## Decision

A `graph_enabled` flag on the Knowledge Base. `BUILD_GRAPH` is enqueued only when it is set.

Ingestion **always** produces chunks, embeddings and full-text indexes, so a Knowledge Base without
a graph is fully functional for every non-relationship question. Enabling the flag later triggers a
backfill job over existing documents.

## Alternatives

| Option | Why not |
|---|---|
| Always on at `BACKGROUND` priority | Never blocks chat, but still consumes GPU time on every upload for a feature most students will not use |
| Restrict extraction to headings, definitions and captions | Much cheaper, but weak coverage of the prose relationships that make the graph worth having |
| Always on, no gating | Worst case: a slow first ingestion for every student regardless of intent |

## Consequences

**Gained.** First ingestion is fast. The graph is fully functional when wanted. The cost is opt-in
and visible to the student who chooses it.

**Accepted cost.** A student who never enables the flag never discovers the concept graph. The
interface must surface it as an offer rather than hiding it behind a settings page — otherwise this
decision quietly removes a §2 objective.

Backfill must be idempotent and resumable, since it may run over a large existing corpus
(`NFR-REL-01`).

## Revisit if

Extraction becomes cheap enough to be effectively free — a much smaller extraction model, or
batched inference that fills otherwise-idle GPU time — or telemetry shows most Knowledge Bases
enable it anyway, in which case the default is simply wrong.
