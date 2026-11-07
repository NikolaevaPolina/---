from __future__ import annotations

import logging

import requests

from .config import settings


logger = logging.getLogger(__name__)


def extract_tickets(updated_after=None) -> list[dict]:
    tickets: list[dict] = []
    offset = 0
    params: dict[str, object] = {"limit": settings.page_size, "offset": offset}
    if updated_after is not None:
        params["updated_after"] = updated_after.isoformat()

    while True:
        params["offset"] = offset
        response = requests.get(
            f"{settings.source_api_url}/tickets",
            params=params,
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        page = response.json()
        tickets.extend(page["items"])
        logger.info(
            "Extracted page: offset=%s count=%s total=%s",
            offset,
            len(page["items"]),
            page["total"],
        )
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    return tickets
