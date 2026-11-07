from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://support:support@db:5432/support_dw"
).replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

st.set_page_config(
    page_title="Аналитика технической поддержки",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=30)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})


st.title("Платформа данных службы технической поддержки")
st.caption("Демонстрационный аналитический слой Gold · обезличенные синтетические данные")

try:
    date_bounds = query(
        "SELECT min(report_date) AS min_date, max(report_date) AS max_date FROM gold.mart_requests_daily"
    )
except Exception as error:
    st.warning("Хранилище ещё не заполнено. Сначала выполните полную ETL-загрузку.")
    st.code("docker compose run --rm etl python -m etl.cli full")
    st.exception(error)
    st.stop()

if date_bounds.empty or pd.isna(date_bounds.loc[0, "min_date"]):
    st.info("Данных пока нет. Выполните полную ETL-загрузку.")
    st.stop()

min_date = pd.to_datetime(date_bounds.loc[0, "min_date"]).date()
max_date = pd.to_datetime(date_bounds.loc[0, "max_date"]).date()

services = query("SELECT DISTINCT service FROM gold.mart_requests_daily ORDER BY service")
with st.sidebar:
    st.header("Фильтры")
    date_range = st.date_input(
        "Период",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    selected_services = st.multiselect(
        "Сервисы",
        services["service"].tolist(),
        default=services["service"].tolist(),
    )
    if st.button("Обновить данные"):
        st.cache_data.clear()
        st.rerun()

if len(date_range) != 2:
    st.stop()
date_from, date_to = date_range
if not selected_services:
    st.warning("Выберите хотя бы один сервис.")
    st.stop()

base_params = {"date_from": date_from, "date_to": date_to, "services": selected_services}

overview = query(
    """
    SELECT
        sum(request_count)::integer AS requests,
        sum(resolved_count)::integer AS resolved,
        sum(breached_count)::integer AS breached,
        round(sum(breached_count)::numeric / NULLIF(sum(request_count), 0) * 100, 1) AS breached_pct,
        round(sum(avg_resolution_minutes * resolved_count) / NULLIF(sum(resolved_count), 0), 1) AS avg_resolution
    FROM gold.mart_sla_daily
    WHERE report_date BETWEEN :date_from AND :date_to
      AND service = ANY(:services)
    """,
    base_params,
).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Обращений", int(overview["requests"] or 0))
c2.metric("Решено", int(overview["resolved"] or 0))
c3.metric("Нарушение SLA", f"{float(overview['breached_pct'] or 0):.1f}%")
c4.metric("Среднее время решения", f"{float(overview['avg_resolution'] or 0):.0f} мин")

tab_flow, tab_sla, tab_workload, tab_model, tab_quality = st.tabs(
    ["Поток обращений", "SLA", "Загрузка", "Классификация", "Качество и запуски"]
)

with tab_flow:
    daily = query(
        """
        SELECT report_date, service, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY report_date, service ORDER BY report_date, service
        """,
        base_params,
    )
    st.plotly_chart(
        px.line(daily, x="report_date", y="request_count", color="service", markers=True,
                labels={"report_date": "Дата", "request_count": "Обращения", "service": "Сервис"}),
        use_container_width=True,
    )
    left, right = st.columns(2)
    by_category = query(
        """
        SELECT category, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY category ORDER BY request_count DESC
        """,
        base_params,
    )
    by_priority = query(
        """
        SELECT priority, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY priority ORDER BY request_count DESC
        """,
        base_params,
    )
    left.plotly_chart(px.bar(by_category, x="category", y="request_count",
                             labels={"category": "Категория", "request_count": "Обращения"}),
                      use_container_width=True)
    right.plotly_chart(px.pie(by_priority, names="priority", values="request_count", hole=0.45),
                       use_container_width=True)

with tab_sla:
    sla_daily = query(
        """
        SELECT report_date,
               round(sum(breached_count)::numeric / NULLIF(sum(request_count), 0) * 100, 1) AS breached_pct,
               round(sum(avg_resolution_minutes * resolved_count) /
                     NULLIF(sum(resolved_count), 0), 1) AS avg_resolution_minutes
        FROM gold.mart_sla_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY report_date ORDER BY report_date
        """,
        base_params,
    )
    left, right = st.columns(2)
    left.plotly_chart(px.line(sla_daily, x="report_date", y="breached_pct", markers=True,
                              labels={"report_date": "Дата", "breached_pct": "Нарушение SLA, %"}),
                      use_container_width=True)
    right.plotly_chart(px.line(sla_daily, x="report_date", y="avg_resolution_minutes", markers=True,
                               labels={"report_date": "Дата", "avg_resolution_minutes": "Время решения, мин"}),
                       use_container_width=True)

with tab_workload:
    workload = query(
        """
        SELECT assignee_group, assignee,
               sum(assigned_count)::integer AS assigned_count,
               sum(resolved_count)::integer AS resolved_count,
               round(sum(avg_resolution_minutes * resolved_count) /
                     NULLIF(sum(resolved_count), 0), 1) AS avg_resolution_minutes,
               sum(reopened_count)::integer AS reopened_count
        FROM gold.mart_workload_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY assignee_group, assignee ORDER BY assigned_count DESC
        """,
        base_params,
    )
    st.plotly_chart(
        px.bar(workload, x="assignee", y=["assigned_count", "resolved_count"], barmode="group",
               labels={"assignee": "Исполнитель", "value": "Количество", "variable": "Показатель"}),
        use_container_width=True,
    )
    st.dataframe(workload, use_container_width=True, hide_index=True)

with tab_model:
    model_versions = query(
        """SELECT model_id::text, model_name, trained_at, training_count,
                  record_test_count, record_accuracy, record_macro_f1,
                  template_test_count, template_accuracy, template_macro_f1,
                  majority_baseline, candidate_metrics
           FROM meta.model_versions ORDER BY trained_at DESC LIMIT 1"""
    )
    if model_versions.empty:
        st.info("Модель будет обучена при полном запуске конвейера.")
    else:
        latest = model_versions.iloc[0]
        st.caption(
            "Рекомендация категории по теме обращения. Обучение и оценка выполнены "
            "на синтетических шаблонных заявках; на реальных обращениях качество не проверено."
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Точность на 20% заявок", f"{float(latest['record_accuracy']):.1%}")
        m2.metric("Точность на новых шаблонах", f"{float(latest['template_accuracy']):.1%}")
        m3.metric("Базовый метод большинства", f"{float(latest['majority_baseline']):.1%}")
        comparisons = []
        for method, values in latest["candidate_metrics"].items():
            comparisons.append({
                "Метод": method,
                "Ошибка обучения": values["train"]["error"],
                "Ошибка теста": values["record_test"]["error"],
                "Точность теста": values["record_test"]["accuracy"],
                "Макро-F1 теста": values["record_test"]["macro_f1"],
                "Точность новых шаблонов": values["template_test"]["accuracy"],
                "Макро-F1 новых шаблонов": values["template_test"]["macro_f1"],
            })
        st.subheader("Сравнение двух методов на одинаковой выборке")
        st.dataframe(pd.DataFrame(comparisons), use_container_width=True, hide_index=True)
        predictions = query(
            """SELECT p.ticket_id, p.title, p.source_category,
                      p.predicted_category, p.confidence, s.service
               FROM gold.ticket_category_predictions p
               JOIN silver.tickets s ON s.ticket_id = p.ticket_id
               WHERE s.created_at::date BETWEEN :date_from AND :date_to
                 AND s.service = ANY(:services)
               ORDER BY p.predicted_at DESC LIMIT 200""",
            base_params,
        )
        st.subheader("Рекомендации для открытых обращений")
        st.caption("Оценка модели служит для сравнения рекомендаций; она не является проверенной вероятностью правильного ответа.")
        st.dataframe(predictions, use_container_width=True, hide_index=True)

with tab_quality:
    runs = query(
        """
        SELECT run_id::text, mode, status, started_at, finished_at,
               extracted_count, processed_count, duration_seconds,
               extract_seconds, load_seconds, transform_seconds, gold_seconds,
               model_seconds, scored_count
        FROM meta.etl_runs ORDER BY started_at DESC LIMIT 20
        """
    )
    checks = query(
        """
        SELECT c.checked_at, c.check_name, c.passed, c.actual_value, c.expected_value
        FROM meta.data_quality_checks c
        ORDER BY c.checked_at DESC LIMIT 50
        """
    )
    st.subheader("Последние запуски конвейера")
    st.dataframe(runs, use_container_width=True, hide_index=True)
    st.subheader("Проверки качества")
    st.dataframe(checks, use_container_width=True, hide_index=True)
