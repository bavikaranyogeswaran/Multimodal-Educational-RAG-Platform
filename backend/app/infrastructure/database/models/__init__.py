"""SQLAlchemy ORM models.

Importing this package registers every model class with the shared Base
metadata. Always import this package (not individual model modules) from
alembic/env.py and from the async session factory, so that autogenerate
and create_all see every table in one pass.
"""

from app.infrastructure.database.models.chunk import (
    ChunkElementModel,
    ChunkModel,
    DocumentElementModel,
)
from app.infrastructure.database.models.conversation import (
    ConversationModel,
    ConversationRetrievalChunkModel,
    MemoryFactModel,
    MessageModel,
)
from app.infrastructure.database.models.document import DocumentModel, DocumentPageModel
from app.infrastructure.database.models.figure import DocumentFigureModel
from app.infrastructure.database.models.graph import GraphEntityModel, GraphRelationshipModel
from app.infrastructure.database.models.job import CacheEntryModel, ProcessingJobModel
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.models.model_invocation import ModelInvocationModel
from app.infrastructure.database.models.study import (
    FlashcardModel,
    FlashcardReviewModel,
    QuizAttemptModel,
    QuizModel,
    QuizQuestionModel,
    StudyPlanModel,
    StudySummaryModel,
    StudyTaskModel,
)
from app.infrastructure.database.models.table import DocumentTableModel

__all__ = [
    "CacheEntryModel",
    "ChunkElementModel",
    "ChunkModel",
    "ConversationModel",
    "ConversationRetrievalChunkModel",
    "DocumentElementModel",
    "DocumentFigureModel",
    "DocumentModel",
    "DocumentPageModel",
    "DocumentTableModel",
    "GraphEntityModel",
    "GraphRelationshipModel",
    "KnowledgeBaseModel",
    "MemoryFactModel",
    "MessageModel",
    "ModelInvocationModel",
    "ProcessingJobModel",
    "FlashcardModel",
    "FlashcardReviewModel",
    "QuizAttemptModel",
    "QuizModel",
    "QuizQuestionModel",
    "StudyPlanModel",
    "StudySummaryModel",
    "StudyTaskModel",
]
