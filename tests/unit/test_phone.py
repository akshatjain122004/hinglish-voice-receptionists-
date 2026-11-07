import pytest

from app.booking import InvalidBookingError, normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "98290 12345",
        "+91-9829012345",
        "09829012345",
        "9829012345",
        "+919829012345",
    ],
)
def test_normalises_to_e164(raw):
    assert normalize_phone(raw) == "+919829012345"


@pytest.mark.parametrize("raw", ["", "123", "not a phone", "+1-555-0100"])
def test_garbage_input_raises(raw):
    with pytest.raises(InvalidBookingError):
        normalize_phone(raw)
