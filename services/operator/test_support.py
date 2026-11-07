"""Focused checks for ranking and safe draft wording."""

import unittest

from support import build_draft, rank_candidates


class SupportTests(unittest.TestCase):
    def test_same_title_ranks_first(self):
        current = {"title": "Не отправляется письмо", "service": "Почта"}
        candidates = [
            {"ticket_id": 1, "title": "Сброс пароля", "service": "Почта", "category": "Почта"},
            {"ticket_id": 2, "title": "Не отправляется письмо", "service": "Почта", "category": "Почта"},
        ]
        ranked = rank_candidates(current, candidates, "Почта")
        self.assertEqual(ranked[0]["ticket_id"], 2)
        self.assertGreater(ranked[0]["similarity"], ranked[1]["similarity"])

    def test_draft_uses_past_tense_as_reference(self):
        current = {"title": "Не отправляется письмо"}
        reference = {"resolution_text": "Работа сервиса восстановлена."}
        draft = build_draft(current, reference)
        self.assertIn("в похожем ранее решённом случае", draft.lower())
        self.assertIn("Проверим, подходит ли оно", draft)


if __name__ == "__main__":
    unittest.main()
