"""SQLAlchemy repository implementations.

Each module implements the corresponding domain Protocol using the shared
ScopedRepository base class and the ORM models defined in
app.infrastructure.database.models.
"""

from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.graph import SqlGraphRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.repositories.knowledge_base import SqlKnowledgeBaseRepository
from app.infrastructure.database.repositories.memory import SqlMemoryRepository

__all__ = [
    "SqlChunkRepository",
    "SqlConversationRepository",
    "SqlDocumentRepository",
    "SqlGraphRepository",
    "SqlJobRepository",
    "SqlKnowledgeBaseRepository",
    "SqlMemoryRepository",
]
