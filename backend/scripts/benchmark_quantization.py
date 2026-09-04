"""Benchmark Q4_K_M, Q5_K_M and Q8_0 quantizations of Gemma 3 4B.

Measures, per quantization level:
  - Schema validity rate   (output parses against the answer JSON schema)
  - Citation accuracy      (cited labels are a subset of the supplied labels)
  - Answer correctness     (answer contains an expected key phrase)
  - Tokens per second      (Ollama eval_count / eval_duration)
  - Time to first token    (streaming: wall time from request to first token)
  - VRAM footprint         (nvidia-smi at generation time)

Usage (from the backend/ directory):
    PYTHONUTF8=1 python scripts/benchmark_quantization.py

The script pulls Q5_K_M and Q8_0 if they are not already present, then runs
the benchmark. Copy the printed table into docs/adr/0011-quantization-benchmark.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Allow importing app modules when running from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domain.errors import GenerationParseError
from app.domain.models.generation import OUTPUT_SCHEMA, parse_generated_answer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OLLAMA_BASE = "http://127.0.0.1:11434"
TIMEOUT = 180  # seconds

# Model tags to benchmark. Gemma 3 4B has no Q5_K_M variant in the Ollama
# registry; QAT (quantization-aware training, 4.0 GB) is used in its place —
# it sits between Q4_K_M and Q8_0 in size and is trained to minimise the
# accuracy loss from quantization. Q8_0 at 5.0 GB is marginal on 6 GB VRAM.
MODELS: list[tuple[str, str]] = [
    ("Q4_K_M", "gemma3:4b"),
    ("QAT",    "gemma3:4b-it-qat"),
    ("Q8_0",   "gemma3:4b-it-q8_0"),
]

# ---------------------------------------------------------------------------
# Benchmark cases
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a concise educational assistant. "
    "Answer the student's question using only the supplied passages. "
    "Do not add information not present in the passages."
)

TASK_INSTRUCTIONS = (
    "Answer the question in two to four sentences using only the evidence below. "
    "Respond with valid JSON matching the schema exactly."
)


@dataclass(frozen=True)
class Case:
    question: str
    passages: list[tuple[str, str]]  # (label, text)
    must_contain: str                 # expected key phrase (case-insensitive)


CASES: list[Case] = [
    Case(
        question="What is supervised learning?",
        passages=[
            ("[S1]", "Supervised learning is a type of machine learning where a model is trained on labelled examples."),
            ("[S2]", "Each training example consists of an input and the correct output, called the label."),
            ("[S3]", "After training, the model predicts labels for new, unseen inputs."),
        ],
        must_contain="labelled",
    ),
    Case(
        question="What is gradient descent used for?",
        passages=[
            ("[S1]", "Gradient descent is an optimisation algorithm used to minimise a loss function."),
            ("[S2]", "It iteratively adjusts model parameters in the direction opposite to the gradient of the loss."),
            ("[S3]", "Learning rate controls the size of each step taken during gradient descent."),
        ],
        must_contain="gradient",
    ),
    Case(
        question="What does a confusion matrix show?",
        passages=[
            ("[S1]", "A confusion matrix displays the counts of true positives, false positives, true negatives, and false negatives."),
            ("[S2]", "It is used to evaluate the performance of a classification model on a test dataset."),
            ("[S3]", "Precision and recall can both be derived from the confusion matrix."),
        ],
        must_contain="confusion matrix",
    ),
    Case(
        question="What is cross-validation?",
        passages=[
            ("[S1]", "Cross-validation is a technique for estimating how well a model generalises to an independent dataset."),
            ("[S2]", "In k-fold cross-validation, the data is split into k subsets, and the model is trained and evaluated k times."),
            ("[S3]", "Each fold serves as the test set once, while the remaining folds form the training set."),
        ],
        must_contain="cross-validation",
    ),
    Case(
        question="What is the purpose of regularisation in machine learning?",
        passages=[
            ("[S1]", "Regularisation adds a penalty term to the loss function to discourage overly complex models."),
            ("[S2]", "L1 regularisation (Lasso) can drive some model weights to exactly zero, performing feature selection."),
            ("[S3]", "L2 regularisation (Ridge) penalises large weights without eliminating them."),
        ],
        must_contain="regularisation",
    ),
    Case(
        question="What is a decision tree?",
        passages=[
            ("[S1]", "A decision tree is a hierarchical model that splits data based on feature values at each node."),
            ("[S2]", "Leaf nodes represent the final predictions of the model."),
            ("[S3]", "Decision trees are prone to overfitting when they grow too deep."),
        ],
        must_contain="decision tree",
    ),
    Case(
        question="What is the bias-variance tradeoff?",
        passages=[
            ("[S1]", "Bias measures how far the model's predictions are from the true values on average."),
            ("[S2]", "Variance measures how much the model's predictions change with different training datasets."),
            ("[S3]", "A high-bias model underfits, while a high-variance model overfits."),
        ],
        must_contain="bias",
    ),
    Case(
        question="How does a support vector machine separate classes?",
        passages=[
            ("[S1]", "A support vector machine finds the hyperplane that maximises the margin between classes."),
            ("[S2]", "Support vectors are the training examples closest to the decision boundary."),
            ("[S3]", "The kernel trick allows SVMs to classify non-linearly separable data."),
        ],
        must_contain="margin",
    ),
    Case(
        question="What is a neural network activation function?",
        passages=[
            ("[S1]", "An activation function introduces non-linearity into a neural network."),
            ("[S2]", "ReLU returns zero for negative inputs and the input value for positive inputs."),
            ("[S3]", "Without activation functions, a neural network is equivalent to a linear model."),
        ],
        must_contain="activation",
    ),
    Case(
        question="What is transfer learning?",
        passages=[
            ("[S1]", "Transfer learning reuses a model trained on one task as the starting point for a different but related task."),
            ("[S2]", "This is especially useful when the target task has limited labelled data."),
            ("[S3]", "The initial layers of a pre-trained model often capture generic features that transfer across domains."),
        ],
        must_contain="transfer learning",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_prompt(case: Case) -> list[dict[str, str]]:
    """Assemble the chat messages for one benchmark case."""
    evidence = "\n".join(f"{label}: {text}" for label, text in case.passages)
    supplied_labels = {label for label, _ in case.passages}

    user_content = (
        f"{TASK_INSTRUCTIONS}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"Question: {case.question}"
    )
    schema_content = f"[Required output format]\n{OUTPUT_SCHEMA}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
        {"role": "user",   "content": schema_content},
    ], supplied_labels


def _vram_mb() -> int | None:
    """Query nvidia-smi for current GPU memory usage in MiB. Returns None on failure."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        return int(out.strip().splitlines()[0].strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-model benchmark
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    schema_valid: int = 0
    citation_clean: int = 0   # valid parses where all citations are in-set
    correct: int = 0          # answers containing must_contain phrase
    total: int = 0
    tok_per_sec: list[float] = None  # type: ignore[assignment]
    ttft_ms: list[float] = None      # type: ignore[assignment]
    vram_mb: int | None = None

    def __post_init__(self) -> None:
        if self.tok_per_sec is None:
            self.tok_per_sec = []
        if self.ttft_ms is None:
            self.ttft_ms = []


