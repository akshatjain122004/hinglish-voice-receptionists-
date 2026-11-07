"""Settings loaded from environment variables / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sarvam_api_key: str

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    google_service_account_json: str = ""
    google_calendar_id: str = ""

    public_base_url: str = ""
    dashboard_password: str = ""
    daily_budget_inr: int = 50


def get_settings() -> Settings:
    return Settings()
