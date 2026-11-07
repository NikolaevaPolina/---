"""Экран проверки рекомендаций специалистом на синтетических заявках."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path

import streamlit as st

from neural import NeuralRanker
from repository import DatabaseSettings, OperatorRepository
from support import build_draft, rank_candidates


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("support-operator")

st.set_page_config(page_title="Рабочее место специалиста СТП", page_icon="🛠️", layout="wide")


@st.cache_resource
def repository() -> OperatorRepository:
    instance = OperatorRepository(DatabaseSettings.from_environment())
    instance.prepare()
    logger.info("operator_repository_ready")
    return instance


@st.cache_resource
def load_neural_model(path: str, modified_at: float | None) -> NeuralRanker | None:
    """Загрузить модель повторно, если файл изменился после обучения."""
    if modified_at is None:
        return None
    return NeuralRanker.load(Path(path))


st.title("Рабочее место специалиста технической поддержки")
st.caption(
    "Учебный макет на синтетических обращениях. Черновик требует проверки специалистом "
    "и не отправляется заявителю автоматически."
)

try:
    repo = repository()
    tickets = repo.open_tickets()
except Exception as error:
    logger.error("operator_start_failed kind=%s", type(error).__name__)
    st.error("Не удалось получить обращения. Проверьте готовность платформы данных.")
    st.stop()

if not tickets:
    st.info("Открытых обращений пока нет. Выполните полную загрузку данных.")
    st.stop()

ticket_by_id = {int(row["ticket_id"]): row for row in tickets}
selected_id = st.selectbox(
    "Открытая заявка",
    list(ticket_by_id),
    format_func=lambda ticket_id: (
        f"№ {ticket_id} — {ticket_by_id[ticket_id]['title']} "
        f"({ticket_by_id[ticket_id]['status']})"
    ),
)
ticket = ticket_by_id[selected_id]
logger.info("operator_ticket_view ticket_id=%s", selected_id)

model_path = Path(os.getenv("NEURAL_MODEL_PATH", "/models/neural_ranker.npz"))
try:
    modified_at = model_path.stat().st_mtime if model_path.exists() else None
    neural_model = load_neural_model(str(model_path), modified_at)
except Exception as error:
    logger.error("operator_model_load_failed kind=%s", type(error).__name__)
    neural_model = None

left, right = st.columns([2, 1])
with left:
    st.subheader("Обращение")
    st.write(f"**Тема:** {ticket['title']}")
    st.write(f"**Описание:** {ticket['description']}")
with right:
    st.subheader("Признаки")
    st.write(f"**Сервис:** {ticket['service']}")
    st.write(f"**Приоритет:** {ticket['priority']}")
    st.write(f"**Состояние:** {ticket['status']}")
    recommendation = ticket.get("predicted_category")
    st.write(f"**Рекомендованная категория:** {recommendation or 'нет'}")
    st.caption("Классификация экспериментальная. Категория заявки не меняется автоматически.")
    if neural_model is not None:
        issue_type, _ = neural_model.predict(ticket["title"])
        st.write(f"**Предполагаемый тип проблемы:** {issue_type}")
        st.caption("Оценка сети требует проверки специалистом и не является вероятностью решения.")

category_for_search = recommendation or ticket["category"]
try:
    candidates = repo.closed_candidates(ticket["service"], category_for_search)
    similar = (
        neural_model.rank(ticket, candidates)
        if neural_model is not None
        else rank_candidates(ticket, candidates, category_for_search)
    )
except Exception as error:
    logger.error("operator_retrieval_failed ticket_id=%s kind=%s", selected_id, type(error).__name__)
    st.error("Не удалось получить похожие закрытые обращения.")
    st.stop()

st.subheader("Похожие закрытые обращения")
if neural_model is None:
    st.caption("Пока используется поиск по словам. Для нейросетевого поиска запустите обучение модели.")
else:
    st.caption("Порядок заявок рассчитан обученной сетью. Оценка сходства не является вероятностью правильного решения.")
    metrics_path = model_path.with_suffix(".json")
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            st.caption(
                f"Поиск на {metrics['retrieval_test']['examples']} новых синтетических формулировках "
                f"среди трёх типов одного сервиса: первая подходящая заявка у сети "
                f"{metrics['retrieval_test']['neural_recall_at_1']:.1%}, "
                f"у поиска по словам {metrics['retrieval_test']['lexical_recall_at_1']:.1%}. "
                "На реальных заявках качество не измерено."
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.error("operator_metrics_read_failed kind=%s", type(error).__name__)
reference = None
if similar:
    similar_by_id = {int(row["ticket_id"]): row for row in similar}
    reference_id = st.selectbox(
        "Основание для черновика",
        list(similar_by_id),
        format_func=lambda ticket_id: (
            f"№ {ticket_id} — {similar_by_id[ticket_id]['title']} "
            f"(условное сходство {similar_by_id[ticket_id]['similarity']:.0%})"
        ),
    )
    reference = similar_by_id[reference_id]
    st.write(f"**Итог прежней заявки:** {reference['resolution_text']}")
else:
    st.info("Похожих закрытых заявок не найдено. Черновик будет общим.")

proposed_reply = build_draft(ticket, reference)
st.subheader("Черновик ответа")
with st.form(key=f"review_{selected_id}_{reference['ticket_id'] if reference else 'none'}"):
    edited_reply = st.text_area(
        "Текст для проверки специалистом",
        value=proposed_reply,
        height=175,
    )
    review_note = st.text_input("Примечание специалиста (необязательно)")
    approved = st.form_submit_button("Согласовать черновик", type="primary")
    rejected = st.form_submit_button("Отклонить черновик")

if approved or rejected:
    decision = "approved" if approved else "rejected"
    try:
        review_id = repo.save_review(
            ticket_id=selected_id,
            source_ticket_id=int(reference["ticket_id"]) if reference else None,
            model_id=ticket.get("model_id"),
            proposed_reply=proposed_reply,
            edited_reply=edited_reply,
            decision=decision,
            review_note=review_note,
        )
    except ValueError:
        st.warning("Для согласования введите непустой текст ответа.")
    except Exception as error:
        logger.error("operator_review_failed ticket_id=%s kind=%s", selected_id, type(error).__name__)
        st.error("Не удалось сохранить решение специалиста.")
    else:
        logger.info(
            "operator_review_saved ticket_id=%s review_id=%s decision=%s",
            selected_id,
            review_id,
            decision,
        )
        st.success("Решение записано. Ответ заявителю не отправлен.")

try:
    reviews = repo.reviews(selected_id)
except Exception as error:
    logger.error("operator_history_failed ticket_id=%s kind=%s", selected_id, type(error).__name__)
    reviews = []
if reviews:
    st.subheader("История проверки этой заявки")
    st.dataframe(reviews, use_container_width=True, hide_index=True)