def _pull_model(client: httpx.Client, tag: str) -> bool:
    """Pull `tag` if not already present. Returns True on success."""
    tags_resp = client.get("/api/tags", timeout=10)
    present = {m["name"] for m in tags_resp.json().get("models", [])}
    if tag in present:
        return True
    print(f"  pulling {tag} …", end=" ", flush=True)
    try:
        with client.stream(
            "POST", "/api/pull", json={"name": tag, "stream": True}, timeout=600
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("status") == "success":
                    print("done")
                    return True
    except Exception as exc:
        print(f"FAILED ({exc})")
        return False
    return False


def _run_case_streaming(
    client: httpx.Client, tag: str, case: Case
) -> tuple[str, float, float]:
    """Return (full_text, ttft_ms, tok_per_sec)."""
    messages, _ = _build_prompt(case)
    payload = {
        "model": tag,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    tokens: list[str] = []
    ttft_ms = 0.0
    tok_per_sec = 0.0
    t0 = time.monotonic()
    first_token = True
    with client.stream("POST", "/api/chat", json=payload, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.strip():
                continue
            data = json.loads(line)
            token: str = data.get("message", {}).get("content", "")
            if token:
                if first_token:
                    ttft_ms = (time.monotonic() - t0) * 1000
                    first_token = False
                tokens.append(token)
            if data.get("done"):
                eval_count = data.get("eval_count", 0)
                eval_duration_ns = data.get("eval_duration", 0)
                if eval_duration_ns > 0:
                    tok_per_sec = eval_count / (eval_duration_ns / 1e9)
                break
    return "".join(tokens), ttft_ms, tok_per_sec


def _run_model(client: httpx.Client, tag: str, quant: str) -> RunResult | None:
    print(f"\n{'─'*60}")
    print(f"  {quant}  ({tag})")
    print(f"{'─'*60}")

    if not _pull_model(client, tag):
        print(f"  ✗ could not pull — skipped")
        return None

    # Warm the model with a minimal request before timing
    print("  warming up …", end=" ", flush=True)
    try:
        client.post(
            "/api/chat",
            json={
                "model": tag,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "options": {"num_predict": 4},
            },
            timeout=TIMEOUT,
        ).raise_for_status()
    except Exception as exc:
        print(f"FAILED ({exc}) — skipped")
        return None
    print("done")

    vram = _vram_mb()

    result = RunResult(vram_mb=vram)

    for i, case in enumerate(CASES, 1):
        messages, supplied_labels = _build_prompt(case)
        print(f"  [{i:02d}/{len(CASES)}] {case.question[:55]:<55}", end=" ", flush=True)
        try:
            raw, ttft_ms, tps = _run_case_streaming(client, tag, case)
        except Exception as exc:
            print(f"ERROR: {exc}")
            result.total += 1
            continue

        result.total += 1
        result.ttft_ms.append(ttft_ms)
        if tps > 0:
            result.tok_per_sec.append(tps)

        # Schema validity
        parsed = None
        try:
            parsed = parse_generated_answer(raw)
            result.schema_valid += 1
        except GenerationParseError as exc:
            print(f"PARSE_FAIL ({exc})", end=" ")

        if parsed is not None:
            # Citation accuracy: every cited label must be in the supplied set
            all_cited = {c for claim in parsed.claims for c in claim.citations}
            if all_cited.issubset(supplied_labels):
                result.citation_clean += 1
            else:
                bad = all_cited - supplied_labels
                print(f"BAD_CITE({bad})", end=" ")

            # Correctness: must_contain phrase in answer (case-insensitive)
            if case.must_contain.lower() in parsed.answer.lower():
                result.correct += 1

        print("✓")

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "—"
    return f"{100 * n // d}%"


def _avg(xs: list[float]) -> str:
    if not xs:
        return "—"
    return f"{sum(xs) / len(xs):.1f}"


def _print_table(results: list[tuple[str, str, RunResult | None]]) -> None:
    print("\n")
    print("=" * 90)
    print("RESULTS")
    print("=" * 90)
    header = f"{'Quant':<8}  {'Correct':>9}  {'Schema':>8}  {'Citation':>10}  {'tok/s':>7}  {'TTFT ms':>9}  {'VRAM MiB':>10}  {'Fits':>6}"
    print(header)
    print("-" * 90)
    for quant, _tag, r in results:
        if r is None:
            print(f"{quant:<8}  {'—':>9}  {'—':>8}  {'—':>10}  {'—':>7}  {'—':>9}  {'—':>10}  {'no':>6}")
            continue
        fits = "yes" if r.vram_mb is not None and r.vram_mb < 6000 else ("?" if r.vram_mb is None else "check")
        print(
            f"{quant:<8}  "
            f"{_pct(r.correct, r.total):>9}  "
            f"{_pct(r.schema_valid, r.total):>8}  "
            f"{_pct(r.citation_clean, r.schema_valid):>10}  "
            f"{_avg(r.tok_per_sec):>7}  "
            f"{_avg(r.ttft_ms):>9}  "
            f"{str(r.vram_mb) + ' MiB' if r.vram_mb else '—':>10}  "
            f"{fits:>6}"
        )
    print("=" * 90)
    print()
    print("Columns:")
    print("  Correct  — answer contains the expected key phrase (proxy for factual accuracy)")
    print("  Schema   — response parsed against the structured JSON schema")
    print("  Citation — cited labels are all within the supplied set (no invented labels)")
    print("  tok/s    — Ollama eval_count / eval_duration (generation throughput)")
    print("  TTFT ms  — wall time from request to first token (streaming)")
    print("  VRAM     — GPU memory used at generation time (nvidia-smi)")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("Quantization benchmark — Gemma 3 4B")
    print(f"Ollama: {OLLAMA_BASE}")
    print(f"Cases:  {len(CASES)}")
    print()

    with httpx.Client(base_url=OLLAMA_BASE) as client:
        try:
            client.get("/api/tags", timeout=5).raise_for_status()
        except Exception as exc:
            print(f"ERROR: cannot reach Ollama at {OLLAMA_BASE}: {exc}")
            sys.exit(1)

        results: list[tuple[str, str, RunResult | None]] = []
        for quant, tag in MODELS:
            r = _run_model(client, tag, quant)
            results.append((quant, tag, r))

    _print_table(results)


if __name__ == "__main__":
    main()
