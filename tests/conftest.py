import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import db as db_module


@pytest.fixture()
def db(monkeypatch):
    """An in-memory SQLite engine, fresh for each test."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_module.create_all(test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    yield test_engine
