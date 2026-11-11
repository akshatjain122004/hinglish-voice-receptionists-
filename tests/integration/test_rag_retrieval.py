"""FAQ retrieval accuracy against the real multilingual embedding model.

No paid API is involved (the model runs locally on CPU), so this stays in
the default `pytest` run per docs/BUILD_PLAN.md Phase 3 — just note that the
very first run on a machine downloads the model weights from Hugging Face
(see .github/workflows/ci.yml for the CI cache that keeps that a one-time
cost).
"""

from __future__ import annotations

import pathlib

import pytest

from app import rag, tools

DATA = pathlib.Path("data")

# Paraphrases of the real FAQs in data/faqs.md, in Hinglish, Hindi and
# English, each noticeably reworded from the FAQ's own heading so the test
# exercises semantic retrieval rather than near-exact string matching.
PARAPHRASES = [
    ("cleaning ka kitna paisa lagta hai", "Cleaning ki fees kitni hai?"),
    ("first visit consultation fee kitni hai", "Consultation ka charge kya hai?"),
    ("aap subah kitne baje khulte hain", "Clinic kitne baje khulta hai?"),
    ("clinic dopahar mein kab band rehta hai", "Lunch break kab hota hai?"),
    ("is the clinic open on sundays?", "Clinic Sunday ko khula rehta hai kya?"),
    ("gaadi park karne ki jagah hai kya", "Parking ki facility hai kya?"),
    ("can I pay by card or UPI?", "Payment kaise kar sakte hain?"),
    ("mera insurance yahan chalega kya", "Health insurance accept karte hain kya?"),
    ("clinic ka address kya hai", "Clinic kahan located hai?"),
    ("dant mein bahut dard ho to kise call karein", "Emergency mein kya karein?"),
    ("do you treat small children's teeth?", "Bachon ka treatment hota hai kya?"),
    ("root canal treatment mein kitna waqt lagta hai", "Root canal mein kitna time lagta hai?"),
    ("teeth whitening kitne mein hoti hai", "Teeth whitening ka charge kya hai?"),
    (
        "mujhe apna appointment cancel karna hai, kaise karu",
        "Appointment cancel kar sakte hain kya?",
    ),
    ("who is the dentist here, what are their qualifications", "Doctor kaun hain?"),
    ("second opinion lene ke liye aana padega kya", "Second opinion ke liye aa sakte hain kya?"),
    ("is there digital x-ray available", "X-ray ki facility hai kya?"),
    ("filling mein kitna time jaata hai", "Filling karane mein kitna time lagta hai?"),
]

OUT_OF_SCOPE_QUESTIONS = [
    "cricket match ka score kya hai",
    "aaj ka weather kaisa hai",
    "MRI scan hota hai kya yahan",
    "what's the capital of France",
    "share market mein kya chal raha hai",
    "mobile phone recharge kaise karu",
]


@pytest.fixture(scope="session")
def faq_persist_dir(tmp_path_factory):
    persist_dir = tmp_path_factory.mktemp("rag_retrieval_chroma")
    rag.ingest(DATA / "faqs.md", persist_dir=persist_dir)
    return persist_dir


@pytest.mark.parametrize("query,expected_question", PARAPHRASES)
def test_paraphrase_retrieves_correct_faq_in_top_3(faq_persist_dir, query, expected_question):
    results = rag.retrieve(query, k=3, persist_dir=faq_persist_dir)
    assert expected_question in [r["question"] for r in results]


@pytest.mark.parametrize("query", OUT_OF_SCOPE_QUESTIONS)
def test_out_of_scope_question_scores_below_threshold(faq_persist_dir, query):
    results = rag.retrieve(query, k=1, persist_dir=faq_persist_dir)
    assert not results or results[0]["score"] < tools.FAQ_SCORE_THRESHOLD
