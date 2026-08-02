# ADR-0007 — HyDE disabled by default

**Status:** Accepted · 2 August 2026
**Phase:** 9
**Requirements:** FR-QRY-08

## Context

HyDE (Hypothetical Document Embeddings) asks a model to write a plausible answer to the query, then
embeds that hypothetical answer instead of the question. It often improves recall, because the
generated text is lexically closer to the passages being searched than a short question is.

The corpus here is educational material where exact terminology carries meaning. A hypothetical
answer that invents a plausible-sounding but wrong term — a nearby concept, a synonym the textbook
does not use, a mis-stated unit — shifts the query vector *away* from the correct chunks, and does
so invisibly.

It also costs a generation call on the latency-critical path, before retrieval can begin.

## Decision

HyDE is not enabled by default. Query expansion uses bounded paraphrase variants instead — 2–3
variants, maximum 4 total queries, temperature 0 (`FR-QRY-06`), which stays anchored to the
student's own wording.

## Alternatives

| Option | Why not |
|---|---|
| HyDE on by default | Terminology drift is a silent failure mode in exactly the corpus where terminology matters most |
| HyDE for abstract query classes only | Defensible, but adds a routing rule with no evidence yet that it helps. Phase 17 can produce that evidence. |

## Consequences

**Gained.** Retrieval stays anchored to the student's actual terminology. One fewer model call
before retrieval. Query expansion at temperature 0 is reproducible; HyDE is not.

**Accepted cost.** May underperform on genuinely abstract or poorly-worded questions where the
student does not know the right vocabulary — which is a real scenario for a learning tool.

## Revisit if

Phase 17 retrieval evaluation shows a recall gap on abstract or conceptual queries that bounded
expansion does not close. If so, enable HyDE **for those query classes only**, and measure
terminology drift explicitly rather than assuming it is absent.
