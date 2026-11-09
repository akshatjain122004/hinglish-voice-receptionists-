import pytest

from app import rag

FAQS_MD = """## Cleaning ki fees kitni hai?
Cleaning ka charge paanch sau rupaye hai.

## Clinic kitne baje khulta hai?
Subah das baje se raat aath baje tak khula rehta hai.

## Parking ki facility hai kya?
Haan, clinic ke saamne free parking available hai.
"""


def _ingest(tmp_path, fake_embedding_function):
    faqs_path = tmp_path / "faqs.md"
    faqs_path.write_text(FAQS_MD, encoding="utf-8")
    persist_dir = tmp_path / "chroma"
    rag.ingest(faqs_path, persist_dir=persist_dir, embedding_function=fake_embedding_function)
    return persist_dir


def test_retrieve_returns_question_answer_and_score(tmp_path, fake_embedding_function):
    persist_dir = _ingest(tmp_path, fake_embedding_function)

    results = rag.retrieve(
        "Cleaning ki fees kitni hai?",
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    assert len(results) > 0
    for r in results:
        assert set(r.keys()) == {"question", "answer", "score"}
        assert isinstance(r["score"], float)


def test_retrieve_respects_k(tmp_path, fake_embedding_function):
    persist_dir = _ingest(tmp_path, fake_embedding_function)

    results = rag.retrieve(
        "Cleaning ki fees kitni hai?",
        k=2,
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    assert len(results) == 2


def test_retrieve_orders_results_best_match_first(tmp_path, fake_embedding_function):
    persist_dir = _ingest(tmp_path, fake_embedding_function)

    results = rag.retrieve(
        "Cleaning ki fees kitni hai?",
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


class TestDedupeBestScore:
    """Each FAQ is indexed twice (question-only + question-and-answer, see
    app.rag.ingest) and can therefore appear twice in raw query results —
    this merges back to one entry per question, keeping the higher score."""

    def test_keeps_the_higher_scoring_duplicate(self):
        candidates = [
            {"question": "A?", "answer": "a", "score": 0.9},
            {"question": "B?", "answer": "b", "score": 0.95},
            {"question": "A?", "answer": "a", "score": 0.4},
        ]
        assert rag._dedupe_best_score(candidates) == [
            {"question": "B?", "answer": "b", "score": 0.95},
            {"question": "A?", "answer": "a", "score": 0.9},
        ]

    def test_no_duplicates_is_a_no_op_besides_sorting(self):
        candidates = [
            {"question": "A?", "answer": "a", "score": 0.4},
            {"question": "B?", "answer": "b", "score": 0.95},
        ]
        assert rag._dedupe_best_score(candidates) == [
            {"question": "B?", "answer": "b", "score": 0.95},
            {"question": "A?", "answer": "a", "score": 0.4},
        ]


def test_retrieve_exact_question_text_scores_near_one(tmp_path, fake_embedding_function):
    """Regression test for the bug where embedding "question\\nanswer"
    together diluted an exact question match's score to ~0.45 instead of
    ~1.0 (see docs/BUILD_PLAN.md phase 3 notes)."""
    persist_dir = _ingest(tmp_path, fake_embedding_function)

    results = rag.retrieve(
        "Cleaning ki fees kitni hai?",
        k=1,
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    assert results[0]["question"] == "Cleaning ki fees kitni hai?"
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-6)


def test_retrieve_on_empty_collection_returns_empty_list(tmp_path, fake_embedding_function):
    persist_dir = tmp_path / "chroma"

    results = rag.retrieve(
        "anything",
        persist_dir=persist_dir,
        embedding_function=fake_embedding_function,
    )

    assert results == []
