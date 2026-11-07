"""Extract section page numbers from a rendered thesis PDF for the editable contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pdfplumber


PREFIXES = {
    "Введение": "ВВЕДЕНИЕ",
    "Глава 1": "1 АНАЛИЗ ПРЕДМЕТНОЙ ОБЛАСТИ",
    "1.1": "1.1 Характеристика обращений",
    "1.2": "1.2 Состав данных",
    "1.3": "1.3 Подходы к хранению",
    "1.4": "1.4 Постановка задачи",
    "Глава 2": "2 ПРОЕКТИРОВАНИЕ, РЕАЛИЗАЦИЯ",
    "2.1": "2.1 Требования к макету",
    "2.2": "2.2 Архитектура и взаимодействие",
    "2.3": "2.3 Модель данных",
    "2.4": "2.4 Алгоритм загрузки",
    "2.5": "2.5 Программная реализация",
    "2.6": "2.6 Классификация обращений",
    "2.7": "2.7 Испытание конвейера",
    "Заключение": "ЗАКЛЮЧЕНИЕ",
    "Глоссарий": "ГЛОССАРИЙ И СПИСОК СОКРАЩЕНИЙ",
    "Список источников": "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ",
    "Приложение А": "ПРИЛОЖЕНИЕ А",
    "Приложение Б": "ПРИЛОЖЕНИЕ Б",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    found: dict[str, int] = {}
    with pdfplumber.open(args.pdf) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            if number <= 2:
                continue
            lines = [line.strip() for line in (page.extract_text() or "").splitlines()]
            for key, prefix in PREFIXES.items():
                if key not in found and any(line.startswith(prefix) for line in lines):
                    found[key] = number
    missing = [key for key in PREFIXES if key not in found]
    if missing:
        raise ValueError(f"Headings not found: {missing}")
    args.output.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    print(f"Chapter 1: {found['Глава 2'] - found['Глава 1']} pages")
    print(f"Chapter 2: {found['Заключение'] - found['Глава 2']} pages")
    print(f"Total: {number} pages")


if __name__ == "__main__":
    main()
