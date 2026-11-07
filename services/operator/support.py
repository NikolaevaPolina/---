"""Explainable retrieval and draft preparation for a support specialist.

The returned score is lexical overlap on synthetic titles, not a probability
that a past resolution will solve the current request.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


def title_words(value: str) -> set[str]:
    return set(re.findall(r"[а-яёa-z0-9]+", value.casefold()))


def similarity_score(current: Mapping, candidate: Mapping, category: str | None) -> float:
    current_words = title_words(str(current["title"]))
    past_words = title_words(str(candidate["title"]))
    union = current_words | past_words
    overlap = len(current_words & past_words) / len(union) if union else 0.0
    service_match = current.get("service") == candidate.get("service")
    category_match = bool(category) and category == candidate.get("category")
    return round(0.8 * overlap + 0.1 * service_match + 0.1 * category_match, 4)


def rank_candidates(
    current: Mapping, candidates: Sequence[Mapping], category: str | None, limit: int = 3
) -> list[dict]:
    ranked = [
        {**candidate, "similarity": similarity_score(current, candidate, category)}
        for candidate in candidates
    ]
    ranked.sort(key=lambda row: (-row["similarity"], -int(row["ticket_id"])))
    return ranked[:limit]


def build_draft(current: Mapping, reference: Mapping | None) -> str:
    """Prepare a reviewable reply without claiming the new issue is resolved."""
    title = str(current["title"]).strip()
    if reference is None:
        return (
            f"Здравствуйте! Получили ваше обращение «{title}». "
            "Уточним обстоятельства и сообщим о дальнейших действиях после проверки."
        )
    past_resolution = str(reference["resolution_text"]).strip()
    return (
        f"Здравствуйте! Получили ваше обращение «{title}». "
        f"В похожем ранее решённом случае применялось следующее решение: {past_resolution} "
        "Проверим, подходит ли оно для вашего обращения, и сообщим результат."
    )
