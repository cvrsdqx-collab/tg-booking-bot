"""Расписание и свободные окна. Чистые функции: без Telegram и базы, легко тестировать."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

PHONE_DIGITS = re.compile(r"\D")
MIN_PHONE_DIGITS = 10
MAX_PHONE_DIGITS = 15


@dataclass(frozen=True)
class Service:
    code: str
    title: str
    minutes: int
    price: int


@dataclass(frozen=True)
class WorkSchedule:
    opens: time
    closes: time
    step_minutes: int
    days_ahead: int
    days_off: frozenset[int]     # 0 — понедельник … 6 — воскресенье
    min_lead_minutes: int        # за сколько минут до начала ещё можно записаться

    def is_working_day(self, day: date) -> bool:
        return day.weekday() not in self.days_off


@dataclass(frozen=True)
class Catalog:
    services: tuple[Service, ...]
    schedule: WorkSchedule

    def service(self, code: str) -> Service | None:
        return next((s for s in self.services if s.code == code), None)


def load_catalog(path: Path) -> Catalog:
    """Услуги и график из TOML: владелец меняет их без правки кода."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    services = tuple(
        Service(code=str(code), title=str(item["title"]), minutes=int(item["minutes"]), price=int(item["price"]))
        for code, item in data.get("services", {}).items()
    )
    if not services:
        raise ValueError(f"В {path} нет ни одной услуги [services.<код>]")
    if any(s.minutes <= 0 or s.price < 0 for s in services):
        raise ValueError("Длительность услуги должна быть > 0, цена — ≥ 0")
    work = data.get("schedule", {})
    schedule = WorkSchedule(
        opens=time.fromisoformat(work.get("opens", "10:00")),
        closes=time.fromisoformat(work.get("closes", "20:00")),
        step_minutes=int(work.get("step_minutes", 30)),
        days_ahead=int(work.get("days_ahead", 7)),
        days_off=frozenset(int(d) for d in work.get("days_off", [6])),
        min_lead_minutes=int(work.get("min_lead_minutes", 60)),
    )
    if schedule.opens >= schedule.closes or schedule.step_minutes <= 0 or schedule.days_ahead <= 0:
        raise ValueError("Проверьте график: opens < closes, step_minutes > 0, days_ahead > 0")
    return Catalog(services, schedule)


def booking_days(schedule: WorkSchedule, today: date) -> list[date]:
    """Рабочие дни, на которые открыта запись (начиная с сегодня)."""
    days = (today + timedelta(days=offset) for offset in range(schedule.days_ahead))
    return [day for day in days if schedule.is_working_day(day)]


def free_slots(
    schedule: WorkSchedule,
    day: date,
    minutes: int,
    busy: list[tuple[datetime, datetime]],
    now: datetime,
) -> list[datetime]:
    """Начала окон, где услуга длительностью `minutes` помещается до закрытия и не пересекается с записями."""
    if not schedule.is_working_day(day):
        return []
    duration = timedelta(minutes=minutes)
    step = timedelta(minutes=schedule.step_minutes)
    earliest = now + timedelta(minutes=schedule.min_lead_minutes)
    start = datetime.combine(day, schedule.opens)
    closes = datetime.combine(day, schedule.closes)
    slots: list[datetime] = []
    while start + duration <= closes:
        end = start + duration
        if start >= earliest and not any(start < b_end and b_start < end for b_start, b_end in busy):
            slots.append(start)
        start += step
    return slots


def normalize_phone(text: str) -> str | None:
    """«8 (900) 123-45-67» → «+79001234567». None — не похоже на телефон."""
    digits = PHONE_DIGITS.sub("", text)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return None
    return "+" + digits
