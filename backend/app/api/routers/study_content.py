"""Study content resource endpoints — summaries, quizzes, flashcards, study plans, progress."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.retrieval import get_retrieval_orchestrator
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.study import (
    CreateStudyPlanRequest,
    FlashcardResponse,
    FlashcardReviewResponse,
    GenerateFlashcardsRequest,
    GenerateQuizRequest,
    GenerateSummaryRequest,
    LearningProgressResponse,
    QuizAttemptFeedback,
    QuizAttemptResponse,
    QuizQuestionResponse,
    QuizResponse,
    StudyPlanResponse,
    StudyTaskResponse,
    SubmitFlashcardReviewRequest,
    SubmitQuizAttemptRequest,
    SummaryResponse,
    UpdateStudyTaskRequest,
)
from app.application.commands.create_study_plan import (
    CreateStudyPlanCommand,
    CreateStudyPlanUseCase,
)
from app.application.commands.generate_flashcards import (
    GenerateFlashcardsCommand,
    GenerateFlashcardsUseCase,
)
from app.application.commands.generate_quiz_structured import (
    GenerateStructuredQuizCommand,
    GenerateStructuredQuizUseCase,
)
from app.application.commands.generate_summary import (
    GenerateSummaryCommand,
    GenerateSummaryUseCase,
)
from app.application.commands.submit_flashcard_review import (
    SubmitFlashcardReviewCommand,
    SubmitFlashcardReviewUseCase,
)
from app.application.commands.submit_quiz_attempt import (
    SubmitQuizAttemptCommand,
    SubmitQuizAttemptUseCase,
)
from app.application.queries.get_progress import GetProgressQuery, GetProgressUseCase
from app.application.queries.retrieve_evidence import (
    RetrievalOrchestrator,
    RetrieveEvidenceQuery,
)
from app.configuration.container import Container
from app.configuration.settings import get_settings
from app.domain.models.context_builder import ContextBuilder
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext
from app.domain.study.entities import Flashcard, Quiz, StudyPlan, StudySummary
from app.infrastructure.database.repositories.study import (
    SqlFlashcardRepository,
    SqlQuizRepository,
    SqlStudyPlanRepository,
    SqlStudySummaryRepository,
)
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}",
    tags=["study-content"],
    dependencies=[Depends(get_kb_scope)],
)

_DEFAULT_EVIDENCE_LIMIT = 10


async def _retrieve(
    query: str,
    scope: ScopeContext,
    orchestrator: RetrievalOrchestrator,
) -> tuple:
    if not query.strip():
        return ()
    result = await orchestrator.execute(
        RetrieveEvidenceQuery(scope=scope, query=query, filters=RetrievalFilters())
    )
    return tuple(result.evidence)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


@router.post("/summaries", response_model=SummaryResponse, status_code=201)
async def generate_summary(
    body: GenerateSummaryRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
    orchestrator: Annotated[RetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
) -> SummaryResponse:
    settings = get_settings()
    query = body.query or body.summary_type.value.lower().replace("_", " ")
    evidence = await _retrieve(query, scope, orchestrator)
    if not evidence:
        raise HTTPException(status_code=422, detail="No relevant content found to summarise")

    repo = SqlStudySummaryRepository(scope=scope, session=session)
    use_case = GenerateSummaryUseCase(
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
        summary_repo=repo,
    )
    try:
        result = await use_case.execute(
            GenerateSummaryCommand(
                scope=scope,
                summary_type=body.summary_type,
                section_ids=tuple(body.section_ids),
                evidence=evidence,
            ),
            session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _summary_response(result.summary)


@router.get("/summaries", response_model=list[SummaryResponse])
async def list_summaries(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SummaryResponse]:
    repo = SqlStudySummaryRepository(scope=scope, session=session)
    summaries = await repo.list(scope)
    return [_summary_response(s) for s in summaries]


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------


@router.post("/quizzes", response_model=QuizResponse, status_code=201)
async def generate_quiz(
    body: GenerateQuizRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
    orchestrator: Annotated[RetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
) -> QuizResponse:
    settings = get_settings()
    evidence = await _retrieve(body.topic, scope, orchestrator)
    if not evidence:
        raise HTTPException(status_code=422, detail="No relevant content found for quiz")

    repo = SqlQuizRepository(scope=scope, session=session)
    use_case = GenerateStructuredQuizUseCase(
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
        quiz_repo=repo,
    )
    try:
        result = await use_case.execute(
            GenerateStructuredQuizCommand(
                scope=scope,
                topic=body.topic,
                evidence=evidence,
                n_questions=body.n_questions,
            ),
            session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _quiz_response(result.quiz)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
async def get_quiz(
    quiz_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuizResponse:
    repo = SqlQuizRepository(scope=scope, session=session)
    quiz = await repo.get(scope, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return _quiz_response(quiz)


@router.post("/quizzes/{quiz_id}/attempts", response_model=QuizAttemptResponse, status_code=201)
async def submit_quiz_attempt(
    quiz_id: uuid.UUID,
    body: SubmitQuizAttemptRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuizAttemptResponse:
    quiz_repo = SqlQuizRepository(scope=scope, session=session)
    quiz = await quiz_repo.get(scope, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")

    use_case = SubmitQuizAttemptUseCase(attempt_repo=quiz_repo)
    result = await use_case.execute(
        SubmitQuizAttemptCommand(scope=scope, quiz=quiz, answers=body.answers),
        session,
    )
    await session.commit()
    return QuizAttemptResponse(
        id=result.attempt.id,
        quiz_id=result.attempt.quiz_id,
        score=result.attempt.score,
        correct_count=result.attempt.correct_count,
        total_count=result.attempt.total_count,
        feedback={
            qid: QuizAttemptFeedback(**fb)
            for qid, fb in result.feedback.items()
        },
    )


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------


@router.post("/flashcards", response_model=list[FlashcardResponse], status_code=201)
async def generate_flashcards(
    body: GenerateFlashcardsRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
    orchestrator: Annotated[RetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
) -> list[FlashcardResponse]:
    settings = get_settings()
    query = body.query or body.source.value.lower().replace("_", " ")
    evidence = await _retrieve(query, scope, orchestrator)
    if not evidence:
        raise HTTPException(status_code=422, detail="No relevant content found for flashcards")

    repo = SqlFlashcardRepository(scope=scope, session=session)
    use_case = GenerateFlashcardsUseCase(
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
        flashcard_repo=repo,
    )
    try:
        result = await use_case.execute(
            GenerateFlashcardsCommand(
                scope=scope,
                source=body.source,
                evidence=evidence,
            ),
            session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return [_flashcard_response(c, scope) for c in result.flashcards]


@router.get("/flashcards", response_model=list[FlashcardResponse])
async def list_flashcards(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FlashcardResponse]:
    repo = SqlFlashcardRepository(scope=scope, session=session)
    cards = await repo.list(scope)
    return [_flashcard_response(c, scope) for c in cards]


@router.post(
    "/flashcards/{card_id}/reviews",
    response_model=FlashcardReviewResponse,
    status_code=201,
)
async def submit_flashcard_review(
    card_id: uuid.UUID,
    body: SubmitFlashcardReviewRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FlashcardReviewResponse:
    repo = SqlFlashcardRepository(scope=scope, session=session)
    use_case = SubmitFlashcardReviewUseCase(flashcard_repo=repo)
    result = await use_case.execute(
        SubmitFlashcardReviewCommand(
            scope=scope,
            flashcard_id=card_id,
            rating=body.rating,
        ),
        session,
    )
    await session.commit()
    return FlashcardReviewResponse(
        id=result.review.id,
        flashcard_id=result.review.flashcard_id,
        rating=result.review.rating,
        reviewed_at=result.review.reviewed_at,
    )


# ---------------------------------------------------------------------------
# Study plans
# ---------------------------------------------------------------------------


@router.post("/study-plans", response_model=StudyPlanResponse, status_code=201)
async def create_study_plan(
    body: CreateStudyPlanRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> StudyPlanResponse:
    settings = get_settings()
    repo = SqlStudyPlanRepository(scope=scope, session=session)
    use_case = CreateStudyPlanUseCase(
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
        plan_repo=repo,
    )
    try:
        result = await use_case.execute(
            CreateStudyPlanCommand(
                scope=scope,
                exam_date=body.exam_date,
                available_hours_per_day=body.available_hours_per_day,
                chapters=tuple(body.chapters),
                priority_topics=tuple(body.priority_topics),
            ),
            session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _plan_response(result.plan)


@router.get("/study-plans", response_model=list[StudyPlanResponse])
async def list_study_plans(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StudyPlanResponse]:
    repo = SqlStudyPlanRepository(scope=scope, session=session)
    plans = await repo.list(scope)
    return [_plan_response(p) for p in plans]


@router.patch(
    "/study-plans/{plan_id}/tasks/{task_id}",
    response_model=StudyTaskResponse,
)
async def update_study_task(
    plan_id: uuid.UUID,
    task_id: uuid.UUID,
    body: UpdateStudyTaskRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StudyTaskResponse:
    repo = SqlStudyPlanRepository(scope=scope, session=session)
    await repo.update_task_status(scope, plan_id, task_id, body.status)
    await session.commit()
    # Re-read the task to return its updated state.
    plans = await repo.list(scope)
    for plan in plans:
        for task in plan.tasks:
            if task.id == task_id:
                return _task_response(task)
    raise HTTPException(status_code=404, detail="Task not found")


# ---------------------------------------------------------------------------
# Learning progress
# ---------------------------------------------------------------------------


@router.get("/progress", response_model=LearningProgressResponse)
async def get_progress(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LearningProgressResponse:
    quiz_repo = SqlQuizRepository(scope=scope, session=session)
    flashcard_repo = SqlFlashcardRepository(scope=scope, session=session)
    plan_repo = SqlStudyPlanRepository(scope=scope, session=session)

    use_case = GetProgressUseCase(
        quiz_repo=quiz_repo,
        flashcard_repo=flashcard_repo,
        plan_repo=plan_repo,
    )
    progress = await use_case.execute(GetProgressQuery(scope=scope))
    return LearningProgressResponse(
        knowledge_base_id=progress.kb_id,
        topic_mastery=progress.topic_mastery,
        quiz_scores=list(progress.quiz_scores),
        flashcard_ratings=progress.flashcard_ratings,
        completed_chapters=list(progress.completed_chapters),
        weak_concepts=list(progress.weak_concepts),
        plan_completion=progress.plan_completion,
        last_review_date=progress.last_review_date,
    )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _summary_response(s: StudySummary) -> SummaryResponse:
    return SummaryResponse(
        id=s.id,
        knowledge_base_id=s.kb_id,
        summary_type=s.summary_type,
        section_ids=list(s.section_ids),
        content=s.content,
        created_at=s.created_at,
    )


def _quiz_response(q: Quiz) -> QuizResponse:
    return QuizResponse(
        id=q.id,
        knowledge_base_id=q.kb_id,
        topic=q.topic,
        questions=[
            QuizQuestionResponse(
                id=qq.id,
                question_type=qq.question_type,
                question=qq.question,
                options=list(qq.options) if qq.options else None,
                difficulty=qq.difficulty,
                source_chunk_id=qq.source_chunk_id,
                document_id=qq.document_id,
                page_number=qq.page_number,
            )
            for qq in q.questions
        ],
        created_at=q.created_at,
    )


def _flashcard_response(c: Flashcard, scope: ScopeContext) -> FlashcardResponse:
    return FlashcardResponse(
        id=c.id,
        knowledge_base_id=c.kb_id,
        front=c.front,
        back=c.back,
        source=c.source,
        source_chunk_id=c.source_chunk_id,
        document_id=c.document_id,
        page_number=c.page_number,
        created_at=c.created_at,
    )


def _plan_response(p: StudyPlan) -> StudyPlanResponse:
    return StudyPlanResponse(
        id=p.id,
        knowledge_base_id=p.kb_id,
        exam_date=p.exam_date,
        available_hours_per_day=p.available_hours_per_day,
        chapters=list(p.chapters),
        priority_topics=list(p.priority_topics),
        tasks=[_task_response(t) for t in p.tasks],
        created_at=p.created_at,
    )


def _task_response(t) -> StudyTaskResponse:
    return StudyTaskResponse(
        id=t.id,
        title=t.title,
        description=t.description,
        due_date=t.due_date,
        chapter_reference=t.chapter_reference,
        hours_allocated=t.hours_allocated,
        status=t.status,
    )
