# ADR-0009 — Provider-agnostic model gateway

**Status:** Accepted · 2 August 2026
**Phase:** 8
**Requirements:** FR-MDL-01 … FR-MDL-26, NFR-PRV-01, NFR-PRV-02, NFR-POR-01, NFR-MNT-03

## Context

The system makes model calls for ten distinct tasks with different requirements — query rewriting
needs speed, visual questions need image input, faithfulness checking needs a different model than
answer generation, graph extraction needs structured output.

It must also enforce a hard privacy rule: private documents must not reach a provider whose data
boundary forbids them (§52). A rule enforced at every call site is a rule that will eventually be
missed at one call site.

## Decision

All model execution passes through a single gateway:

```
application → gateway → task router → capability registry → privacy pre-flight → provider adapter
```

Three properties are non-negotiable:

1. **Internal model keys.** Application code names `default_text_model`, never `gemma3:4b`.
   Provider model names exist only in configuration (`NFR-MNT-03`).
2. **Privacy is pre-flight and central.** The `data_boundary` check happens before the prompt is
   assembled, in one place. A forbidden combination **raises** — there is no silent reroute
   (`FR-MDL-17`).
3. **Fallback is explicit.** Capability check → call → retryable classification → one retry →
   approved fallback. Non-retryable errors fail immediately. Every fallback is logged.

Ollama and an OpenAI-compatible adapter are implemented; the latter covers vLLM and llama.cpp
servers. Gemini and Anthropic adapters exist against the interface but raise until credentials
exist (D-17).

## Alternatives

| Option | Why not |
|---|---|
| Direct provider SDK calls | Scatters model names through application code and makes the §52 privacy check unenforceable — it becomes a convention at N call sites |
| A thin `chat()` wrapper | Does not give capability negotiation, task routing, or a single place for the boundary check |
| A framework's provider abstraction | See ADR-0003; and none of them model a data boundary |

## Consequences

**Gained.** Swapping the answer model is a configuration change (`NFR-POR-01`). The privacy rule
has exactly one enforcement point. Every invocation is measurable in one place, which is what makes
`FR-MDL-26` and the §62 model metrics possible at all.

**Accepted cost.** An indirection layer to maintain, and provider-specific capabilities are only
reachable if the capability registry models them.

## Revisit if

Not applicable. This boundary is load-bearing for §52 — removing it removes the ability to enforce
the privacy policy at all.
