# ADR-0014 — Page renders as regenerable cache

**Status:** Accepted · 2 August 2026 · **Deviates from §60 as written**
**Phase:** 4, 5, 16
**Requirements:** FR-ING-19, NFR-CAP-01, NFR-CAP-03

## Context

§60 lists page renders among the artifacts stored in object storage, alongside originals and crops.

Page renders are produced by `pypdfium2` at roughly 200 DPI as **input to OCR**. At that resolution
a letter page is about 250 KB, so a 400-page textbook produces around 100 MB of renders — more than
half of its total storage footprint, and by a wide margin the largest single artifact class.

Examining what actually consumes them:

| Consumer | Needs a stored render? |
|---|---|
| OCR during ingestion | Transiently, during the job |
| PDF.js viewer | **No** — renders client-side from the original |
| Citation bounding-box highlight | **No** — PDF.js overlays on its own render |
| Multimodal visual questions | **No** — uses the *crop*, not the full page |

Nothing consumes a stored page render after ingestion completes.

## Decision

Page renders are written to a **TTL-bounded cache prefix** and regenerated on demand, not stored
permanently.

Table, figure, chart and diagram **crops remain permanent**, because §18 requires re-sending the
real crop to the multimodal model for visual questions (`FR-VIS-06`). Crops are small and read
often — exactly the opposite profile from full-page renders.

## Alternatives

| Option | Why not |
|---|---|
| Store renders permanently, as §60 says | More than half the storage budget spent on artifacts nothing reads after ingestion |
| Never persist renders at all | Re-running OCR on a single page would require re-rendering; a short-lived cache makes page-level retry (`NFR-REL-08`) cheap |
| Store at lower resolution | Degrades OCR accuracy — the one thing the renders exist for |
| Also treat crops as regenerable | Regenerating a crop needs the original, the page render and the bounding box; it is three steps to recover a 60 KB object that is read on every visual question |

## Consequences

**Gained.** Permanent storage per textbook drops from roughly 175 MB to 50–100 MB — the difference
between 5–8 textbooks and 12–20 within the same budget. Directly satisfies `NFR-CAP-01`.

**Accepted cost.** Reprocessing a document after cache expiry pays a re-render. Rendering is fast
and local, so this is cheap; but it means reprocessing cost is not constant, and a bulk reprocess
of an old document is slower than of a recent one.

Deviates from §60 as written. The deviation is a storage-tier change, not a behavioural one — every
artifact §60 names still exists when needed.

## Revisit if

Re-render cost shows up as a measured bottleneck during bulk reprocessing, or a future feature needs
full-page images after ingestion — server-side thumbnails, or a page-level visual model that
operates on whole pages rather than crops.
