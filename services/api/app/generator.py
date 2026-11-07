from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone


SERVICES = {
    "Корпоративная почта": ["Не отправляется письмо", "Создание группы рассылки", "Настройка почтового клиента"],
    "Удалённый доступ": ["Не подключается VPN", "Истёк сертификат", "Медленное соединение"],
    "Учётные записи": ["Сброс пароля", "Блокировка учётной записи", "Предоставление доступа"],
    "Рабочее место": ["Не включается компьютер", "Установка программы", "Не работает периферия"],
    "Корпоративные системы": ["Ошибка при входе", "Не формируется отчёт", "Недоступен сервис"],
}

CATEGORIES = {
    "Корпоративная почта": "Почта",
    "Удалённый доступ": "Сетевой доступ",
    "Учётные записи": "Управление доступом",
    "Рабочее место": "Оборудование и ПО",
    "Корпоративные системы": "Бизнес-приложения",
}

GROUPS = {
    "Корпоративная почта": "Линия поддержки Microsoft",
    "Удалённый доступ": "Сетевая поддержка",
    "Учётные записи": "Управление доступом",
    "Рабочее место": "Поддержка рабочих мест",
    "Корпоративные системы": "Поддержка приложений",
}

ASSIGNEES = {
    "Линия поддержки Microsoft": ["Специалист MS-01", "Специалист MS-02", "Специалист MS-03"],
    "Сетевая поддержка": ["Специалист NET-01", "Специалист NET-02"],
    "Управление доступом": ["Специалист IAM-01", "Специалист IAM-02"],
    "Поддержка рабочих мест": ["Специалист SD-01", "Специалист SD-02", "Специалист SD-03"],
    "Поддержка приложений": ["Специалист APP-01", "Специалист APP-02"],
}

DEPARTMENTS = ["Финансы", "Продажи", "Логистика", "Производство", "ИТ", "Кадры"]
PRIORITIES = ["Низкий", "Средний", "Высокий", "Критический"]
SLA_HOURS = {"Низкий": 72, "Средний": 24, "Высокий": 8, "Критический": 4}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def build_ticket(ticket_id: int, base_time: datetime, force_open: bool = False) -> dict:
    """Создать воспроизводимую синтетическую заявку без персональных данных."""
    rng = random.Random(ticket_id * 7919)
    service = rng.choice(list(SERVICES))
    title = rng.choice(SERVICES[service])
    priority = rng.choices(PRIORITIES, weights=[15, 55, 24, 6], k=1)[0]
    resolution_hours = max(1, int(rng.lognormvariate(2.3, 0.8)))
    response_minutes = rng.randint(5, min(180, resolution_hours * 60 - 1))
    created_at = base_time - timedelta(minutes=rng.randint(60, 180 * 24 * 60))
    first_response_at = min(
        created_at + timedelta(minutes=response_minutes), base_time - timedelta(minutes=2)
    )
    resolved_at = min(
        created_at + timedelta(hours=resolution_hours), base_time - timedelta(minutes=1)
    )

    status = rng.choices(
        ["Закрыта", "Решена", "В работе", "Ожидает уточнения", "Новая"],
        weights=[57, 13, 15, 10, 5],
        k=1,
    )[0]
    if force_open:
        status = rng.choice(["В работе", "Ожидает уточнения", "Новая"])
    is_resolved = status in {"Закрыта", "Решена"}
    closed_at = (
        min(resolved_at + timedelta(hours=rng.randint(1, 48)), base_time)
        if status == "Закрыта"
        else None
    )
    group = GROUPS[service]
    last_event = (closed_at or resolved_at) if is_resolved else first_response_at
    updated_at = min(last_event + timedelta(minutes=rng.randint(0, 60)), base_time)

    return {
        "id": ticket_id,
        "title": title,
        "description": (
            f"Синтетическое обращение №{ticket_id}. Пользователь сообщает о проблеме: "
            f"«{title.lower()}». Требуется диагностика сервиса «{service}»."
        ),
        "category": CATEGORIES[service],
        "service": service,
        "priority": priority,
        "status": status,
        "requester_department": rng.choice(DEPARTMENTS),
        "assignee_group": group,
        "assignee": rng.choice(ASSIGNEES[group]),
        "created_at": _iso(created_at),
        "first_response_at": _iso(first_response_at),
        "resolved_at": _iso(resolved_at) if is_resolved else None,
        "closed_at": _iso(closed_at),
        "updated_at": _iso(updated_at),
        "sla_deadline": _iso(created_at + timedelta(hours=SLA_HOURS[priority])),
        "resolution_text": (
            f"Выполнена диагностика. Работа сервиса «{service}» восстановлена, рекомендации направлены пользователю."
            if is_resolved
            else None
        ),
        "reopened_count": rng.choices([0, 1, 2], weights=[90, 9, 1], k=1)[0],
    }


def resolve_ticket(ticket: dict, changed_at: datetime) -> dict:
    created_at = datetime.fromisoformat(ticket["created_at"])
    resolved_at = max(changed_at - timedelta(minutes=5), created_at + timedelta(minutes=30))
    ticket["status"] = "Решена"
    ticket["resolved_at"] = _iso(resolved_at)
    ticket["closed_at"] = None
    ticket["updated_at"] = _iso(changed_at)
    ticket["resolution_text"] = (
        f"Повторная диагностика выполнена. Работа сервиса «{ticket['service']}» восстановлена."
    )
    return ticket
