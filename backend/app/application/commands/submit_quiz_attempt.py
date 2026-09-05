"""Use case: score a quiz attempt deterministically and persist it.

Scoring is always deterministic Python — never LLM-judged (FR-STU-05).
Multiple-choice and true/false: case-insensitive exact match.
Short answer and fill-blank: case-insensitive, stripping punctuation and whitespace.
Chart/table interpretation: treated as short-answer scoring.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.scope import ScopeContext
from app.domain.study.entities import Quiz, QuizAttempt
from app.domain.enums import QuestionType


@dataclass(frozen=True)
class SubmitQuizAttemptCommand:
    scope: ScopeContext
    quiz: Quiz
    answers: dict[str, str]  # str(question_id) -> submitted answer


@dataclass(frozen=True)
class SubmitQuizAttemptResult:
    attempt: QuizAttempt
    feedback: dict[str, dict]  # question_id -> {correct, correct_answer, explanation}


_PUNCT = re.compile(r"[^\w\s]")


def _normalise(text: str) -> str:
    return _PUNCT.sub("", text).strip().lower()


def _is_correct(question_type: QuestionType, submitted: str, correct: str) -> bool:
    if question_type in (QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE):
        return submitted.strip().lower() == correct.strip().lower()
    return _normalise(submitted) == _normalise(correct)


class SubmitQuizAttemptUseCase:
    def __init__(self, *, attempt_repo: object) -> None:  # SqlQuizRepository
        self._repo = attempt_repo

    async def execute(
        self, command: SubmitQuizAttemptCommand, session: object
    ) -> SubmitQuizAttemptResult:
        feedback: dict[str, dict] = {}
        incorrect_ids: list[uuid.UUID] = []
        correct_count = 0

        for question in command.quiz.questions:
            qid = str(question.id)
            submitted = command.answers.get(qid, "")
            correct = _is_correct(question.question_type, submitted, question.correct_answer)

            if correct:
                correct_count += 1
            else:
                incorrect_ids.append(question.id)

            feedback[qid] = {
                "correct": correct,
                "correct_answer": question.correct_answer,
                "explanation": question.explanation,
            }

        total = len(command.quiz.questions)
        score = correct_count / total if total else 0.0

        attempt = QuizAttempt(
            id=uuid.uuid4(),
            quiz_id=command.quiz.id,
            kb_id=command.scope.knowledge_base_id,
            user_id=command.scope.user_id,
            answers=command.answers,
            score=score,
            correct_count=correct_count,
            total_count=total,
            incorrect_question_ids=tuple(incorrect_ids),
            created_at=datetime.now(UTC),
        )
        await self._repo.save_attempt(command.scope, attempt)
        return SubmitQuizAttemptResult(attempt=attempt, feedback=feedback)
