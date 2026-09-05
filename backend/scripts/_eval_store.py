"""Save evaluation run results to a JSON file so regressions are detectable.

Satisfies NFR-OBS-05: evaluation results must be persisted per run so that a
score change between commits is attributed to a specific change in the code.

Each run is written to:
    evaluation/results/<script>/<YYYY-MM-DD>T<HH-MM-SS>-<sha8>.json

The JSON contains the script name, knowledge-base ID, gold-set source, git SHA,
timestamp, and a flat dict of metric scores.  A directory per script keeps the
listing manageable when many runs accumulate.

Intended use inside any evaluate_*.py script::

    from scripts._eval_store import save_run
    ...
    path = save_run(
        "retrieval",
        kb_id,
        gold.source,
        {"page_recall": 0.84, "ndcg": 0.71, "mrr": 0.68},
    )
    print(f"results saved to {path.relative_to(Path.cwd())}")
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

#: Root of all evaluation artefacts, two directories above this script.
_RESULTS_ROOT = Path(__file__).resolve().parent.parent.parent / "evaluation" / "results"


def _git_sha8() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=8", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return "unknown"


def save_run(
    script: str,
    kb_id: UUID,
    gold_source: str,
    scores: dict[str, float | int | str | None],
    *,
    results_dir: Path | None = None,
) -> Path:
    """Write one evaluation run to a timestamped JSON file and return its path.

    Parameters
    ----------
    script:
        Short identifier for the evaluation, e.g. ``"retrieval"`` or
        ``"generation"``.  Becomes the subdirectory name under *results_dir*.
    kb_id:
        The knowledge-base the run was measured against.
    gold_source:
        The ``GoldSet.source`` string — names what was being evaluated against.
    scores:
        Flat dict of metric name → value.  Values may be float, int, str or None;
        complex nested structures should be flattened before passing in.
    results_dir:
        Override the default output root.  Useful in tests.
    """
    root = results_dir or _RESULTS_ROOT
    out_dir = root / script
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    sha = _git_sha8()

    payload = {
        "script": script,
        "kb_id": str(kb_id),
        "gold_source": gold_source,
        "git_sha": sha,
        "timestamp": now.isoformat(),
        "scores": scores,
    }

    path = out_dir / f"{timestamp}-{sha}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_runs(script: str, *, results_dir: Path | None = None) -> list[dict]:
    """Return all persisted runs for *script*, oldest first."""
    root = results_dir or _RESULTS_ROOT
    run_dir = root / script
    if not run_dir.exists():
        return []
    runs: list[dict] = []
    for f in sorted(run_dir.glob("*.json")):
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return runs
