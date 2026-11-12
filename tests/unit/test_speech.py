import pytest

from app.speech import is_closing


@pytest.mark.parametrize(
    "text",
    [
        "No thank you.",
        "That's all, thanks.",
        "Okay, bye!",
        "नहीं जी बस अभी तो इतना ही।",
        "जी बिल्कुल धन्यवाद।",
        "नाही बस धन्यवाद.",
        "Haan theek hai, dhanyavaad.",
        "Bas itna hi chahiye tha, shukriya.",
    ],
)
def test_closing_phrases_are_detected(text):
    assert is_closing(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Mujhe kal consultation ke liye appointment chahiye.",
        "Can you check Friday evening slots?",
        "Haan, confirm kar do.",
        "What's the fee for cleaning?",
    ],
)
def test_non_closing_turns_are_not_detected(text):
    assert is_closing(text) is False
