# ADR-0001 — No PyMuPDF

**Status:** Accepted · 2 August 2026
**Phase:** 5
**Requirements:** FR-ING-02, FR-ING-04

## Context

PyMuPDF (`fitz`) is the fastest and most capable Python PDF library available. It handles text
extraction with layout, page rendering, image extraction and region cropping in a single dependency
— exactly the four things this ingestion pipeline needs.

It is licensed AGPL-3.0, with a commercial licence available from Artifex. AGPL obligations extend
to network-accessible services, which makes it unsuitable for some distribution models. The
distribution model for this system is not yet fixed.

## Decision

Do not use PyMuPDF. Use three permissively licensed libraries instead:

| Library | Role | Licence |
|---|---|---|
| `pypdf` | Metadata, basic native text | BSD-3-Clause |
| `pdfplumber` | Layout, blocks, table detection | MIT |
| `pypdfium2` | Page and region rendering | Apache-2.0 / BSD-3-Clause (PDFium) |

## Alternatives

| Option | Why not |
|---|---|
| PyMuPDF | AGPL-3.0 obligations may be incompatible with the eventual distribution model |
| PyMuPDF under commercial licence | Cost, and a licensing dependency taken before it is needed |
| `pdfminer.six` alone | No rendering; substantially slower on large documents |
| `PyPDF2` | Deprecated in favour of `pypdf` |

## Consequences

**Accepted cost.** Three dependencies where one would do, and integration work to make their
coordinate systems and page indexing agree. `pdfplumber` is slower than PyMuPDF on large documents.

**Gained.** No copyleft obligation on the eventual distribution model, and no licence-driven
rewrite later. `pypdfium2` wraps PDFium, the renderer in Chrome — rendering fidelity is not a
compromise.

## Revisit if

The distribution model is settled as something AGPL permits (a purely internal, non-distributed
deployment), or a commercial licence is acquired for another reason. Rendering fidelity or parsing
accuracy is **not** a reason to revisit; `pypdfium2` and `pdfplumber` are adequate.
