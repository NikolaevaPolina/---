from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from .cli import execute
from .config import settings


def run_benchmark(sizes: list[int], output: Path) -> list[dict]:
    results: list[dict] = []
    for size in sizes:
        response = requests.post(
            f"{settings.source_api_url}/admin/advance",
            params={"new_count": size, "update_count": max(1, size // 10)},
            timeout=max(settings.request_timeout, 120),
        )
        response.raise_for_status()
        source_change = response.json()

        incremental = execute("incremental")
        full = execute("full")
        results.append(
            {
                "measured_at": datetime.now(timezone.utc).isoformat(),
                "added_count": source_change["new_tickets"],
                "updated_count": source_change["updated_tickets"],
                "total_changed": source_change["new_tickets"] + source_change["updated_tickets"],
                "incremental_seconds": incremental["duration_seconds"],
                "full_seconds": full["duration_seconds"],
                "speedup": round(
                    full["duration_seconds"] / max(incremental["duration_seconds"], 0.001), 3
                ),
                "full_extracted_count": full["extracted_count"],
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare full and incremental mart builds")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 5000])
    parser.add_argument("--output", type=Path, default=Path("/artifacts/benchmark.csv"))
    args = parser.parse_args()
    results = run_benchmark(args.sizes, args.output)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"CSV saved to {args.output}")


if __name__ == "__main__":
    main()
