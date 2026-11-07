import pytest
from pydantic import ValidationError

from app.config import Settings


def test_config_loads_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SARVAM_API_KEY=test-key\nDAILY_BUDGET_INR=75\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=str(env_file))

    assert settings.sarvam_api_key == "test-key"
    assert settings.daily_budget_inr == 75


def test_missing_required_key_raises(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DAILY_BUDGET_INR=75\n")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=str(env_file))
