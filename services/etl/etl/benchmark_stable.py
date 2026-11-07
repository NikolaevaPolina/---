from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import requests

from .cli import execute
from .config import settings


def source_count() -> int:
    response = requests.get(f"{settings.source_api_url}/stats", timeout=30)
    response.raise_for_status()
    return int(response.json()["count"])


def advance(new_count: int, update_count: int) -> dict:
    response = requests.post(
        f"{settings.source_api_url}/admin/advance",
        params={"new_count": new_count, "update_count": update_count},
        timeout=max(120, settings.request_timeout),
    )
    response.raise_for_status()
    return response.json()


def save_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def save_svg(path: Path, rows: list[dict]) -> None:
    width = 920
    left = 265
    right = 100
    scale = (width - left - right) / max(row["full_median_seconds"] for row in rows)
    height = 110 + 112 * len(rows)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="37" font-family="Arial" font-size="22" font-weight="bold">Время обработки обращений</text>',
        '<text x="30" y="61" font-family="Arial" font-size="13" fill="#555">Медиана трёх запусков; пакет: 100 новых и до 20 обновлённых</text>',
    ]
    for index, row in enumerate(rows):
        y = 92 + index * 112
        label = f'{row["baseline_tickets"]:,}'.replace(",", " ")
        elements.append(f'<text x="30" y="{y + 27}" font-family="Arial" font-size="16">{label} заявок</text>')
        for offset, key, color in [(0, "incremental_median_seconds", "#1674b8"), (36, "full_median_seconds", "#e28e36")]:
            value = float(row[key])
            bar_width = max(1, round(value * scale))
            elements.append(f'<rect x="{left}" y="{y + offset}" width="{bar_width}" height="28" rx="3" fill="{color}"/>')
            elements.append(f'<text x="{left + bar_width + 8}" y="{y + offset + 20}" font-family="Arial" font-size="13">{value:.3f} с</text>')
    elements.extend([
        f'<rect x="{left}" y="{height - 32}" width="14" height="14" fill="#1674b8"/>',
        f'<text x="{left + 21}" y="{height - 20}" font-family="Arial" font-size="13">Инкрементально</text>',
        f'<rect x="{left + 180}" y="{height - 32}" width="14" height="14" fill="#e28e36"/>',
        f'<text x="{left + 201}" y="{height - 20}" font-family="Arial" font-size="13">Полностью</text>',
        '</svg>',
    ])
    path.write_text("\n".join(elements), encoding="utf-8")


def run(targets: list[int], repeats: int, batch_size: int, output_dir: Path) -> tuple[list[dict], list[dict]]:
    details: list[dict] = []
    summary: list[dict] = []
    for target in targets:
        current = source_count()
        if current < target:
            advance(target - current, 0)
            execute("full")
        baseline = source_count()
        group = []
        for repetition in range(1, repeats + 1):
            change = advance(batch_size, max(1, batch_size // 5))
            incremental = execute("incremental")
            full = execute("full")
            row = {
                "measured_at": datetime.now(timezone.utc).isoformat(),
                "target_tickets": target,
                "baseline_tickets": baseline,
                "repetition": repetition,
                "new_tickets": change["new_tickets"],
                "updated_tickets": change["updated_tickets"],
                "full_extracted_count": full["extracted_count"],
                "incremental_extracted_count": incremental["extracted_count"],
                "incremental_seconds": incremental["duration_seconds"],
                "full_seconds": full["duration_seconds"],
                "incremental_gold_seconds": incremental["stage_seconds"]["gold"],
                "full_gold_seconds": full["stage_seconds"]["gold"],
            }
            details.append(row)
            group.append(row)
        inc = median(row["incremental_seconds"] for row in group)
        complete = median(row["full_seconds"] for row in group)
        summary.append({
            "target_tickets": target,
            "baseline_tickets": baseline,
            "repeats": repeats,
            "batch_size": batch_size,
            "incremental_median_seconds": round(inc, 3),
            "full_median_seconds": round(complete, 3),
            "speedup": round(complete / inc, 2),
            "incremental_gold_median_seconds": round(median(row["incremental_gold_seconds"] for row in group), 3),
            "full_gold_median_seconds": round(median(row["full_gold_seconds"] for row in group), 3),
        })

    save_csv(output_dir / "benchmark_stable_details.csv", details)
    save_csv(output_dir / "benchmark_stable_summary.csv", summary)
    save_svg(output_dir / "benchmark_stable.svg", summary)
    return details, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeated comparison with fixed change batch")
    parser.add_argument("--targets", nargs="+", type=int, default=[7200, 12000, 22000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, default=Path("/artifacts"))
    args = parser.parse_args()
    if args.repeats < 1 or args.batch_size < 1 or any(target < 1 for target in args.targets):
        parser.error("Targets, repeats and batch size must be positive")
    _, summary = run(args.targets, args.repeats, args.batch_size, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
