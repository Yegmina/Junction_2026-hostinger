from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    cala_api_key: str | None
    cala_base_url: str
    openai_api_key: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str
    gemini_fallback_model: str
    context_dev_api_key: str | None
    oxylabs_api_key: str | None
    nvidia_api_key: str | None
    nemotron_model: str
    access_code: str | None
    request_timeout_seconds: float
    rate_limit_per_hour: int
    cors_origins: tuple[str, ...]

    @property
    def data_mode(self) -> str:
        return "cala" if self.cala_api_key else "demo"

    @property
    def analysis_mode(self) -> str:
        if self.openai_api_key:
            return "openai"
        return "gemini" if self.gemini_api_key else "demo"


def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        cala_api_key=os.getenv("CALA_API_KEY") or None,
        cala_base_url=(os.getenv("CALA_BASE_URL") or "https://api.cala.ai").rstrip("/"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL") or "gpt-5.5",
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL") or "gemini-flash-latest",
        gemini_fallback_model=os.getenv("GEMINI_FALLBACK_MODEL") or "gemini-flash-lite-latest",
        context_dev_api_key=os.getenv("CONTEXT_DEV_API_KEY") or None,
        oxylabs_api_key=os.getenv("OXYLABS_WEB_API_KEY") or None,
        nvidia_api_key=os.getenv("NVIDIA_API_KEY") or None,
        nemotron_model=os.getenv("NEMOTRON_MODEL") or "nvidia/nemotron-3.5-super-vl-120b-a12b",
        access_code=os.getenv("ACCESS_CODE") or None,
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS") or 120),
        rate_limit_per_hour=int(os.getenv("RATE_LIMIT_PER_HOUR") or 30),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )
