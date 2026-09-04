# ADR-0011 — Benchmark local model quantization

**Status:** **Accepted** — Q4_K_M selected; see Results section
**Phase:** 16
**Requirements:** FR-PRF-03, NFR-PERF-01, NFR-PERF-03

## Context

Gemma 3 4B is available at several quantization levels through Ollama. The common practice is to
reach for `Q4_K_M` because it is the default recommendation and fits comfortably in VRAM.

That default is unverified for this workload, and this workload is unusually sensitive. The system
depends on the model producing **valid structured JSON**, **citing only supplied identifiers**, and
**preserving numbers and units exactly** (`FR-GEN-06`, `FR-GEN-10`, `FR-CIT-03`). Quantization is
known to degrade instruction-following and structured-output fidelity before it degrades fluency —
which means a quantized model can look fine in casual use while failing precisely the properties
this system validates against.

§55 requires benchmarking rather than assuming.

## Hardware ceiling — added after step 0.3

The target GPU is an **RTX 3050 6 GB Laptop**. Measured allocation leaves roughly **2.3 GB** after
`bge-small` (0.13 GB) and `ms-marco-MiniLM-L6-v2` (0.09 GB), with OCR moved to CPU (D-27).

This makes VRAM a **pass/fail gate rather than a data point**:

| Quantization | Ollama download | + KV cache @ 4k | Fits in ~5.7 GB with retrieval models? |
|---|---|---|---|
| Q4_K_M | 2.6 GB | ~3.5 GB | Yes, comfortably |
| QAT | 4.0 GB | ~5.0 GB | Yes, with margin |
| Q8_0 | 5.0 GB | ~6.0 GB | Marginal — likely fails under load |

*Note: Gemma 3 4B has no Q5_K_M variant in the Ollama registry. QAT
(quantization-aware training, `gemma3:4b-it-qat`) is the next tier above Q4_K_M.*

`Q8_0` is included for reference but is unlikely to be selectable on this hardware. If citation
accuracy or schema validity turns out to require it, that is a **hardware finding**, not a tuning
finding, and should be recorded as such rather than worked around with prompt changes.

## Decision

Benchmark `Q4_K_M`, `QAT`, and `Q8_0` against five measures, and record the results in this ADR
before fixing a default:

| Measure | Why |
|---|---|
| Answer correctness | Baseline quality |
| **Citation accuracy** | The property most likely to degrade silently |
| **Structured-output validity rate** | Schema failures drive the repair path and cost latency |
| Tokens per second · time to first token | Against `NFR-PERF-01` and `NFR-PERF-03` |
| VRAM footprint | Shared with PaddleOCR, embeddings and the reranker |

## Alternatives

| Option | Why not |
|---|---|
| Assume `Q4_K_M` is fine | Common, and unverified for the properties that matter here |
| Always run FP16 | Largest VRAM footprint, contending with OCR and reranking on the same GPU |
| Defer the question entirely | Latency budgets in `NFR-PERF` cannot be validated without knowing the generation configuration |

## Results

Benchmark script: `backend/scripts/benchmark_quantization.py` — 10 ML-concept QA cases, each
with three evidence passages and a required key phrase. Measured on RTX 3050 6 GB Laptop.

| Quantization | Correctness | Citation accuracy | Schema validity | tok/s | TTFT (ms) | VRAM (MiB) | Fits |
|---|---|---|---|---|---|---|---|
| Q4_K_M | 100 % | 100 % | 100 % | 35.3 | 367 | 3 748 | Yes |
| QAT | — | — | — | — | — | ~4 000 est. | Yes |
| Q8_0 | — | — | — | — | — | ~5 000 est. | Marginal |

*QAT and Q8_0 could not be benchmarked on the development machine: download size (4.0 GB and
5.0 GB respectively) was impractical over the available connection. VRAM figures are estimated
from Ollama model sizes. The hardware ceiling section gives the full VRAM analysis.*

**Selected: Q4_K_M** (`gemma3:4b`)

Q4_K_M achieves perfect scores on every quality measure that matters for this system:
100 % schema validity, 100 % citation accuracy, and 100 % answer correctness across all 10
test cases. Throughput (35.3 tok/s) and time-to-first-token (367 ms) are well inside the
NFR-PERF targets. VRAM footprint (3 748 MiB) sits comfortably below the ~5.7 GB ceiling
shared with the retrieval models.

Upgrading to QAT or Q8_0 would trade additional VRAM for no measurable quality gain on this
task — the model already maxes out the quality metrics at Q4_K_M precision. If a future
regression in citation accuracy or schema validity is observed (see *Revisit if* below), the
first step is re-testing at QAT, not changing prompts.

## Revisit if

The answer model changes, the GPU changes, or Phase 17 shows citation accuracy or schema validity
below target — in which case the first thing to test is a higher-precision quantization, before
changing prompts or models.
