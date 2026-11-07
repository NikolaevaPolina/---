"""Reproducible category recommendations from synthetic ticket titles.

Only the title is a feature. The service, description and recorded category are
excluded from inference because the synthetic generator exposes the answer there.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from .queries import ClassificationSQL


def tokenize(title: str) -> Counter[str]:
    return Counter(re.findall(r"[а-яёa-z]+", title.lower()))


class NaiveBayesClassifier:
    name = "multinomial_naive_bayes"

    def fit(self, examples: list[tuple[str, str]]) -> None:
        self.documents: Counter[str] = Counter()
        self.words: dict[str, Counter[str]] = defaultdict(Counter)
        for title, category in examples:
            self.documents[category] += 1
            self.words[category].update(tokenize(title))
        self.vocabulary = set().union(*(set(words) for words in self.words.values()))

    def predict(self, title: str) -> tuple[str, float]:
        tokens = tokenize(title)
        categories = sorted(self.documents)
        total_documents = sum(self.documents.values())
        vocabulary_size = max(len(self.vocabulary), 1)
        scores = {}
        for category in categories:
            word_counts = self.words[category]
            denominator = sum(word_counts.values()) + vocabulary_size
            score = math.log(self.documents[category] / total_documents)
            score += sum(
                count * math.log((word_counts.get(word, 0) + 1) / denominator)
                for word, count in tokens.items()
            )
            scores[category] = score
        best = max(categories, key=lambda category: (scores[category], category))
        anchor = max(scores.values())
        normalizer = sum(math.exp(score - anchor) for score in scores.values())
        return best, math.exp(scores[best] - anchor) / normalizer

    def to_dict(self) -> dict:
        return {
            "type": self.name,
            "documents": dict(self.documents),
            "words": {label: dict(counts) for label, counts in self.words.items()},
            "vocabulary": sorted(self.vocabulary),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NaiveBayesClassifier":
        instance = cls()
        instance.documents = Counter(data["documents"])
        instance.words = {label: Counter(counts) for label, counts in data["words"].items()}
        instance.vocabulary = set(data["vocabulary"])
        return instance


class CentroidClassifier:
    name = "word_frequency_centroid"

    def fit(self, examples: list[tuple[str, str]]) -> None:
        self.documents: Counter[str] = Counter()
        self.centroids: dict[str, Counter[str]] = defaultdict(Counter)
        for title, category in examples:
            self.documents[category] += 1
            self.centroids[category].update(tokenize(title))
        self.norms = {
            category: math.sqrt(sum(value * value for value in counts.values()))
            for category, counts in self.centroids.items()
        }

    def predict(self, title: str) -> tuple[str, float]:
        tokens = tokenize(title)
        token_norm = math.sqrt(sum(value * value for value in tokens.values()))
        scores = {}
        for category in sorted(self.documents):
            numerator = sum(
                count * self.centroids[category].get(word, 0)
                for word, count in tokens.items()
            )
            denominator = token_norm * self.norms[category]
            scores[category] = numerator / denominator if denominator else 0.0
        best = max(scores, key=lambda category: (scores[category], category))
        # Scores are cosine similarities. Softmax provides a bounded display
        # value, not a calibrated probability on real service-desk data.
        anchor = max(scores.values())
        normalizer = sum(math.exp(4 * (score - anchor)) for score in scores.values())
        return best, 1 / normalizer

    def to_dict(self) -> dict:
        return {
            "type": self.name,
            "documents": dict(self.documents),
            "centroids": {label: dict(counts) for label, counts in self.centroids.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CentroidClassifier":
        instance = cls()
        instance.documents = Counter(data["documents"])
        instance.centroids = {
            label: Counter(counts) for label, counts in data["centroids"].items()
        }
        instance.norms = {
            category: math.sqrt(sum(value * value for value in counts.values()))
            for category, counts in instance.centroids.items()
        }
        return instance


CLASSIFIERS = {
    NaiveBayesClassifier.name: NaiveBayesClassifier,
    CentroidClassifier.name: CentroidClassifier,
}


def evaluate(model, examples: list[tuple[str, str]], labels: list[str]) -> dict:
    if not examples:
        return {"count": 0, "accuracy": None, "error": None, "macro_f1": None}
    outcomes = [(truth, model.predict(title)[0]) for title, truth in examples]
    correct = sum(truth == predicted for truth, predicted in outcomes)
    f1_values = []
    for label in labels:
        tp = sum(truth == label and predicted == label for truth, predicted in outcomes)
        fp = sum(truth != label and predicted == label for truth, predicted in outcomes)
        fn = sum(truth == label and predicted != label for truth, predicted in outcomes)
        denominator = 2 * tp + fp + fn
        f1_values.append(2 * tp / denominator if denominator else 0.0)
    accuracy = correct / len(outcomes)
    return {
        "count": len(examples),
        "accuracy": round(accuracy, 4),
        "error": round(1 - accuracy, 4),
        "macro_f1": round(sum(f1_values) / len(labels), 4),
    }


def ensure_schema(connection: psycopg.Connection) -> None:
    """Upgrade an existing local volume as well as a fresh initialized database."""
    connection.execute(ClassificationSQL.ALTER_RUNS)
    connection.execute(ClassificationSQL.CREATE_MODEL_VERSIONS)
    connection.execute(ClassificationSQL.CREATE_PREDICTIONS)
    connection.execute(ClassificationSQL.CREATE_PREDICTIONS_INDEX)


def train_model(connection: psycopg.Connection, run_id: UUID) -> tuple[UUID, object, dict]:
    rows = connection.execute(ClassificationSQL.TRAINING_ROWS).fetchall()
    if len(rows) < 25:
        raise RuntimeError("At least 25 resolved tickets are required for classification")
    labels = sorted({category for _, _, category in rows})
    if len(labels) < 2:
        raise RuntimeError("At least two categories are required for classification")

    train_rows = [(ticket_id, title, category) for ticket_id, title, category in rows if ticket_id % 5]
    record_train = [(title, category) for _, title, category in train_rows]
    record_test = [(title, category) for ticket_id, title, category in rows if not ticket_id % 5]
    if not record_train or not record_test:
        raise RuntimeError("The deterministic 80/20 split is empty")

    # Hold out one complete title template per category to expose the
    # optimistic score caused by repeated synthetic phrases.
    templates = defaultdict(set)
    for _, title, category in train_rows:
        templates[category].add(title)
    held_out = {category: sorted(titles)[-1] for category, titles in templates.items() if len(titles) >= 2}
    template_train = [(title, category) for _, title, category in train_rows if title != held_out.get(category)]
    template_test = [(title, category) for _, title, category in train_rows if title == held_out.get(category)]

    metrics = {}
    for name, classifier_type in CLASSIFIERS.items():
        candidate = classifier_type()
        candidate.fit(record_train)
        train_metrics = evaluate(candidate, record_train, labels)
        test_metrics = evaluate(candidate, record_test, labels)
        template_metrics = {"count": 0, "accuracy": None, "error": None, "macro_f1": None}
        if template_train and template_test:
            template_candidate = classifier_type()
            template_candidate.fit(template_train)
            template_metrics = evaluate(template_candidate, template_test, labels)
        metrics[name] = {
            "train": train_metrics,
            "record_test": test_metrics,
            "template_test": template_metrics,
        }

    selected_name = max(
        metrics,
        key=lambda name: (
            metrics[name]["template_test"]["macro_f1"] or 0,
            name,
        ),
    )
    model = CLASSIFIERS[selected_name]()
    model.fit([(title, category) for _, title, category in rows])
    model_id = uuid4()
    selected = metrics[selected_name]
    majority = Counter(category for _, category in record_train).most_common(1)[0][0]
    baseline = round(sum(category == majority for _, category in record_test) / len(record_test), 4)
    connection.execute(
        ClassificationSQL.SAVE_MODEL,
        (
            model_id, run_id, selected_name, len(rows), len(record_test),
            selected["record_test"]["accuracy"], selected["record_test"]["macro_f1"],
            selected["template_test"]["count"], selected["template_test"]["accuracy"],
            selected["template_test"]["macro_f1"], baseline,
            Jsonb(metrics), Jsonb(model.to_dict()),
        ),
    )
    return model_id, model, {
        "model_name": selected_name,
        "model_id": str(model_id),
        "training_count": len(rows),
        "record_test_count": len(record_test),
        "record_accuracy": selected["record_test"]["accuracy"],
        "record_macro_f1": selected["record_test"]["macro_f1"],
        "template_test_count": selected["template_test"]["count"],
        "template_accuracy": selected["template_test"]["accuracy"],
        "template_macro_f1": selected["template_test"]["macro_f1"],
        "majority_baseline": baseline,
        "candidate_metrics": metrics,
        "trained": True,
    }


def latest_model(connection: psycopg.Connection) -> tuple[UUID, object, dict] | None:
    row = connection.execute(ClassificationSQL.LATEST_MODEL).fetchone()
    if row is None:
        return None
    model_id, name, payload = row
    return model_id, CLASSIFIERS[name].from_dict(payload), {
        "model_name": name, "model_id": str(model_id), "trained": False
    }


def run_classification(connection: psycopg.Connection, run_id: UUID, mode: str) -> dict:
    ensure_schema(connection)
    existing = latest_model(connection) if mode == "incremental" else None
    model_id, model, result = existing or train_model(connection, run_id)

    if mode == "full" or existing is None:
        connection.execute(ClassificationSQL.DELETE_ALL_PREDICTIONS)
        rows = connection.execute(ClassificationSQL.OPEN_TICKETS_FULL).fetchall()
    else:
        connection.execute(ClassificationSQL.DELETE_RESOLVED_PREDICTIONS, (run_id,))
        rows = connection.execute(ClassificationSQL.OPEN_TICKETS_BATCH, (run_id,)).fetchall()

    predictions = []
    for ticket_id, title, source_category, updated_at in rows:
        predicted_category, confidence = model.predict(title)
        predictions.append(
            (ticket_id, title, source_category, predicted_category,
             round(confidence, 4), model_id, updated_at)
        )
    if predictions:
        with connection.cursor() as cursor:
            cursor.executemany(ClassificationSQL.UPSERT_PREDICTIONS, predictions)
    result["scored_count"] = len(predictions)
    return result
