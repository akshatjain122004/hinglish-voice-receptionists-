"""Rebuild the FAQ vector store from data/faqs.md.

Usage:
    python scripts/ingest_faqs.py
"""

from __future__ import annotations

from app import rag


def main() -> None:
    count = rag.ingest()
    print(
        f"Ingested {count} FAQ chunks into '{rag.DEFAULT_COLLECTION_NAME}' at {rag.DEFAULT_PERSIST_DIR}"
    )


if __name__ == "__main__":
    main()
