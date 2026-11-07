from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from .classification import run_classification
from .db import connect, get_watermark, set_watermark, wait_for_database
from .extract import extract_tickets
from .load import load_bronze
from .quality import run_quality_checks
from .transform import refresh_gold, transform_silver


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("support-etl")


def execute(mode: str) -> dict:
    wait_for_database()
    run_id = uuid4()
    started = time.perf_counter()
    extracted_count = loaded_count = processed_count = 0
    watermark_from = None
    watermark_to = None
    extract_seconds = load_seconds = transform_seconds = gold_seconds = model_seconds = 0.0
    model_result: dict = {}
    quality_results: list[dict] = []

    with connect() as connection:
        watermark_from = None if mode == "full" else get_watermark(connection)
        connection.execute(
            """
            INSERT INTO meta.etl_runs (run_id, mode, status, watermark_from)
            VALUES (%s, %s, 'running', %s)
            """,
            (run_id, mode, watermark_from),
        )
        connection.commit()

    try:
        stage_started = time.perf_counter()
        tickets = extract_tickets(watermark_from)
        extract_seconds = time.perf_counter() - stage_started
        extracted_count = len(tickets)
        if tickets:
            watermark_to = max(datetime.fromisoformat(item["updated_at"]) for item in tickets)
        else:
            watermark_to = watermark_from

        with connect() as connection:
            stage_started = time.perf_counter()
            loaded_count = load_bronze(connection, tickets, run_id)
            load_seconds = time.perf_counter() - stage_started
            stage_started = time.perf_counter()
            processed_count = transform_silver(connection, run_id, mode) if tickets or mode == "full" else 0
            transform_seconds = time.perf_counter() - stage_started
            stage_started = time.perf_counter()
            refresh_gold(connection, run_id, mode)
            gold_seconds = time.perf_counter() - stage_started
            quality_results = run_quality_checks(connection, run_id)
            failed_checks = [result for result in quality_results if not result["passed"]]
            if failed_checks:
                raise RuntimeError(f"Data quality checks failed: {failed_checks}")
            stage_started = time.perf_counter()
            model_result = run_classification(connection, run_id, mode)
            model_seconds = time.perf_counter() - stage_started
            if watermark_to is not None:
                set_watermark(connection, watermark_to)
            duration = time.perf_counter() - started
            connection.execute(
                """
                UPDATE meta.etl_runs
                SET status = 'success', finished_at = now(), watermark_to = %s,
                    extracted_count = %s, loaded_count = %s, processed_count = %s,
                    duration_seconds = %s, extract_seconds = %s, load_seconds = %s,
                    transform_seconds = %s, gold_seconds = %s,
                    model_seconds = %s, scored_count = %s
                WHERE run_id = %s
                """,
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
        logger.info("ETL completed: %s", json.dumps(result, ensure_ascii=False))
        return result
    except Exception as error:
        duration = time.perf_counter() - started
        logger.exception("ETL failed")
        with connect() as connection:
            for result in quality_results:
                connection.execute(
                    """
                    INSERT INTO meta.data_quality_checks
                        (run_id, check_name, passed, actual_value, expected_value)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (run_id, result["check"], result["passed"], result["actual"], "0"),
                )
            connection.execute(
                """
                UPDATE meta.etl_runs
                SET status = 'failed', finished_at = now(),
                    extracted_count = %s, loaded_count = %s, processed_count = %s,
                    duration_seconds = %s, error_message = %s
                WHERE run_id = %s
                """,
                (extracted_count, loaded_count, processed_count, duration, str(error), run_id),
            )
            connection.commit()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Support data platform ETL")
    parser.add_argument("mode", choices=["full", "incremental"])
    args = parser.parse_args()
    result = execute(args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
