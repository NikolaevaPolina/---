"""Assemble the thesis from its reviewed source sections."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PARTS = (
    "introduction.md",
    "chapter1_1.md",
    "chapter1_2.md",
    "chapter1_3.md",
    "chapter1_4.md",
    "chapter2_1.md",
    "chapter2_2.md",
    "chapter2_3.md",
    "chapter2_4.md",
    "chapter2_5.md",
    "chapter2_6_model.md",
    "chapter2_7_results.md",
    "conclusion.md",
    "glossary.md",
    "references.md",
    "appendices.md",
)
TITLE = (
    "Проектирование распределённой платформы сбора, хранения и обработки "
    "данных об обращениях пользователей корпоративных ИТ-сервисов"
)
CHAPTER_1 = (
    "Глава 1. Анализ предметной области и архитектурных подходов "
    "к обработке данных обращений технической поддержки"
)
CHAPTER_2 = (
    "Глава 2. Проектирование, реализация и тестирование макета "
    "программного обеспечения платформы данных"
)


def build() -> Path:
    sections = [f"# {TITLE}"]
    for name in PARTS:
        if name == "chapter1_1.md":
            sections.append(f"# {CHAPTER_1}")
        elif name == "chapter2_1.md":
            sections.append(f"# {CHAPTER_2}")
        sections.append((DOCS / name).read_text(encoding="utf-8").strip())
    target = DOCS / "thesis_text.md"
    target.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(build())
