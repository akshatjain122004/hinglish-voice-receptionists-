from app.prompts import SYSTEM_PROMPT, build_system_prompt


def test_build_system_prompt_includes_the_clinic_name():
    prompt = build_system_prompt("Test Dental Clinic")
    assert "Test Dental Clinic" in prompt


def test_build_system_prompt_sets_the_two_sentence_limit():
    prompt = build_system_prompt("Test Dental Clinic")
    assert "2" in prompt


def test_build_system_prompt_forbids_inventing_slots():
    prompt = build_system_prompt("Test Dental Clinic").lower()
    assert "never" in prompt and "tool" in prompt


def test_build_system_prompt_requires_confirmation_before_booking():
    prompt = build_system_prompt("Test Dental Clinic").lower()
    assert "confirm" in prompt


def test_default_system_prompt_loads_the_real_clinic_name():
    assert "Mehta Dental Clinic" in SYSTEM_PROMPT


def test_build_system_prompt_never_asks_for_the_phone_number():
    prompt = build_system_prompt("Test Dental Clinic").lower()
    assert "never ask" in prompt and "phone" in prompt
