"""FAQ ingestion and retrieval (Chroma RAG).

Embedding is injected behind a small protocol, the same pattern as
`app.agent.LLMClient`, so tests can plug in a fast fake instead of loading a
real sentence-transformer model.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

import chromadb

from app import db

DEFAULT_PERSIST_DIR = "data/chroma"
DEFAULT_COLLECTION_NAME = "faqs"
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_HEADING_RE = re.compile(r"^##[ \t]+(.+)$", re.MULTILINE)


class EmbeddingFunction(Protocol):
    def __call__(self, input: list[str]) -> list[list[float]]: ...


def chunk_faqs(markdown_text: str) -> list[dict[str, str]]:
    """Split FAQ markdown into one chunk per `## ` heading.

    Each chunk is `{"id", "question", "answer"}`: the heading is the
    question, and the answer is everything up to the next heading.
    """
    headings = list(_HEADING_RE.finditer(markdown_text))
    chunks = []
    for i, match in enumerate(headings):
        question = match.group(1).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown_text)
        answer = markdown_text[start:end].strip()
        chunks.append({"id": f"faq-{i}", "question": question, "answer": answer})
    return chunks


def get_embedding_function(model_name: str = DEFAULT_EMBEDDING_MODEL) -> EmbeddingFunction:
    """The real embedder: a small local multilingual sentence-transformer.

    Runs on CPU; after the model weights are first downloaded it makes no
    network calls, so it stays out of `pytest -m live` (no paid API involved).
    """
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)


def _get_collection(
    persist_dir: str | Path,
    collection_name: str,
    embedding_function: EmbeddingFunction | None,
):
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function or get_embedding_function(),
    )


def _hash_path(persist_dir: str | Path, collection_name: str) -> Path:
    return Path(persist_dir) / f"{collection_name}.hash"


def ingest(
    faqs_path: str | Path = "data/faqs.md",
    *,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_function: EmbeddingFunction | None = None,
) -> int:
    """Chunk `faqs_path` and upsert every chunk into a persistent Chroma collection.

    Re-running with the same chunk ids updates those chunks in place instead
    of duplicating them. Skips re-embedding entirely when `faqs_path`'s
    content hash matches the last ingest, so a repeat run (e.g. in CI) never
    loads the embedding model. Returns the number of chunks in the file.
    """
    text = Path(faqs_path).read_text(encoding="utf-8")
    chunks = chunk_faqs(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    hash_file = _hash_path(persist_dir, collection_name)
    if hash_file.exists() and hash_file.read_text().strip() == digest:
        return len(chunks)

    collection = _get_collection(persist_dir, collection_name, embedding_function)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    for c in chunks:
        metadata = {"question": c["question"], "answer": c["answer"]}
        # Indexed twice: by the question alone (so an exact-ish question
        # match scores ~1.0 instead of being diluted by unrelated answer
        # text) and by question+answer (so a paraphrase that happens to
        # share vocabulary with the *answer* still ranks well). retrieve()
        # dedupes back to one result per question, keeping the best score.
        ids.append(f"{c['id']}-q")
        documents.append(c["question"])
        metadatas.append(metadata)
        ids.append(f"{c['id']}-qa")
        documents.append(f"{c['question']}\n{c['answer']}")
        metadatas.append(metadata)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(digest)
    return len(chunks)


def _dedupe_best_score(
    results: list[dict[str, str | float]],
) -> list[dict[str, str | float]]:
    """Each FAQ is indexed twice (question-only + question-and-answer, see
    `ingest`) and can appear twice in raw query results — collapse back to
    one entry per question, keeping the higher score."""
    best: dict[str, dict[str, str | float]] = {}
    for r in results:
        q = r["question"]
        if q not in best or r["score"] > best[q]["score"]:
            best[q] = r
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)


def retrieve(
    question: str,
    k: int = 3,
    *,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_function: EmbeddingFunction | None = None,
) -> list[dict[str, str | float]]:
    """Return the top-`k` FAQ chunks for `question`, best match first.

    `score` is `1 - cosine distance`: close to 1 is a strong match, 0 or
    below means the question is likely out of scope.
    """
    collection = _get_collection(persist_dir, collection_name, embedding_function)
    # Each FAQ has two indexed variants, so fetch enough raw results to
    # guarantee k distinct questions survive deduping.
    raw_n = max(k * 2, collection.count())
    result = collection.query(
        query_texts=[question], n_results=raw_n, include=["metadatas", "distances"]
    )
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    candidates = [
        {"question": m["question"], "answer": m["answer"], "score": 1 - d}
        for m, d in zip(metadatas, distances)
    ]
    return _dedupe_best_score(candidates)[:k]


def log_unanswered(question: str, caller_phone: str | None = None) -> None:
    """Record a question the FAQs couldn't answer, for the owner to review
    later and add to `data/faqs.md` (see the Phase 9 dashboard)."""
    with db.get_session() as session:
        session.add(db.UnansweredQuestion(question=question, caller_phone=caller_phone))
        session.commit()
