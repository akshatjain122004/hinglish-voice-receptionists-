import pytest

from app.stt_noise import is_noise


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "।",
        "॥",
        ".",
        ",",
        "...",
        "a",
        "?",
    ],
)
def test_noise_is_dropped(text):
    assert is_noise(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "haan",
        "हाँ",
        "जी",
        "ok",
        "na",
        "नहीं",
        "haan.",
        "  haan  ",
        "हाँ।",
    ],
)
def test_real_short_words_are_not_noise(text):
    assert is_noise(text) is False
