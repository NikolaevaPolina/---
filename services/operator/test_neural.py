"""Проверки разделения данных и сохранения обученной сети."""

import tempfile
import unittest
from pathlib import Path

from neural import NeuralRanker, classification_metrics
from neural_data import VARIANTS, make_splits


class NeuralTests(unittest.TestCase):
    def test_phrases_do_not_cross_splits(self):
        train, validation, test = make_splits(set(VARIANTS))
        self.assertEqual((len(train), len(validation), len(test)), (135, 15, 15))
        self.assertFalse({text for text, _ in train} & {text for text, _ in validation})
        self.assertFalse({text for text, _ in train} & {text for text, _ in test})
        self.assertFalse({text for text, _ in validation} & {text for text, _ in test})

    def test_model_can_be_saved_and_used_for_ranking(self):
        labels = set(list(VARIANTS)[:3])
        train, validation, test = make_splits(labels)
        model = NeuralRanker(max_features=256, hidden_size=16)
        model.fit(train, validation, epochs=30)
        metrics = classification_metrics(model, test)
        self.assertEqual(metrics["examples"], 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            model.save(path)
            restored = NeuralRanker.load(path)
            self.assertEqual(model.predict(test[0][0])[0], restored.predict(test[0][0])[0])
            candidates = [
                {"ticket_id": i + 1, "title": label, "service": "Почта"}
                for i, label in enumerate(sorted(labels))
            ]
            ranked = restored.rank({"title": test[0][0], "service": "Почта"}, candidates)
            self.assertEqual(len(ranked), 3)
            self.assertTrue(all(0 <= row["similarity"] <= 1 for row in ranked))


if __name__ == "__main__":
    unittest.main()
