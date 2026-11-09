import pathlib

from app import rag

DATA = pathlib.Path("data")

SAMPLE = """# Clinic FAQs

## Cleaning ki fees kitni hai?
Cleaning ka charge paanch sau rupaye hai.

## Clinic kitne baje khulta hai?
Subah das baje se raat aath baje tak khula rehta hai.
"""


def test_chunk_faqs_splits_on_each_heading():
    chunks = rag.chunk_faqs(SAMPLE)
    assert len(chunks) == 2


def test_chunk_faqs_keeps_question_and_answer_together():
    chunks = rag.chunk_faqs(SAMPLE)
    assert chunks[0]["question"] == "Cleaning ki fees kitni hai?"
    assert "paanch sau rupaye" in chunks[0]["answer"]
    assert chunks[1]["question"] == "Clinic kitne baje khulta hai?"
    assert "aath baje" in chunks[1]["answer"]


def test_chunk_faqs_on_real_faqs_file_produces_at_least_15_chunks():
    text = (DATA / "faqs.md").read_text(encoding="utf-8")
    chunks = rag.chunk_faqs(text)
    assert len(chunks) >= 15
    for chunk in chunks:
        assert chunk["question"]
        assert chunk["answer"]
