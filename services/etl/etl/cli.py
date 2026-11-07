from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from uuid import uuid4

from .classification import run_classification
from .db import connect, get_watermark, set_watermark, wait_for_database
from .extract import extract_tickets
from .load import load_bronze
from .quality import run_quality_checks
from .queries import RunSQL
from .transform import refresh_gold, transform_silver


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("support-etl")


def execute(mode: str) -> dict:
    run_id = uuid4()
    started = time.perf_counter()
    stage = "database"
    logger.info("run_id=%s mode=%s stage=start status=running", run_id, mode)
    try:
        wait_for_database()
    except Exception as error:
        logger.error("run_id=%s stage=database status=failed error_type=%s", run_id, type(error).__name__)
        raise RuntimeError("Database is unavailable") from None
    extracted_count = loaded_count = processed_count = 0
    watermark_from = None
    watermark_to = None
    extract_seconds = load_seconds = transform_seconds = gold_seconds = model_seconds = 0.0
    model_result: dict = {}
    quality_results: list[dict] = []

    try:
        with connect() as connection:
            watermark_from = None if mode == "full" else get_watermark(connection)
            connection.execute(RunSQL.START, (run_id, mode, watermark_from))
            connection.commit()
    except Exception as error:
        logger.error("run_id=%s stage=journal_start status=failed error_type=%s", run_id, type(error).__name__)
        raise RuntimeError("Could not start ETL run") from None

    try:
        stage = "extract"
        stage_started = time.perf_counter()
        tickets = extract_tickets(watermark_from)
        extract_seconds = time.perf_counter() - stage_started
        extracted_count = len(tickets)
        logger.info("run_id=%s stage=extract status=success count=%s seconds=%.3f", run_id, extracted_count, extract_seconds)
        if tickets:
            watermark_to = max(datetime.fromisoformat(item["updated_at"]) for item in tickets)
        else:
            watermark_to = watermark_from

        with connect() as connection:
            stage = "load"
            stage_started = time.perf_counter()
            loaded_count = load_bronze(connection, tickets, run_id)
            load_seconds = time.perf_counter() - stage_started
            logger.info("run_id=%s stage=load status=success count=%s seconds=%.3f", run_id, loaded_count, load_seconds)
            stage = "transform"
            stage_started = time.perf_counter()
            processed_count = transform_silver(connection, run_id, mode) if tickets or mode == "full" else 0
            transform_seconds = time.perf_counter() - stage_started
            logger.info("run_id=%s stage=transform status=success count=%s seconds=%.3f", run_id, processed_count, transform_seconds)
            stage = "gold"
            stage_started = time.perf_counter()
            mart_rows = refresh_gold(connection, run_id, mode)
            gold_seconds = time.perf_counter() - stage_started
            logger.info("run_id=%s stage=gold status=success count=%s seconds=%.3f", run_id, mart_rows, gold_seconds)
            stage = "quality"
            stage_started = time.perf_counter()
            quality_results = run_quality_checks(connection, run_id)
            failed_checks = [result for result in quality_results if not result["passed"]]
            logger.info(
                "run_id=%s stage=quality status=%s count=%s failed=%s seconds=%.3f",
                run_id, "failed" if failed_checks else "success", len(quality_results),
                len(failed_checks), time.perf_counter() - stage_started,
            )
            if failed_checks:
                raise RuntimeError("Data quality checks failed")
            stage = "model"
            stage_started = time.perf_counter()
            model_result = run_classification(connection, run_id, mode)
            model_seconds = time.perf_counter() - stage_started
            logger.info(
                "run_id=%s stage=model status=success name=%s trained=%s count=%s seconds=%.3f",
                run_id, model_result["model_name"], model_result["trained"],
                model_result["scored_count"], model_seconds,
            )
            stage = "commit"
            if watermark_to is not None:
                set_watermark(connection, watermark_to)
            duration = time.perf_counter() - started
            connection.execute(
                RunSQL.SUCCESS,
                (
                    watermark_to, extracted_count, loaded_count, processed_count, duration,
                    extract_seconds, load_seconds, transform_seconds, gold_seconds,
                    model_seconds, model_result["scored_count"], run_id,
                ),
            )
            connection.commit()

        result = {
            "run_id": str(run_id),
            "status": "success",
            "mode": mode,
            "watermark_from": watermark_from.isoformat() if watermark_from else None,
            "watermark_to": watermark_to.isoformat() if watermark_to else None,
            "extracted_count": extracted_count,
            "loaded_count": loaded_count,
            "processed_count": processed_count,
            "duration_seconds": round(duration, 3),
            "stage_seconds": {
                "extract": round(extract_seconds, 3),
                "load": round(load_seconds, 3),
                "transform": round(transform_seconds, 3),
                "gold": round(gold_seconds, 3),
                "model": round(model_seconds, 3),
            },
            "classification": model_result,
            "quality_checks": quality_results,
        }
        logger.info("run_id=%s mode=%s stage=complete status=success seconds=%.3f", run_id, mode, duration)
        return result
    except Exception as error:
        duration = time.perf_counter() - started
        safe_error = f"{stage}: {type(error).__name__}"
        logger.error("run_id=%s mode=%s stage=%s status=failed error_type=%s", run_id, mode, stage, type(error).__name__)
        try:
            with connect() as connection:
                for result in quality_results:
                    connection.execute(
                        RunSQL.FAILED_CHECK,
                        (run_id, result["check"], result["passed"], result["actual"], "0"),
                    )
                connection.execute(
                    RunSQL.FAILURE,
                    (extracted_count, loaded_count, processed_count, duration, safe_error, run_id),
                )
                connection.commit()
        except Exception as journal_error:
            logger.error(
                "run_id=%s stage=journal_failure status=failed error_type=%s",
                run_id, type(journal_error).__name__,
            )
        raise RuntimeError(f"ETL run {run_id} failed during {stage}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Support data platform ETL")
    parser.add_argument("mode", choices=["full", "incremental"])
    args = parser.parse_args()
    try:
        result = execute(args.mode)
    except Exception as error:
        logger.error("command status=failed error_type=%s", type(error).__name__)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
