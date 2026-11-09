import hashlib
from typing import Any

import chromadb
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


class FakeEmbeddingFunction(chromadb.EmbeddingFunction):
    """A deterministic, instant stand-in for a real sentence-transformer.

    Hashes each text into a fixed-length vector. Not semantically meaningful
    (don't use it to test retrieval *accuracy*), but valid input for Chroma,
    so tests that only need the ingest/retrieve plumbing to work stay fast
    and offline instead of downloading a real embedding model.
    """

    DIMENSIONS = 16

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, input: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255 for b in digest[: self.DIMENSIONS]]

    @staticmethod
    def name() -> str:
        return "fake_test_embedding"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "FakeEmbeddingFunction":
        return FakeEmbeddingFunction()


@pytest.fixture()
def fake_embedding_function():
    return FakeEmbeddingFunction()
