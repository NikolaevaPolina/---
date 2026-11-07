from __future__ import annotations

import os
from dataclasses import dataclass, field


def _required_password() -> str:
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD must be set in the local .env file")
    return password


@dataclass(frozen=True)
class Settings:
    postgres_host: str = os.getenv("POSTGRES_HOST", "db")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "support_dw")
    postgres_user: str = os.getenv("POSTGRES_USER", "support")
    postgres_password: str = field(default_factory=_required_password, repr=False)
    source_api_url: str = os.getenv("SOURCE_API_URL", "http://mock-api:8000")
    page_size: int = int(os.getenv("PAGE_SIZE", "500"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))


settings = Settings()
