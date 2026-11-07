"""Обучение нейросетевого поиска на синтетических закрытых заявках."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from neural import NeuralRanker, classification_metrics, lexical_baseline, retrieval_metrics
from neural_data import SERVICE_BY_TITLE, make_splits
from repository import DatabaseSettings, OperatorRepository


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("support-neural-training")
MODEL_PATH = Path(os.getenv("NEURAL_MODEL_PATH", "/models/neural_ranker.npz"))


def main() -> int:
    try:
        repository = OperatorRepository(DatabaseSettings.from_environment())
        closed_titles = repository.training_titles()
        train, validation, test = make_splits(closed_titles)
        logger.info(
            "training_start closed_title_count=%d train=%d validation=%d test=%d",
            len(closed_titles), len(train), len(validation), len(test),
        )
        model = NeuralRanker(seed=42)
        training = model.fit(train, validation)
        result = {
            "dataset": "synthetic_paraphrases_of_closed_ticket_titles",
            "closed_title_count": len(closed_titles),
            "classes": len(model.labels),
            "train_examples": len(train),
            "validation": classification_metrics(model, validation),
            "test": classification_metrics(model, test),
            "lexical_baseline_test": lexical_baseline(train, test),
            "retrieval_test": retrieval_metrics(model, test, SERVICE_BY_TITLE),
            "training": training,
            "limitation": "15 held-out synthetic formulations; no estimate for real support tickets",
        }
        model.save(MODEL_PATH)
        metrics_path = MODEL_PATH.with_suffix(".json")
        metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "training_complete classes=%d epochs=%d test_top1=%.4f baseline_top1=%.4f",
            len(model.labels), training["epochs"], result["test"]["top1"],
            result["lexical_baseline_test"]["top1"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        logger.error("training_failed error_type=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
