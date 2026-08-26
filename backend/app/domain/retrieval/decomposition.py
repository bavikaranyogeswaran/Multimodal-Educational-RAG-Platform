"""Sub-question entities for multi-hop query decomposition.

A complex query — one spanning multiple documents, requiring chain-of-thought
reasoning, or comparing multiple concepts — is broken into ordered sub-questions
before retrieval begins. Each sub-question maps to one full retrieval pipeline run.

DecompositionPlan.build enforces:
  - unique sub-question IDs
  - no dangling depends_on references
  - no dependency cycles
  - topological ordering so callers can iterate in execution order
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Self

from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_non_blank


@dataclass(frozen=True, slots=True)
class SubQuestion:
    """One retrievable piece of a decomposed query.

    `id` is a stable short key (e.g. "Q1") produced by the decomposer and
    referenced in `depends_on`. `depends_on` names the ids of sub-questions that
    must be answered before this one executes, so that a synthesis step can use
    earlier sub-answers as context when building the next retrieval query.
    """

    id: str
    text: str
    depends_on: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        require_non_blank(self.id, "id")
        require_non_blank(self.text, "text")
        if self.id in self.depends_on:
            raise InvariantViolationError(
                f"sub-question {self.id!r} cannot depend on itself"
            )


@dataclass(frozen=True, slots=True)
class DecompositionPlan:
    """A validated, topologically sorted decomposition of a complex query.

    `sub_questions` are guaranteed to be in dependency order: for any sub-question
    with a non-empty `depends_on`, every dependency appears earlier in the tuple.
    Independent sub-questions appear before the sub-questions that rely on them;
    among purely independent items the original decomposer order is preserved.
    """

    original_query: str
    sub_questions: tuple[SubQuestion, ...]

    @classmethod
    def build(cls, original_query: str, sub_questions: list[SubQuestion]) -> Self:
        """Validate and topologically sort sub-questions.

        Raises InvariantViolationError when:
        - the list is empty
        - the original query is blank
        - any two sub-questions share the same id
        - a depends_on entry names an id not present in the list
        - the dependency graph contains a cycle
        """
        require_non_blank(original_query, "original_query")
        if not sub_questions:
            raise InvariantViolationError(
                "a decomposition must have at least one sub-question"
            )

        ids = [sq.id for sq in sub_questions]
        if len(set(ids)) != len(ids):
            raise InvariantViolationError(
                "sub-question ids must be unique within a plan"
            )

        id_set = frozenset(ids)
        by_id = {sq.id: sq for sq in sub_questions}

        for sq in sub_questions:
            for dep in sq.depends_on:
                if dep not in id_set:
                    raise InvariantViolationError(
                        f"sub-question {sq.id!r} depends on unknown id {dep!r}"
                    )

        # Kahn's algorithm: BFS topological sort with cycle detection.
        # in_degree[id] counts unsatisfied dependencies.
        # dependents[id] lists the ids that depend on id.
        in_degree: dict[str, int] = {sq_id: 0 for sq_id in id_set}
        dependents: dict[str, list[str]] = {sq_id: [] for sq_id in id_set}

        for sq in sub_questions:
            for dep in sq.depends_on:
                in_degree[sq.id] += 1
                dependents[dep].append(sq.id)

        # Seed with nodes that have no unsatisfied dependencies, preserving
        # the decomposer's order for nodes that are equally eligible.
        queue: deque[str] = deque(sq_id for sq_id in ids if in_degree[sq_id] == 0)
        ordered: list[SubQuestion] = []

        while queue:
            sq_id = queue.popleft()
            ordered.append(by_id[sq_id])
            for dependent_id in dependents[sq_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(ordered) != len(sub_questions):
            raise InvariantViolationError(
                "sub-questions contain a dependency cycle — "
                "topological sort is impossible"
            )

        return cls(original_query=original_query, sub_questions=tuple(ordered))

    def __len__(self) -> int:
        return len(self.sub_questions)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.sub_questions)
