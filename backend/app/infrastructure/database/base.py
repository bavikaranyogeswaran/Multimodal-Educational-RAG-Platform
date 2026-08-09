"""SQLAlchemy declarative base shared by all ORM models.

All models import ``Base`` from here so that ``Base.metadata`` is a single
registry. Alembic's ``env.py`` points ``target_metadata`` at this object so
that autogenerate detects every table in one pass.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
