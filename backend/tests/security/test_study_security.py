"""Security tests: scope isolation for study-content repositories.

Three invariants must hold across all four study-content repositories
(Summary, Quiz, Flashcard, StudyPlan):

  1. Cross-KB isolation — a call whose scope differs from the bound scope is
     rejected before any database round-trip.

  2. SQL parameter binding — user_id and knowledge_base_id must appear as bound
     SQL parameters on every SELECT so removing a WHERE clause is visible in
     query inspection rather than silently absent.

  3. Mutation isolation — UPDATE operations must not reach rows belonging to a
     different scope even when a foreign plan_id or task_id is supplied.
     update_task_status enforces this by scoping the plan lookup via a
     subquery before the task update is applied.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.study import (
    SqlFlashcardRepository,
    SqlQuizRepository,
    SqlStudyPlanRepository,
    SqlStudySummaryRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _session() -> AsyncMock:
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# 1. Cross-KB isolation — every repo rejects a foreign call scope
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_summary_repo_rejects_foreign_scope_before_db_call() -> None:
    """SqlStudySummaryRepository.list must raise before any SQL runs when the
    call scope differs from the bound scope."""
    bound = _scope()
    caller = _scope()
    ses = _session()

    repo = SqlStudySummaryRepository(scope=bound, session=ses)

    with pytest.raises(ScopeViolationError):
        await repo.list(caller)

    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_quiz_repo_rejects_foreign_scope_before_db_call() -> None:
    """SqlQuizRepository.list_all_attempts must raise before any SQL runs when
    the call scope differs from the bound scope."""
    bound = _scope()
    caller = _scope()
    ses = _session()

    repo = SqlQuizRepository(scope=bound, session=ses)

    with pytest.raises(ScopeViolationError):
        await repo.list_all_attempts(caller)

    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_flashcard_repo_rejects_foreign_scope_before_db_call() -> None:
    """SqlFlashcardRepository.list must raise before any SQL runs when the call
    scope differs from the bound scope."""
    bound = _scope()
    caller = _scope()
    ses = _session()

    repo = SqlFlashcardRepository(scope=bound, session=ses)

    with pytest.raises(ScopeViolationError):
        await repo.list(caller)

    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_plan_repo_rejects_foreign_scope_before_db_call() -> None:
    """SqlStudyPlanRepository.list must raise before any SQL runs when the call
    scope differs from the bound scope."""
    bound = _scope()
    caller = _scope()
    ses = _session()

    repo = SqlStudyPlanRepository(scope=bound, session=ses)

    with pytest.raises(ScopeViolationError):
        await repo.list(caller)

    ses.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 2. SQL parameter binding — user_id and knowledge_base_id on primary reads
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_summary_list_binds_user_id_as_sql_parameter() -> None:
    """user_id must be a bound SQL parameter on SqlStudySummaryRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlStudySummaryRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_summary_list_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must be a bound SQL parameter on SqlStudySummaryRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlStudySummaryRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_quiz_list_all_attempts_binds_user_id_as_sql_parameter() -> None:
    """user_id must be a bound SQL parameter on SqlQuizRepository.list_all_attempts."""
    scope = _scope()
    ses = _session()

    await SqlQuizRepository(scope=scope, session=ses).list_all_attempts(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_quiz_list_all_attempts_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must be a bound SQL parameter on SqlQuizRepository.list_all_attempts."""
    scope = _scope()
    ses = _session()

    await SqlQuizRepository(scope=scope, session=ses).list_all_attempts(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_flashcard_list_binds_user_id_as_sql_parameter() -> None:
    """user_id must be a bound SQL parameter on SqlFlashcardRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlFlashcardRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_flashcard_list_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must be a bound SQL parameter on SqlFlashcardRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlFlashcardRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_plan_list_binds_user_id_as_sql_parameter() -> None:
    """user_id must be a bound SQL parameter on SqlStudyPlanRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlStudyPlanRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_plan_list_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must be a bound SQL parameter on SqlStudyPlanRepository.list."""
    scope = _scope()
    ses = _session()

    await SqlStudyPlanRepository(scope=scope, session=ses).list(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


# ---------------------------------------------------------------------------
# 3. list_all_tasks scopes through the StudyPlanModel JOIN
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_list_all_tasks_binds_user_id_via_plan_join() -> None:
    """list_all_tasks must bind user_id through the StudyPlanModel JOIN, not
    rely on the caller to filter afterwards."""
    scope = _scope()
    ses = _session()

    await SqlStudyPlanRepository(scope=scope, session=ses).list_all_tasks(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values(), (
        "user_id must appear as a bound parameter in the list_all_tasks JOIN query"
    )


@pytest.mark.security
@pytest.mark.gate
async def test_list_all_tasks_binds_knowledge_base_id_via_plan_join() -> None:
    """list_all_tasks must bind knowledge_base_id through the StudyPlanModel JOIN."""
    scope = _scope()
    ses = _session()

    await SqlStudyPlanRepository(scope=scope, session=ses).list_all_tasks(scope)

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values(), (
        "knowledge_base_id must appear as a bound parameter in the list_all_tasks JOIN query"
    )


# ---------------------------------------------------------------------------
# 4. Mutation isolation — update_task_status
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_update_task_status_rejects_foreign_scope_before_db_call() -> None:
    """update_task_status must raise before any SQL runs when the call scope
    differs from the bound scope."""
    bound = _scope()
    caller = _scope()
    ses = _session()

    repo = SqlStudyPlanRepository(scope=bound, session=ses)

    with pytest.raises(ScopeViolationError):
        await repo.update_task_status(
            caller,
            plan_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            status=__import__(
                "app.domain.enums", fromlist=["StudyTaskStatus"]
            ).StudyTaskStatus.COMPLETED,
        )

    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_update_task_status_binds_scope_in_plan_subquery() -> None:
    """The UPDATE statement must include a plan-ownership subquery that binds
    user_id and knowledge_base_id, so a foreign plan_id cannot update any task
    even if the application-layer scope check were bypassed."""
    from app.domain.enums import StudyTaskStatus

    scope = _scope()
    ses = _session()

    await SqlStudyPlanRepository(scope=scope, session=ses).update_task_status(
        scope,
        plan_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        status=StudyTaskStatus.COMPLETED,
    )

    compiled = ses.execute.call_args[0][0].compile()
    params = compiled.params
    assert scope.user_id in params.values(), (
        "user_id must appear in the UPDATE subquery so a foreign plan_id is rejected at DB level"
    )
    assert scope.knowledge_base_id in params.values(), (
        "knowledge_base_id must appear in the UPDATE subquery"
    )
