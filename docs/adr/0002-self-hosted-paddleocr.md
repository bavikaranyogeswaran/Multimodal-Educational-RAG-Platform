# ADR-0002 — Self-hosted PaddleOCR, not cloud OCR

**Status:** Accepted · 2 August 2026
**Phase:** 5
**Requirements:** FR-ING-09, FR-ING-10, FR-ING-11, FR-ING-12, FR-ING-13, NFR-PRV-01

## Context

Scanned pages and visual labels require OCR. The realistic options are a hosted OCR API or a
self-hosted engine.

The system's stated privacy posture is that private study material should not need to leave the
machine for processing (§1, §52). Sending every scanned page of a student's textbook to a cloud OCR
endpoint contradicts that directly — and OCR touches *more* of the corpus than the answer model
does, since every page is OCR'd but only retrieved evidence reaches the LLM.

## Decision

Self-hosted PaddleOCR, GPU-accelerated.

- **Primary:** PaddleOCR, PP-OCRv6 family
- **Complex-layout fallback:** PaddleOCR-VL, triggered only by the §15 conditions — dense tables,
  formulas, multiple columns, rotated content, complex reading order, low ordinary confidence
- **Emergency fallback only:** Tesseract

The heavier VL model must not run on every page (`FR-ING-12`, `NFR-PERF-17`).

## Alternatives

| Option | Why not |
|---|---|
| Baidu Cloud OCR | External data transfer, provider quotas, pricing changes, privacy exposure, data-residency concerns |
| Google Cloud Vision / Azure Document Intelligence | Same class of concern; better SLAs, same fundamental objection |
| Tesseract as primary | Markedly worse on multi-column layouts, tables and low-quality scans |
| EasyOCR / docTR | Viable, but weaker table and layout handling than the PaddleOCR family |

## Consequences

**Gained.** No per-page cost, no quota, no rate limit, and no page of a student's textbook leaves
the machine during ingestion. The model version is pinned rather than changing under us.

**Accepted cost.** GPU memory shared with the answer model and reranker. Installation on Windows is
the most fragile part of the environment (see risk R-04). Model weights must be managed and are
excluded from source control.

## Revisit if

The privacy rationale does not expire, so the *self-hosted* part is not up for revision. The
**fallback model choice** may change if PaddleOCR-VL proves unworkable on the target platform — a
different locally-hosted vision model would satisfy this ADR equally.
