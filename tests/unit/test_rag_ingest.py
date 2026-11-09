import chromadb

from app import rag

FAQS_MD = """## Cleaning ki fees kitni hai?
Cleaning ka charge paanch sau rupaye hai.

## Clinic kitne baje khulta hai?
Subah das baje se raat aath baje tak khula rehta hai.
"""


def test_ingest_upserts_two_chroma_entries_per_faq(tmp_path, fake_embedding_function):
    """Each FAQ is indexed twice: once by its question alone (so an exact or
    near-exact question match scores ~1.0) and once by question+answer (so a
    paraphrase that happens to share vocabulary with the *answer* still
    ranks well) — see docs/BUILD_PLAN.md phase 3 notes for why either
    variant alone misses real cases."""
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    count = rag.ingest(
        faqs_path,
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    assert count == 2
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=rag.DEFAULT_COLLECTION_NAME, embedding_function=fake_embedding_function
    )
    assert collection.count() == 4


def test_ingest_is_idempotent_on_rerun(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)
    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=rag.DEFAULT_COLLECTION_NAME, embedding_function=fake_embedding_function
    )
    assert collection.count() == 4


def test_ingest_stores_question_and_answer_in_metadata(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=rag.DEFAULT_COLLECTION_NAME, embedding_function=fake_embedding_function
    )
    result = collection.get(ids=["faq-0-q"])
    assert result["metadatas"][0]["question"] == "Cleaning ki fees kitni hai?"
    assert "paanch sau rupaye" in result["metadatas"][0]["answer"]


def test_ingest_question_variant_embeds_the_question_only(tmp_path, fake_embedding_function):
    """A caller's query resembles the FAQ's *question*, not its answer —
    embedding "question\\nanswer" together dilutes the similarity so badly
    that even the exact question text can score below the found threshold
    against its own FAQ (verified: ~0.45 instead of 1.0 cosine similarity).
    This variant exists so an exact-ish question match still scores ~1.0."""
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=rag.DEFAULT_COLLECTION_NAME, embedding_function=fake_embedding_function
    )
    result = collection.get(ids=["faq-0-q"], include=["documents"])
    assert result["documents"][0] == "Cleaning ki fees kitni hai?"


def test_ingest_combined_variant_embeds_question_and_answer(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=rag.DEFAULT_COLLECTION_NAME, embedding_function=fake_embedding_function
    )
    result = collection.get(ids=["faq-0-qa"], include=["documents"])
    assert (
        result["documents"][0]
        == "Cleaning ki fees kitni hai?\nCleaning ka charge paanch sau rupaye hai."
    )


def test_ingest_skips_reembedding_when_faqs_file_is_unchanged(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)
    calls_after_first_ingest = fake_embedding_function.calls

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    assert fake_embedding_function.calls == calls_after_first_ingest


def test_ingest_reembeds_when_faqs_file_changes(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"

    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)
    calls_after_first_ingest = fake_embedding_function.calls

    faqs_path.write_text(FAQS_MD + "\n## Naya sawal kya hai?\nNaya jawab hai.\n", encoding="utf-8")
    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)

    assert fake_embedding_function.calls > calls_after_first_ingest
