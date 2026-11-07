"""Небольшая нейронная сеть для сортировки закрытых заявок по теме.

Сеть обучается классифицировать тип синтетической проблемы. Её скрытый слой
используется как представление текста при поиске похожих заявок.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np


def _grams(value: str) -> list[str]:
    text = re.sub(r"\s+", " ", value.casefold()).strip()
    text = f"^{text}$"
    return [text[i : i + size] for size in (3, 4, 5) for i in range(len(text) - size + 1)]


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=1, keepdims=True)


class NeuralRanker:
    """Полносвязная сеть с одним скрытым слоем и воспроизводимым обучением."""

    def __init__(self, max_features: int = 768, hidden_size: int = 48, seed: int = 42):
        self.max_features = max_features
        self.hidden_size = hidden_size
        self.seed = seed
        self.vocabulary: list[str] = []
        self.labels: list[str] = []
        self.idf = np.empty(0, dtype=np.float32)

    def _features(self, texts: Sequence[str]) -> np.ndarray:
        positions = {gram: i for i, gram in enumerate(self.vocabulary)}
        matrix = np.zeros((len(texts), len(positions)), dtype=np.float32)
        for row, value in enumerate(texts):
            for gram, count in Counter(_grams(value)).items():
                column = positions.get(gram)
                if column is not None:
                    matrix[row, column] = float(count)
        matrix *= self.idf
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-8)

    def _hidden(self, features: np.ndarray) -> np.ndarray:
        return np.tanh(features @ self.w1 + self.b1)

    def predict_proba(self, texts: Sequence[str]) -> np.ndarray:
        hidden = self._hidden(self._features(texts))
        return _softmax(hidden @ self.w2 + self.b2)

    def predict(self, text: str) -> tuple[str, float]:
        probabilities = self.predict_proba([text])[0]
        index = int(np.argmax(probabilities))
        return self.labels[index], float(probabilities[index])

    def fit(
        self,
        train: Sequence[tuple[str, str]],
        validation: Sequence[tuple[str, str]],
        epochs: int = 300,
        learning_rate: float = 0.025,
        patience: int = 35,
    ) -> dict[str, float | int]:
        if not train or not validation:
            raise ValueError("Пустая обучающая или проверочная часть")
        self.labels = sorted({label for _, label in train})
        if any(label not in self.labels for _, label in validation):
            raise ValueError("В проверочной части есть неизвестный тип заявки")

        # Словарь строится только по обучающей части, чтобы не видеть новые темы заранее.
        counts = Counter(gram for text, _ in train for gram in set(_grams(text)))
        self.vocabulary = [gram for gram, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: self.max_features]]
        self.idf = np.asarray(
            [math.log((1 + len(train)) / (1 + counts[gram])) + 1 for gram in self.vocabulary],
            dtype=np.float32,
        )
        x_train = self._features([text for text, _ in train])
        x_val = self._features([text for text, _ in validation])
        label_ids = {label: i for i, label in enumerate(self.labels)}
        y_train = np.asarray([label_ids[label] for _, label in train])
        y_val = np.asarray([label_ids[label] for _, label in validation])

        rng = np.random.default_rng(self.seed)
        self.w1 = rng.normal(0, math.sqrt(2 / max(x_train.shape[1], 1)), (x_train.shape[1], self.hidden_size)).astype(np.float32)
        self.b1 = np.zeros(self.hidden_size, dtype=np.float32)
        self.w2 = rng.normal(0, math.sqrt(2 / self.hidden_size), (self.hidden_size, len(self.labels))).astype(np.float32)
        self.b2 = np.zeros(len(self.labels), dtype=np.float32)

        params = [self.w1, self.b1, self.w2, self.b2]
        first = [np.zeros_like(param) for param in params]
        second = [np.zeros_like(param) for param in params]
        best_state = [param.copy() for param in params]
        best_loss = float("inf")
        best_epoch = 0
        stale = 0
        regularization = 1e-4

        for epoch in range(1, epochs + 1):
            hidden = self._hidden(x_train)
            probabilities = _softmax(hidden @ self.w2 + self.b2)
            gradient = probabilities.copy()
            gradient[np.arange(len(y_train)), y_train] -= 1
            gradient /= len(y_train)
            dw2 = hidden.T @ gradient + regularization * self.w2
            db2 = np.sum(gradient, axis=0)
            dh = (gradient @ self.w2.T) * (1 - hidden * hidden)
            dw1 = x_train.T @ dh + regularization * self.w1
            db1 = np.sum(dh, axis=0)

            # Adam подбирает размер шага отдельно для каждого веса сети.
            for i, (param, grad) in enumerate(zip(params, (dw1, db1, dw2, db2))):
                first[i] = 0.9 * first[i] + 0.1 * grad
                second[i] = 0.999 * second[i] + 0.001 * grad * grad
                corrected_first = first[i] / (1 - 0.9**epoch)
                corrected_second = second[i] / (1 - 0.999**epoch)
                param -= learning_rate * corrected_first / (np.sqrt(corrected_second) + 1e-8)

            validation_probabilities = _softmax(self._hidden(x_val) @ self.w2 + self.b2)
            loss = -float(np.mean(np.log(np.maximum(validation_probabilities[np.arange(len(y_val)), y_val], 1e-8))))
            if loss < best_loss - 1e-4:
                best_loss = loss
                best_epoch = epoch
                best_state = [param.copy() for param in params]
                stale = 0
            else:
                stale += 1
                if stale >= patience:
                    break

        for param, value in zip(params, best_state):
            param[:] = value
        return {"epochs": best_epoch, "validation_loss": round(best_loss, 4)}

    def rank(self, current: Mapping, candidates: Sequence[Mapping], limit: int = 3) -> list[dict]:
        if not candidates:
            return []
        features = self._features([str(current["title"])] + [str(row["title"]) for row in candidates])
        hidden = self._hidden(features)
        norms = np.linalg.norm(hidden, axis=1)
        similarity = (hidden[1:] @ hidden[0]) / np.maximum(norms[1:] * norms[0], 1e-8)
        ranked = []
        for row, value in zip(candidates, similarity):
            # Сервис уточняет порядок близких результатов; текст определяет основную долю.
            service_bonus = 0.05 if row.get("service") == current.get("service") else 0.0
            ranked.append({**row, "similarity": round(float(0.95 * (value + 1) / 2 + service_bonus), 4)})
        ranked.sort(key=lambda row: (-row["similarity"], -int(row["ticket_id"])))
        return ranked[:limit]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, vocabulary=np.asarray(self.vocabulary), labels=np.asarray(self.labels),
            idf=self.idf, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2,
        )

    @classmethod
    def load(cls, path: Path) -> "NeuralRanker":
        # Загрузка без pickle разрешает только числовые массивы и строки.
        with np.load(path, allow_pickle=False) as data:
            instance = cls(hidden_size=int(data["w1"].shape[1]))
            instance.vocabulary = data["vocabulary"].tolist()
            instance.labels = data["labels"].tolist()
            instance.idf = data["idf"].astype(np.float32)
            for name in ("w1", "b1", "w2", "b2"):
                setattr(instance, name, data[name].astype(np.float32))
        return instance


def classification_metrics(model: NeuralRanker, examples: Sequence[tuple[str, str]]) -> dict[str, float | int]:
    probabilities = model.predict_proba([text for text, _ in examples])
    actual = np.asarray([model.labels.index(label) for _, label in examples])
    order = np.argsort(-probabilities, axis=1)
    return {
        "examples": len(examples),
        "top1": round(float(np.mean(order[:, 0] == actual)), 4),
        "top3": round(float(np.mean(np.any(order[:, :3] == actual[:, None], axis=1))), 4),
    }


def lexical_baseline(train: Sequence[tuple[str, str]], test: Sequence[tuple[str, str]]) -> dict[str, float | int]:
    def words(value: str) -> set[str]:
        return set(re.findall(r"[а-яёa-z0-9]+", value.casefold()))

    references = [(words(text), label) for text, label in train]
    correct = 0
    for text, true_label in test:
        current = words(text)
        scores: dict[str, float] = {}
        for reference, label in references:
            denominator = len(current | reference)
            score = len(current & reference) / denominator if denominator else 0.0
            scores[label] = max(scores.get(label, 0.0), score)
        predicted = max(sorted(scores), key=lambda label: scores[label])
        correct += predicted == true_label
    return {"examples": len(test), "top1": round(correct / len(test), 4)}


def retrieval_metrics(
    model: NeuralRanker,
    test: Sequence[tuple[str, str]],
    service_by_title: Mapping[str, str],
) -> dict[str, float | int]:
    """Сравнить два способа поиска по одним и тем же новым формулировкам."""
    from support import rank_candidates

    candidates = [
        {"ticket_id": i + 1, "title": label, "service": service_by_title[label], "category": ""}
        for i, label in enumerate(model.labels)
    ]
    neural_first = neural_three = lexical_first = lexical_three = 0
    for title, expected in test:
        service = service_by_title[expected]
        query = {"title": title, "service": service}
        # Экран специалиста также отбирает закрытые заявки по сервису.
        selected = [row for row in candidates if row["service"] == service]
        neural_result = model.rank(query, selected, limit=3)
        lexical_result = rank_candidates(query, selected, None, limit=3)
        neural_first += neural_result[0]["title"] == expected
        neural_three += any(row["title"] == expected for row in neural_result)
        lexical_first += lexical_result[0]["title"] == expected
        lexical_three += any(row["title"] == expected for row in lexical_result)
    count = len(test)
    return {
        "examples": count,
        "candidates_per_query": 3,
        "neural_recall_at_1": round(neural_first / count, 4),
        "neural_recall_at_3": round(neural_three / count, 4),
        "lexical_recall_at_1": round(lexical_first / count, 4),
        "lexical_recall_at_3": round(lexical_three / count, 4),
    }
