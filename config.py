"""
config.py — Application settings loaded from environment variables.
All required secrets and optional defaults are declared here.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # SendGrid
    sendgrid_api_key: str
    sendgrid_from_email: str

    # Database
    database_url: str = "sqlite:///./ready_concierge.db"

    # Company / property / stream defaults (used when seeding the first tenant)
    default_company_name: str = "Default Company"
    default_hotel_name: str = "Park Hyatt Aviara"   # legacy alias
    default_property_name: str = "Park Hyatt Aviara"
    default_stream_name: str = "Concierge"
    default_staff_email: str = ""
    default_signal_recipients: str = ""  # comma-separated emails

    # Claude models
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-6"

    # Base URL for the API (used to build feedback links in draft emails)
    base_url: str = "https://web-production-615a3.up.railway.app"

    # Feedback signing secret (HMAC key for one-click feedback tokens)
    feedback_secret: str = "change-me-in-production"

    # Signal thresholds
    volume_spike_default: int = 3
    volume_spike_dining: int = 5
    celebration_cluster_threshold: int = 2
    time_cluster_window_hours: int = 2

    class Config:
        env_file = ".env"
        extra = "ignore"

    @field_validator("anthropic_api_key", "sendgrid_api_key", "sendgrid_from_email")
    @classmethod
    def must_not_be_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()
