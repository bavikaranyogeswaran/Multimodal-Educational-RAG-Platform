"""Unit tests for migration 0005 and conversation/memory ORM models.

Runs without a live database. Migration tests inspect source for expected table
and column names. Model tests use SQLAlchemy's table introspection API.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0005_conversations_messages_memory.py"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConversationsMemoryMigration:
    def test_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.revision == "0005"

    def test_down_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.down_revision == "0004"

    def test_upgrade_is_callable(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert callable(mod.upgrade)

    def test_downgrade_is_callable(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert callable(mod.downgrade)

    def test_upgrade_creates_conversations_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"conversations"' in src
        assert "rolling_summary" in src

    def test_upgrade_creates_messages_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"messages"' in src
        assert "conversation_id" in src

    def test_upgrade_creates_conversation_retrieval_chunks_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "conversation_retrieval_chunks" in src
        assert "rank" in src
        assert "score" in src

    def test_conversation_retrieval_chunks_has_created_at_for_partition_readiness(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        # created_at must be present so the table can later be PARTITION BY RANGE(created_at)
        # without a DDL change (D-15)
        assert "created_at" in src

    def test_upgrade_creates_memory_facts_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"memory_facts"' in src
        assert "superseded_by" in src

    def test_memory_facts_superseded_by_is_self_referential(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        # The FK references the same table
        assert "memory_facts.id" in src

    def test_memory_facts_superseded_by_is_set_null_on_delete(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "SET NULL" in src

    def test_conversations_rolling_summary_present(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "rolling_summary" in src

    def test_downgrade_drops_all_tables(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        for table in [
            "memory_facts",
            "conversation_retrieval_chunks",
            "messages",
            "conversations",
        ]:
            assert table in src, f"downgrade() does not drop '{table}'"


class TestConversationModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        assert ConversationModel.__tablename__ == "conversations"

    def test_has_scope_columns(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        cols = {c.name for c in ConversationModel.__table__.columns}
        assert "user_id" in cols
        assert "knowledge_base_id" in cols

    def test_has_all_active_context_columns(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        cols = {c.name for c in ConversationModel.__table__.columns}
        assert "active_document_id" in cols
        assert "active_page_number" in cols
        assert "active_figure_id" in cols
        assert "active_table_id" in cols

    def test_rolling_summary_is_nullable(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        col = ConversationModel.__table__.c["rolling_summary"]
        assert col.nullable

    def test_active_context_columns_are_nullable(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        for name in (
            "active_document_id",
            "active_page_number",
            "active_figure_id",
            "active_table_id",
        ):
            col = ConversationModel.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"

    def test_knowledge_base_id_has_fk_to_knowledge_bases(self) -> None:
        from app.infrastructure.database.models.conversation import ConversationModel

        fks = ConversationModel.__table__.c["knowledge_base_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "knowledge_bases.id" in targets


class TestMessageModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.conversation import MessageModel

        assert MessageModel.__tablename__ == "messages"

    def test_has_scope_and_role_columns(self) -> None:
        from app.infrastructure.database.models.conversation import MessageModel

        cols = {c.name for c in MessageModel.__table__.columns}
        for name in ("user_id", "knowledge_base_id", "role", "status", "content"):
            assert name in cols

    def test_model_metadata_columns_are_nullable(self) -> None:
        from app.infrastructure.database.models.conversation import MessageModel

        for name in ("model_id", "prompt_tokens", "completion_tokens", "finish_reason"):
            col = MessageModel.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"

    def test_conversation_id_has_fk_to_conversations(self) -> None:
        from app.infrastructure.database.models.conversation import MessageModel

        fks = MessageModel.__table__.c["conversation_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "conversations.id" in targets


class TestConversationRetrievalChunkModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.conversation import (
            ConversationRetrievalChunkModel,
        )

        assert (
            ConversationRetrievalChunkModel.__tablename__ == "conversation_retrieval_chunks"
        )

    def test_composite_primary_key(self) -> None:
        from app.infrastructure.database.models.conversation import (
            ConversationRetrievalChunkModel,
        )

        pk_cols = {
            c.name
            for c in ConversationRetrievalChunkModel.__table__.primary_key.columns
        }
        assert pk_cols == {"message_id", "chunk_id"}

    def test_has_rank_and_score(self) -> None:
        from app.infrastructure.database.models.conversation import (
            ConversationRetrievalChunkModel,
        )

        cols = {c.name for c in ConversationRetrievalChunkModel.__table__.columns}
        assert "rank" in cols
        assert "score" in cols

    def test_has_created_at_for_partition_readiness(self) -> None:
        from app.infrastructure.database.models.conversation import (
            ConversationRetrievalChunkModel,
        )

        cols = {c.name for c in ConversationRetrievalChunkModel.__table__.columns}
        assert "created_at" in cols


class TestMemoryFactModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        assert MemoryFactModel.__tablename__ == "memory_facts"

    def test_has_lifecycle_columns(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        cols = {c.name for c in MemoryFactModel.__table__.columns}
        for name in ("status", "valid_from", "valid_until", "superseded_by"):
            assert name in cols

    def test_superseded_by_is_nullable(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        col = MemoryFactModel.__table__.c["superseded_by"]
        assert col.nullable

    def test_superseded_by_has_self_referential_fk(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        fks = MemoryFactModel.__table__.c["superseded_by"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "memory_facts.id" in targets

    def test_provenance_stored_as_integer(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        col = MemoryFactModel.__table__.c["provenance"]
        assert isinstance(col.type, sa.Integer)

    def test_memory_type_and_status_are_varchar(self) -> None:
        from app.infrastructure.database.models.conversation import MemoryFactModel

        for name in ("memory_type", "status"):
            col = MemoryFactModel.__table__.c[name]
            assert isinstance(col.type, sa.String), f"{name} should be String"
