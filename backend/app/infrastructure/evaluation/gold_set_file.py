"""Load a gold set from the JSON file it is maintained in.

A file rather than a table, because a gold set is edited by a person disagreeing with a
label, and reviewing that disagreement is a diff. It is also the input to a measurement
rather than a product of one, so it belongs beside the code it scores.

Everything is validated on the way in. A gold set that is quietly malformed does not
fail — it scores, and a wrong number looks exactly like a right one.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.enums import QueryClass
from app.domain.errors import InvariantViolationError
from app.domain.evaluation.entities import GoldPair, GoldSet


def load_gold_set(path: Path) -> GoldSet:
    """Read and validate one gold set file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvariantViolationError(f"{path.name} is not valid JSON: {exc}") from exc

    if "pairs" not in raw or "source" not in raw:
        raise InvariantViolationError(
            f"{path.name} must carry both 'source' and 'pairs' — a set that cannot say "
            "what it was written against scores fine against the wrong book"
        )

    return GoldSet(
        source=str(raw["source"]),
        pairs=tuple(_pair(entry, path.name) for entry in raw["pairs"]),
    )


def _sequence(value: object) -> list[object]:
    """Read a JSON list, refusing anything that only looks like one.

    A bare string is the mistake this catches: "gold_pages": "9" iterates into characters
    and produces a set of pages nobody wrote.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    raise InvariantViolationError(f"expected a list, got {type(value).__name__}: {value!r}")


def _pair(entry: dict[str, object], filename: str) -> GoldPair:
    pair_id = str(entry.get("id", ""))
    try:
        expected = QueryClass(str(entry["expected_class"]))
    except (KeyError, ValueError) as exc:
        # Naming a class that does not exist is how a gold set silently stops covering
        # what it claims to: the pair would be dropped, and the coverage count with it.
        raise InvariantViolationError(
            f"{filename}: pair {pair_id!r} names an unknown query class "
            f"{entry.get('expected_class')!r}"
        ) from exc

    return GoldPair(
        id=pair_id,
        question=str(entry.get("question", "")),
        expected_class=expected,
        document=str(entry.get("document", "")),
        gold_pages=frozenset(int(str(page)) for page in _sequence(entry.get("gold_pages"))),
        must_contain=tuple(str(phrase) for phrase in _sequence(entry.get("must_contain"))),
        note=str(entry.get("note", "")),
        unanswerable=bool(entry.get("unanswerable", False)),
    )
