from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://support:support@db:5432/support_dw"
    )
    source_api_url: str = os.getenv("SOURCE_API_URL", "http://mock-api:8000")
    page_size: int = int(os.getenv("PAGE_SIZE", "500"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))


settings = Settings()
