"""Build the editable thesis manuscript from the reviewed Markdown sections.

The manuscript files are the single source of prose. This script only packages
them as an A4 Word document with GOST 7.32-2017 page settings and editable
captions, lists, tables, references and page numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SECTIONS = [
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
]
TITLE = (
    "Проектирование распределённой платформы сбора, хранения и обработки "
    "данных об обращениях пользователей корпоративных ИТ-сервисов"
)
CHAPTER_1 = "1 АНАЛИЗ ПРЕДМЕТНОЙ ОБЛАСТИ И АРХИТЕКТУРНЫХ ПОДХОДОВ К ОБРАБОТКЕ ДАННЫХ ОБРАЩЕНИЙ ТЕХНИЧЕСКОЙ ПОДДЕРЖКИ"
CHAPTER_2 = "2 ПРОЕКТИРОВАНИЕ, РЕАЛИЗАЦИЯ И ТЕСТИРОВАНИЕ МАКЕТА ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ ПЛАТФОРМЫ ДАННЫХ"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_borders(cell) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for side in ("top", "left", "bottom", "right"):
        tag = OxmlElement(f"w:{side}")
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), "4")
        tag.set(qn("w:color"), "D9D9D9")
        borders.append(tag)


def set_cell_margins(cell, top=90, start=100, bottom=90, end=100) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    mar = tc_pr.first_child_found_in("w:tcMar")
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tc_pr.append(mar)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        elm = OxmlElement(f"w:{side}")
        elm.set(qn("w:w"), str(value))
        elm.set(qn("w:type"), "dxa")
        mar.append(elm)


def keep_with_next(paragraph, value=True) -> None:
    paragraph.paragraph_format.keep_with_next = value


def no_widows(paragraph) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    wc = OxmlElement("w:widowControl")
    wc.set(qn("w:val"), "1")
    ppr.append(wc)


def add_inline(paragraph, value: str) -> None:
    # Italic and bold text remains editable; backticks mark identifiers only.
    token_re = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")
    for fragment in token_re.split(value):
        if not fragment:
            continue
        if fragment.startswith("**") and fragment.endswith("**"):
            run = paragraph.add_run(fragment[2:-2])
            run.bold = True
        elif fragment.startswith("`") and fragment.endswith("`"):
            paragraph.add_run(fragment[1:-1])
        elif fragment.startswith("*") and fragment.endswith("*"):
            run = paragraph.add_run(fragment[1:-1])
            run.italic = True
        else:
            paragraph.add_run(fragment)


def add_body(doc: Document, text: str, *, list_item=False, bibliography=False):
    p = doc.add_paragraph(style="Normal")
    if list_item:
        p.paragraph_format.left_indent = Cm(1.25)
        p.paragraph_format.first_line_indent = Cm(-0.65)
    if bibliography:
        p.paragraph_format.left_indent = Cm(1.25)
        p.paragraph_format.first_line_indent = Cm(-1.25)
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    add_inline(p, text)
    no_widows(p)
    return p


def add_heading(doc: Document, text: str, *, chapter=False, front=False):
    if chapter or front:
        p = doc.add_paragraph(style="Chapter")
        p.paragraph_format.page_break_before = True
    else:
        p = doc.add_paragraph(style="Subsection")
        if text.startswith("2."):
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(6)
    p.add_run(text)
    keep_with_next(p)
    return p


def image_for(source: Path) -> Path:
    if source.suffix.lower() != ".svg":
        return source
    sibling = source.with_suffix(".png")
    if sibling.exists() and sibling.stat().st_mtime >= source.stat().st_mtime:
        return sibling
    node = Path(os.environ.get("CODEX_NODE", r"C:\Users\tvnik\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"))
    node_modules = Path(os.environ.get("CODEX_NODE_MODULES", r"C:\Users\tvnik\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"))
    js = "const sharp=require(process.env.NODE_PATH+'/sharp'); sharp(process.argv[1],{density:200}).png().toFile(process.argv[2]).catch(e=>{console.error(e);process.exit(1)});"
    env = dict(os.environ)
    env["NODE_PATH"] = str(node_modules)
    subprocess.run([str(node), "-e", js, str(source), str(sibling)], env=env, check=True)
    return sibling


def add_figure(doc: Document, line: str, base: Path) -> None:
    match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
    if not match:
        raise ValueError(f"Unrecognized figure: {line}")
    image = image_for((base / match.group(2)).resolve())
    p = doc.add_paragraph(style="Figure")
    if "benchmark_stable" in image.name:
        # The plot stays readable at this width and avoids an orphaned end page.
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(3)
        width = Cm(13.5)
    else:
        width = Cm(15.7)
    p.add_run().add_picture(str(image), width=width)
    keep_with_next(p)


def add_caption(doc: Document, text: str, *, figure: bool) -> None:
    p = doc.add_paragraph(style="Figure Caption" if figure else "Table Caption")
    p.add_run(text.strip("*"))
    if figure and text.startswith("*Рисунок 4"):
        p.paragraph_format.space_after = Pt(6)
    keep_with_next(p, not figure)


def add_table(doc: Document, lines: list[str]) -> None:
    rows = []
    for line in lines:
        values = [x.strip() for x in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", x) for x in values):
            continue
        rows.append(values)
    if not rows:
        return
    ncol = len(rows[0])
    if any(len(r) != ncol for r in rows):
        raise ValueError(f"Inconsistent table: {lines[:2]}")
    compact = "Ошибка обучения" in rows[0] or "Базовый объём заявок" in rows[0]
    table = doc.add_table(rows=len(rows), cols=ncol)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.style = "Table Grid"
    available = 16.5
    if ncol == 2:
        widths = [available * .33, available * .67]
    elif ncol == 3:
        widths = [available * .27, available * .35, available * .38]
    elif ncol == 4:
        widths = [available * .23, available * .26, available * .24, available * .27]
    elif ncol == 6:
        widths = [available * .19] + [available * .162] * 5
    elif ncol == 7:
        widths = [available * .19, available * .12, available * .12, available * .12,
                  available * .14, available * .155, available * .155]
    else:
        widths = [available / ncol] * ncol
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            cell = table.cell(i, j)
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_borders(cell)
            if compact:
                set_cell_margins(cell, top=55, bottom=55)
            else:
                set_cell_margins(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.left_indent = Cm(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if j > 0 and ncol >= 6 else WD_ALIGN_PARAGRAPH.LEFT
            add_inline(p, value)
            for run in p.runs:
                run.font.size = Pt(10.5)
            if i == 0:
                set_cell_shading(cell, "D9E7F2")
                for run in p.runs:
                    run.bold = True
            elif i % 2 == 0:
                set_cell_shading(cell, "F7F9FB")
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    for cell in table.rows[0].cells:
        cell._tc.get_or_add_tcPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(header)


def add_page_number(doc: Document) -> None:
    section = doc.sections[0]
    section.different_first_page_header_footer = True
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "2"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for elm in (begin, instr, separate, text, end):
        run._r.append(elm)
    run.font.name = "Times New Roman"
    run.font.size = Pt(14)


def configure_styles(doc: Document) -> None:
    sec = doc.sections[0]
    sec.page_width = Cm(21)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(3)
    sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(2)
    sec.bottom_margin = Cm(2)
    sec.header_distance = Cm(1)
    sec.footer_distance = Cm(1)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(14)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.first_line_indent = Cm(1.25)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(0)

    for name in ("Title Page", "Chapter", "Subsection", "Figure", "Figure Caption", "Table Caption", "Contents"):
        if name not in doc.styles:
            doc.styles.add_style(name, 1)
        s = doc.styles[name]
        s.base_style = normal
        s.font.name = "Times New Roman"
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.font.size = Pt(14)
        s.paragraph_format.first_line_indent = Cm(0)
        s.paragraph_format.space_after = Pt(0)
    title = doc.styles["Title Page"]
    title.font.bold = True
    title.font.size = Pt(16)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.line_spacing = 1.5
    chapter = doc.styles["Chapter"]
    chapter.font.bold = True
    chapter.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    chapter.paragraph_format.space_before = Pt(0)
    chapter.paragraph_format.space_after = Pt(14)
    chapter.paragraph_format.keep_with_next = True
    subsection = doc.styles["Subsection"]
    subsection.font.bold = True
    subsection.paragraph_format.first_line_indent = Cm(1.25)
    subsection.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    subsection.paragraph_format.space_before = Pt(14)
    subsection.paragraph_format.space_after = Pt(8)
    subsection.paragraph_format.keep_with_next = True
    figure = doc.styles["Figure"]
    figure.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    figure.paragraph_format.space_before = Pt(8)
    figure.paragraph_format.space_after = Pt(6)
    figcap = doc.styles["Figure Caption"]
    figcap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    figcap.paragraph_format.space_after = Pt(10)
    tcap = doc.styles["Table Caption"]
    tcap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    tcap.paragraph_format.space_before = Pt(8)
    tcap.paragraph_format.space_after = Pt(5)
    contents = doc.styles["Contents"]
    contents.paragraph_format.line_spacing = 1.5
    contents.paragraph_format.tab_stops.add_tab_stop(
        Cm(16.5), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
    )


def add_front_matter(doc: Document, page_map: dict[str, int]) -> None:
    p = doc.add_paragraph(style="Title Page")
    p.paragraph_format.space_before = Pt(165)
    p.add_run("ВЫПУСКНАЯ КВАЛИФИКАЦИОННАЯ РАБОТА")
    p = doc.add_paragraph(style="Title Page")
    p.paragraph_format.space_before = Pt(35)
    p.add_run(TITLE)
    p = doc.add_paragraph(style="Title Page")
    p.paragraph_format.space_before = Pt(165)
    p.add_run("Николаева Полина")
    p = doc.add_paragraph(style="Title Page")
    p.paragraph_format.space_before = Pt(45)
    p.add_run("Москва 2026")
    doc.add_page_break()
    h = doc.add_paragraph(style="Chapter")
    h.add_run("СОДЕРЖАНИЕ")
    toc = [
        ("ВВЕДЕНИЕ", "Введение"),
        (CHAPTER_1, "Глава 1"),
        ("1.1 Характеристика обращений пользователей корпоративных ИС", "1.1"),
        ("1.2 Состав данных об обращениях и требования к их качеству", "1.2"),
        ("1.3 Подходы к хранению и обработке данных обращений", "1.3"),
        ("1.4 Постановка задачи и критерии оценки макета", "1.4"),
        (CHAPTER_2, "Глава 2"),
        ("2.1 Требования к макету платформы данных", "2.1"),
        ("2.2 Архитектура и взаимодействие компонентов", "2.2"),
        ("2.3 Модель данных и правила расчёта показателей", "2.3"),
        ("2.4 Алгоритм загрузки и обновления витрин", "2.4"),
        ("2.5 Программная реализация и контроль качества", "2.5"),
        ("2.6 Классификация обращений в составе конвейера", "2.6"),
        ("2.7 Испытание конвейера и интерпретация результатов", "2.7"),
        ("ЗАКЛЮЧЕНИЕ", "Заключение"),
        ("ГЛОССАРИЙ И СПИСОК СОКРАЩЕНИЙ", "Глоссарий"),
        ("СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ", "Список источников"),
        ("ПРИЛОЖЕНИЕ А", "Приложение А"),
        ("ПРИЛОЖЕНИЕ Б", "Приложение Б"),
    ]
    for title, key in toc:
        p = doc.add_paragraph(style="Contents")
        p.add_run(title)
        p.add_run("\t" + str(page_map.get(key, "")))


def add_section(doc: Document, path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"No heading in {path}")
    heading = lines[0][2:].strip()
    if path.name == "chapter1_1.md":
        add_heading(doc, CHAPTER_1, chapter=True)
    elif path.name == "chapter2_1.md":
        add_heading(doc, CHAPTER_2, chapter=True)
    if path.name in {"introduction.md", "conclusion.md", "glossary.md", "references.md"}:
        add_heading(doc, heading.upper(), front=True)
    elif path.name == "appendices.md":
        add_heading(doc, heading.upper(), front=True)
    else:
        add_heading(doc, heading)

    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            add_heading(doc, line[2:].upper(), front=True)
            i += 1
            continue
        if line.startswith("!["):
            add_figure(doc, line, path.parent)
            i += 1
            continue
        if re.fullmatch(r"\*Рисунок\s+.+\*", line):
            add_caption(doc, line, figure=True)
            i += 1
            continue
        if re.fullmatch(r"\*Таблица\s+.+\*", line):
            add_caption(doc, line, figure=False)
            i += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            add_table(doc, table_lines)
            continue
        if re.match(r"^\d+\.\s", line):
            add_body(doc, line, list_item=True, bibliography=path.name == "references.md")
        elif line.startswith("- "):
            add_body(doc, "• " + line[2:], list_item=True)
        else:
            add_body(doc, line)
        i += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables" / "thesis.docx")
    parser.add_argument("--page-map", type=Path)
    args = parser.parse_args()
    page_map = json.loads(args.page_map.read_text(encoding="utf-8")) if args.page_map else {}
    doc = Document()
    configure_styles(doc)
    add_page_number(doc)
    add_front_matter(doc, page_map)
    for item in SECTIONS:
        add_section(doc, DOCS / item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
