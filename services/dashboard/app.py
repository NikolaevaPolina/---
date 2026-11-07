from __future__ import annotations

import logging
import os
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from queries import DashboardSQL


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("support-dashboard")

st.set_page_config(
    page_title="Аналитика технической поддержки",
    page_icon="📊",
    layout="wide",
)

password = os.getenv("POSTGRES_PASSWORD")
if not password:
    logger.error("dashboard_configuration_failed missing_password=true")
    st.error("Не задан пароль учебной базы. Проверьте локальный файл .env.")
    st.stop()

db_url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("POSTGRES_USER", "support"),
    password=password,
    host=os.getenv("POSTGRES_HOST", "db"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    database=os.getenv("POSTGRES_DB", "support_dw"),
)
engine = create_engine(db_url, pool_pre_ping=True)
logger.info("dashboard_ready")


@st.cache_data(ttl=30)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            rows = pd.read_sql(text(sql), connection, params=params or {})
    except SQLAlchemyError as error:
        logger.error("dashboard_query_failed error_type=%s", type(error).__name__)
        st.error("Не удалось прочитать данные хранилища. Проверьте состояние базы.")
        st.stop()
    logger.info(
        "dashboard_query rows=%d duration_ms=%.1f",
        len(rows),
        (time.perf_counter() - started) * 1000,
    )
    return rows


st.title("Платформа данных службы технической поддержки")
st.caption("Демонстрационный аналитический слой Gold · обезличенные синтетические данные")

date_bounds = query(DashboardSQL.DATE_BOUNDS)

if date_bounds.empty or pd.isna(date_bounds.loc[0, "min_date"]):
    st.info("Данных пока нет. Выполните полную ETL-загрузку.")
    st.stop()

min_date = pd.to_datetime(date_bounds.loc[0, "min_date"]).date()
max_date = pd.to_datetime(date_bounds.loc[0, "max_date"]).date()

services = query(DashboardSQL.SERVICES)
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

overview = query(DashboardSQL.OVERVIEW, base_params).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Обращений", int(overview["requests"] or 0))
c2.metric("Решено", int(overview["resolved"] or 0))
c3.metric("Нарушение SLA", f"{float(overview['breached_pct'] or 0):.1f}%")
c4.metric("Среднее время решения", f"{float(overview['avg_resolution'] or 0):.0f} мин")

tab_flow, tab_sla, tab_workload, tab_model, tab_quality = st.tabs(
    ["Поток обращений", "SLA", "Загрузка", "Классификация", "Качество и запуски"]
)

with tab_flow:
    daily = query(DashboardSQL.DAILY, base_params)
    st.plotly_chart(
        px.line(daily, x="report_date", y="request_count", color="service", markers=True,
                labels={"report_date": "Дата", "request_count": "Обращения", "service": "Сервис"}),
        use_container_width=True,
    )
    left, right = st.columns(2)
    by_category = query(DashboardSQL.BY_CATEGORY, base_params)
    by_priority = query(DashboardSQL.BY_PRIORITY, base_params)
    left.plotly_chart(px.bar(by_category, x="category", y="request_count",
                             labels={"category": "Категория", "request_count": "Обращения"}),
                      use_container_width=True)
    right.plotly_chart(px.pie(by_priority, names="priority", values="request_count", hole=0.45),
                       use_container_width=True)

with tab_sla:
    sla_daily = query(DashboardSQL.SLA_DAILY, base_params)
    left, right = st.columns(2)
    left.plotly_chart(px.line(sla_daily, x="report_date", y="breached_pct", markers=True,
                              labels={"report_date": "Дата", "breached_pct": "Нарушение SLA, %"}),
                      use_container_width=True)
    right.plotly_chart(px.line(sla_daily, x="report_date", y="avg_resolution_minutes", markers=True,
                               labels={"report_date": "Дата", "avg_resolution_minutes": "Время решения, мин"}),
                       use_container_width=True)

with tab_workload:
    workload = query(DashboardSQL.WORKLOAD, base_params)
    st.plotly_chart(
        px.bar(workload, x="assignee", y=["assigned_count", "resolved_count"], barmode="group",
               labels={"assignee": "Исполнитель", "value": "Количество", "variable": "Показатель"}),
        use_container_width=True,
    )
    st.dataframe(workload, use_container_width=True, hide_index=True)

with tab_model:
    model_versions = query(DashboardSQL.MODEL_VERSIONS)
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
        predictions = query(DashboardSQL.PREDICTIONS, base_params)
        st.subheader("Рекомендации для открытых обращений")
        st.caption("Оценка модели служит для сравнения рекомендаций; она не является проверенной вероятностью правильного ответа.")
        st.dataframe(predictions, use_container_width=True, hide_index=True)

with tab_quality:
    runs = query(DashboardSQL.RUNS)
    checks = query(DashboardSQL.CHECKS)
    st.subheader("Последние запуски конвейера")
    st.dataframe(runs, use_container_width=True, hide_index=True)
    st.subheader("Проверки качества")
    st.dataframe(checks, use_container_width=True, hide_index=True)
