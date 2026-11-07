from datetime import date, datetime

import pytest

from app.timeparse import TimeParseError, parse, parse_date

NOW = datetime(2026, 11, 9, 10, 0)  # Monday


@pytest.mark.parametrize(
    "text,expected",
    [
        # --- from the build plan ---
        ("kal shaam saade paanch", datetime(2026, 11, 10, 17, 30)),
        ("parso subah 10 baje", datetime(2026, 11, 11, 10, 0)),
        ("aaj paune chhe", datetime(2026, 11, 9, 17, 45)),
        ("Friday 4 pm", datetime(2026, 11, 13, 16, 0)),
        # --- relative days, English ---
        ("today 10am", datetime(2026, 11, 9, 10, 0)),
        ("tomorrow 5:30 pm", datetime(2026, 11, 10, 17, 30)),
        ("day after tomorrow quarter to six", datetime(2026, 11, 11, 17, 45)),
        ("today half past five", datetime(2026, 11, 9, 17, 30)),
        ("tomorrow quarter past five", datetime(2026, 11, 10, 17, 15)),
        # --- relative days, Hinglish ---
        ("aaj subah sava das", datetime(2026, 11, 9, 10, 15)),
        ("kal dopahar 2 baje", datetime(2026, 11, 10, 14, 0)),
        ("kal raat 9 baje", datetime(2026, 11, 10, 21, 0)),
        ("parso shaam paune saat", datetime(2026, 11, 11, 18, 45)),
        ("aaj 11 baje", datetime(2026, 11, 9, 11, 0)),
        ("kal 3 baje", datetime(2026, 11, 10, 15, 0)),
        ("parso 12 baje", datetime(2026, 11, 11, 12, 0)),
        ("aaj raat 12 baje", datetime(2026, 11, 9, 0, 0)),
        ("kal subah saade nau", datetime(2026, 11, 10, 9, 30)),
        ("parso 6:15 pm", datetime(2026, 11, 11, 18, 15)),
        ("aaj 9:45 am", datetime(2026, 11, 9, 9, 45)),
        # --- English weekday names ---
        ("Tuesday 9 am", datetime(2026, 11, 10, 9, 0)),
        ("Wednesday 5 pm", datetime(2026, 11, 11, 17, 0)),
        ("Thursday sava paanch", datetime(2026, 11, 12, 17, 15)),
        ("Saturday 10:30", datetime(2026, 11, 14, 10, 30)),
        ("Sunday subah 8 baje", datetime(2026, 11, 15, 8, 0)),
        ("Monday 11 am", datetime(2026, 11, 9, 11, 0)),
        # --- Hindi (romanised) weekday names ---
        ("somvaar 4 pm", datetime(2026, 11, 9, 16, 0)),
        ("mangalvar subah 10 baje", datetime(2026, 11, 10, 10, 0)),
        ("budhwar shaam 6 baje", datetime(2026, 11, 11, 18, 0)),
        ("guruvar raat saade aath", datetime(2026, 11, 12, 20, 30)),
        ("shukravar sava gyarah", datetime(2026, 11, 13, 11, 15)),
        ("shanivar dopahar paune teen", datetime(2026, 11, 14, 14, 45)),
        ("raviwar 7 pm", datetime(2026, 11, 15, 19, 0)),
        ("itwar subah sava nau", datetime(2026, 11, 15, 9, 15)),
    ],
)
def test_parse(text, expected):
    assert parse(text, now=NOW) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello there",
        "kal cleaning chahiye",
    ],
)
def test_parse_raises_when_no_time_found(text):
    with pytest.raises(TimeParseError):
        parse(text, now=NOW)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("aaj", date(2026, 11, 9)),
        ("kal", date(2026, 11, 10)),
        ("parso", date(2026, 11, 11)),
        ("today", date(2026, 11, 9)),
        ("tomorrow", date(2026, 11, 10)),
        ("Friday", date(2026, 11, 13)),
        ("kal shaam", date(2026, 11, 10)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, now=NOW) == expected


def test_parse_date_raises_when_no_date_found():
    with pytest.raises(TimeParseError):
        parse_date("saade paanch baje", now=NOW)
