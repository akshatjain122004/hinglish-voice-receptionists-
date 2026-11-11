import pytest

from app.speech import detect_lang, normalise_for_speech


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        # --- from the build plan ---
        ("Kal shaam 17:30 par aa jaiyega.", "hi", "Kal shaam saade paanch baje par aa jaiyega."),
        ("Cleaning ki fees ₹500 hai.", "hi", "Cleaning ki fees paanch sau rupaye hai."),
        # --- times, Hindi: o'clock, quarter-past, half-past, quarter-to ---
        ("Subah 10:00 khulte hain.", "hi", "Subah das baje khulte hain."),
        ("Shaam 20:00 band.", "hi", "Shaam aath baje band."),
        ("Appointment 17:15 par hai.", "hi", "Appointment sava paanch baje par hai."),
        ("Appointment 17:45 par hai.", "hi", "Appointment paune chhe baje par hai."),
        ("Raat 00:00 par.", "hi", "Raat baarah baje par."),
        # --- times, English equivalents ---
        ("The clinic opens at 10:00.", "en", "The clinic opens at ten o'clock."),
        ("It closes at 20:00.", "en", "It closes at eight o'clock."),
        ("Your slot is at 17:15.", "en", "Your slot is at quarter past five."),
        ("Your slot is at 17:30.", "en", "Your slot is at half past five."),
        ("Your slot is at 17:45.", "en", "Your slot is at quarter to six."),
        # --- a real, observed LLM slip (Phase 3 close-out): digits AND the
        # Hindi time-marker word written together must not duplicate it ---
        ("Subah 10:00 baje khulte hain.", "hi", "Subah das baje khulte hain."),
        ("Sava 17:15 par.", "hi", "sava paanch baje par."),
        ("Paune 17:45 par.", "hi", "paune chhe baje par."),
        # --- prices, Hindi ---
        ("Consultation ₹200 hai.", "hi", "Consultation do sau rupaye hai."),
        ("Cleaning ₹500 hai.", "hi", "Cleaning paanch sau rupaye hai."),
        ("Filling Rs 1500 hai.", "hi", "Filling pandrah sau rupaye hai."),
        ("Filling Rs. 1500 hai.", "hi", "Filling pandrah sau rupaye hai."),
        ("Whitening ₹3000 ki hai.", "hi", "Whitening teen hazar rupaye ki hai."),
        ("Root canal ₹4000 ka hai.", "hi", "Root canal chaar hazar rupaye ka hai."),
        # --- prices, English ---
        ("Cleaning is ₹500.", "en", "Cleaning is five hundred rupees."),
        ("That costs Rs. 1500.", "en", "That costs fifteen hundred rupees."),
        ("Whitening is ₹3000.", "en", "Whitening is three thousand rupees."),
        # --- a non-round price is left exactly as written, not guessed at ---
        ("Iska price ₹350 hai.", "hi", "Iska price ₹350 hai."),
        # --- phone numbers, read digit-by-digit in pairs ---
        (
            "Emergency ho to +919829000001 par call karein.",
            "hi",
            "Emergency ho to nau ek, nau aath, do nau, zero zero, zero zero, zero ek par call karein.",
        ),
        (
            "Call +919829000001 for emergencies.",
            "en",
            "Call nine one, nine eight, two nine, zero zero, zero zero, zero one for emergencies.",
        ),
        # --- unchanged: no matching pattern at all ---
        ("Namaste! Kaise madad kar sakti hoon?", "hi", "Namaste! Kaise madad kar sakti hoon?"),
        ("Hello! How can I help you today?", "en", "Hello! How can I help you today?"),
        # --- unchanged: already in spoken form ---
        ("Kal saade paanch baje free hai.", "hi", "Kal saade paanch baje free hai."),
        ("It's five hundred rupees.", "en", "It's five hundred rupees."),
        # --- unchanged: a date-shaped mention, not a time/price/phone pattern ---
        ("Humari booking window 30 din ki hai.", "hi", "Humari booking window 30 din ki hai."),
        ("We're open every day except Sunday.", "en", "We're open every day except Sunday."),
    ],
)
def test_normalise_for_speech(text, lang, expected):
    assert normalise_for_speech(text, lang) == expected


@pytest.mark.parametrize(
    "text,lang",
    [
        ("17:30", "nl"),  # an unknown lang code defaults to Hindi/Hinglish
    ],
)
def test_unknown_lang_defaults_to_hindi(text, lang):
    assert normalise_for_speech(text, lang) == "saade paanch baje"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("हाँ, कर दीजिये.", "hi"),  # Devanagari
        ("Kal shaam saade paanch baje aa jaiyega.", "hi"),
        ("Emergency ho to yeh number try karein.", "hi"),
        ("Haan, theek hai.", "hi"),
        ("Hello, how can I help you today?", "en"),
        ("Your appointment is confirmed for tomorrow.", "en"),
        ("", "en"),
    ],
)
def test_detect_lang(text, expected):
    assert detect_lang(text) == expected
