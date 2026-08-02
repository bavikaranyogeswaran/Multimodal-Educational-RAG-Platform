# ADR-0013 — Cloudflare R2 over Supabase Storage

**Status:** Accepted · 2 August 2026 · **Deviates from §60 and §65 as written**
**Phase:** 4
**Requirements:** FR-DOC-06, NFR-CAP-01, NFR-POR-02, **NFR-PRV-06**

## Context

§60 and §65 name Supabase Storage. The Supabase free tier provides **1 GB of file storage and 5 GB
of egress per month**.

Sizing one 400-page textbook against that:

| Artifact | Size |
|---|---|
| Original PDF | 20–80 MB |
| Page renders at 200 DPI | ~100 MB |
| Table and figure crops | ~25 MB |
| **Total** | **~150–200 MB** |

That is **5–8 textbooks** before the ceiling. Egress binds sooner: PDF.js downloads the original
document **every time a student opens it**, so a 50 MB textbook opened twice a day exhausts 5 GB in
about seven weeks.

Cloudflare R2 provides 10 GB free with **zero egress fees**, and is S3-compatible — presigned URLs
work the same way.

## Decision

Object storage is Cloudflare R2, behind the existing `StoragePort`. Layout is unchanged:
`{user_id}/{knowledge_base_id}/{document_id}/original.pdf`, private bucket, signed URLs only.

Combined with ADR-0014, permanent storage per textbook falls to roughly 50–100 MB.

## Data custody — stated plainly

**This decision does not make the system more private, and this document must not imply that it
does.** `NFR-PRV-06` requires the custody posture to be recorded honestly, so:

§52 declares `data_boundary: local` and the local-inference default exists so that "private
documents do not need to be sent to external providers". Under this deployment, prompts stay local
— but **every original PDF, every OCR'd chunk, every conversation message and every memory fact
resides with third parties**: Supabase for structured data, Cloudflare for files.

That is a **strictly larger disclosure** than the one local inference avoids. Local inference sends
excerpts to a model provider; this sends the entire corpus to a storage provider.

It is accepted **for convenience**, not because it is privacy-preserving. A fully local package —
local PostgreSQL with pgvector, local filesystem storage, self-issued JWT authentication — remains
reachable behind the same ports (`NFR-POR-02`, `NFR-POR-04`) and is the correct choice if the
privacy posture is ever treated as binding rather than aspirational.

## Alternatives

| Option | Why not |
|---|---|
| Supabase Storage as specified | 1 GB ceiling at 5–8 textbooks; 5 GB monthly egress exhausted by ordinary reading |
| AWS S3 | Egress charged per GB — the worst fit for a render- and re-read-heavy workload |
| Backblaze B2 | Free egress via Cloudflare only; more moving parts than R2 alone |
| Local filesystem | No ceilings and honest about custody, but needs a deployment story and loses signed-URL delivery |
| MinIO self-hosted | S3-compatible and local, but an additional service to run — and containers are excluded |

## Consequences

**Gained.** Ten times the storage, unmetered egress, and one adapter's worth of work. The two hard
capacity ceilings identified in risk R-03 are removed.

**Accepted cost.** Supabase Storage's bucket-level RLS policies are lost. This is acceptable rather
than ideal: §10 and §11 already perform the ownership check in the backend *before* minting a signed
URL, so bucket policy was defence-in-depth, not the primary control. Signed-URL expiry
(`NFR-SEC-05`) becomes the sole storage-layer boundary and must therefore be short.

A second provider account and credential set to manage.

## Revisit if

The privacy posture becomes binding — in which case `StoragePort` switches to a filesystem or MinIO
adapter and this ADR is superseded rather than amended. Or R2's free tier changes materially.
