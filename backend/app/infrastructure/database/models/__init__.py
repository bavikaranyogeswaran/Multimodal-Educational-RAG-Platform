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
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel

__all__ = [
    "ChunkElementModel",
    "ChunkModel",
    "ConversationModel",
    "ConversationRetrievalChunkModel",
    "DocumentElementModel",
    "DocumentModel",
    "DocumentPageModel",
    "KnowledgeBaseModel",
    "MemoryFactModel",
    "MessageModel",
]
