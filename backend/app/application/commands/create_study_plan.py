"""Use case: create a study plan.

Python computes the schedule (dates and workload per chapter) — the model is
called only once to phrase each task as a one-sentence learning objective.
This keeps scheduling deterministic while letting the model produce
natural-language descriptions rather than generic strings.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.domain.enums import ModelTask, StudyTaskStatus
from app.domain.models.context_builder import ContextBuilder, ContextInputs
from app.domain.models.entities import LabeledPassage
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.scope import ScopeContext
from app.domain.study.entities import StudyPlan, StudyTask

_SYSTEM_PREAMBLE = (
    "You are an educational planning assistant. Given a list of study sessions, write "
    "one concise, actionable learning objective per session."
)

_SAFETY_RULES: tuple[str, ...] = (
    "Use only the information given in the session list. Do not add topics not listed.",
)

_TASK_INSTRUCTIONS = (
    "Each item in the JSON input describes a planned study session. "
    "Write one sentence for each: the chapter/topic, what the student should accomplish, "
    "and the time budget. Keep each sentence under 20 words."
)

_OUTPUT_SCHEMA = """\
Return a JSON array of strings, one sentence per input item, in the same order:
["Sentence for session 1", "Sentence for session 2", ...]
Return only the JSON array, no preamble.
"""


@dataclass(frozen=True)
class CreateStudyPlanCommand:
    scope: ScopeContext
    exam_date: date
    available_hours_per_day: float
    chapters: tuple[str, ...]
    priority_topics: tuple[str, ...]


@dataclass(frozen=True)
class CreateStudyPlanResult:
    plan: StudyPlan


class CreateStudyPlanUseCase:
    def __init__(
        self,
        *,
        model_gateway: ModelGatewayPort,
        context_builder: ContextBuilder,
        plan_repo: object,  # SqlStudyPlanRepository
    ) -> None:
        self._gateway = model_gateway
        self._context_builder = context_builder
        self._repo = plan_repo

    async def execute(
        self, command: CreateStudyPlanCommand, session: object
    ) -> CreateStudyPlanResult:
        today = date.today()
        days_left = (command.exam_date - today).days
        if days_left <= 0:
            raise ValueError("Exam date must be in the future")

        # Python computes the schedule.
        raw_tasks = _build_schedule(
            today=today,
            days_left=days_left,
            available_hours=command.available_hours_per_day,
            chapters=list(command.chapters),
            priority_topics=list(command.priority_topics),
        )

        # LLM phrases only the task descriptions.
        descriptions = await self._phrase_tasks(raw_tasks)

        plan_id = uuid.uuid4()
        now = datetime.now(UTC)
        tasks = tuple(
            StudyTask(
                id=uuid.uuid4(),
                plan_id=plan_id,
                title=f"Study {rt['chapter']}",
                description=descriptions[i] if i < len(descriptions) else f"Study {rt['chapter']}",
                due_date=rt["due_date"],
                chapter_reference=rt["chapter"],
                hours_allocated=rt["hours"],
                status=StudyTaskStatus.PENDING,
            )
            for i, rt in enumerate(raw_tasks)
        )

        plan = StudyPlan(
            id=plan_id,
            kb_id=command.scope.knowledge_base_id,
            user_id=command.scope.user_id,
            exam_date=command.exam_date,
            available_hours_per_day=command.available_hours_per_day,
            chapters=command.chapters,
            priority_topics=command.priority_topics,
            tasks=tasks,
            created_at=now,
        )
        await self._repo.save(command.scope, plan)
        return CreateStudyPlanResult(plan=plan)

    async def _phrase_tasks(self, raw_tasks: list[dict]) -> list[str]:
        if not raw_tasks:
            return []

        session_list = [
            {"chapter": rt["chapter"], "hours": rt["hours"], "due": str(rt["due_date"])}
            for rt in raw_tasks
        ]
        query = json.dumps(session_list, ensure_ascii=False)

        request = self._context_builder.build(
            ContextInputs(
                model_task=ModelTask.SUMMARIZATION,
                system_preamble=_SYSTEM_PREAMBLE,
                safety_rules=_SAFETY_RULES,
                task_instructions=_TASK_INSTRUCTIONS,
                query=query,
                evidence=(),
                output_schema=_OUTPUT_SCHEMA,
            )
        )
        raw = await self._gateway.generate(request)
        text = raw.content.value.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [str(s) for s in result]
        except json.JSONDecodeError:
            pass
        return []


# ---------------------------------------------------------------------------
# Schedule builder — pure Python, no LLM
# ---------------------------------------------------------------------------

def _build_schedule(
    today: date,
    days_left: int,
    available_hours: float,
    chapters: list[str],
    priority_topics: list[str],
) -> list[dict]:
    if not chapters:
        return []

    # Priority chapters come first.
    priority_set = set(priority_topics)
    ordered = [c for c in chapters if c in priority_set] + \
              [c for c in chapters if c not in priority_set]

    # Spread chapters evenly across available days (leave 1 day as revision buffer).
    study_days = max(1, days_left - 1)
    days_per_chapter = max(1, math.ceil(study_days / len(ordered)))
    hours_per_chapter = round(available_hours * days_per_chapter, 1)

    tasks: list[dict] = []
    current_day = today + timedelta(days=1)  # start tomorrow
    for chapter in ordered:
        due = current_day + timedelta(days=days_per_chapter - 1)
        tasks.append({
            "chapter": chapter,
            "due_date": min(due, today + timedelta(days=days_left - 1)),
            "hours": hours_per_chapter,
        })
        current_day += timedelta(days=days_per_chapter)

    return tasks
