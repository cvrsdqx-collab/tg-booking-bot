"""Записи клиентов в SQLite. Пересечения проверяются внутри транзакции: два клиента не займут одно окно."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    phone       TEXT NOT NULL,
    service     TEXT NOT NULL,
    price       INTEGER NOT NULL,
    starts_at   TEXT NOT NULL,
    ends_at     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bookings_starts ON bookings(starts_at) WHERE status = 'active';
"""


class SlotTakenError(Exception):
    """Окно успели занять, пока клиент заполнял имя и телефон."""


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    client_name: str
    phone: str
    service: str
    price: int
    starts_at: datetime
    ends_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Booking:
        return cls(
            id=row["id"], user_id=row["user_id"], client_name=row["client_name"], phone=row["phone"],
            service=row["service"], price=row["price"],
            starts_at=datetime.fromisoformat(row["starts_at"]), ends_at=datetime.fromisoformat(row["ends_at"]),
        )


@dataclass(frozen=True)
class NewBooking:
    user_id: int
    client_name: str
    phone: str
    service: str
    price: int
    starts_at: datetime
    minutes: int


class BookingRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)  # транзакции открываем явно
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def busy_intervals(self, day: date) -> list[tuple[datetime, datetime]]:
        rows = self._conn.execute(
            "SELECT starts_at, ends_at FROM bookings WHERE status = 'active' AND starts_at >= ? AND starts_at < ?",
            (day.isoformat(), (day + timedelta(days=1)).isoformat()),
        ).fetchall()
        return [(datetime.fromisoformat(r["starts_at"]), datetime.fromisoformat(r["ends_at"])) for r in rows]

    def create(self, new: NewBooking) -> Booking:
        """Создаёт запись или бросает SlotTakenError, если окно уже пересекается с активной записью."""
        ends_at = new.starts_at + timedelta(minutes=new.minutes)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            clash = self._conn.execute(
                "SELECT 1 FROM bookings WHERE status = 'active' AND starts_at < ? AND ends_at > ?",
                (ends_at.isoformat(), new.starts_at.isoformat()),
            ).fetchone()
            if clash:
                raise SlotTakenError(new.starts_at.isoformat())
            cursor = self._conn.execute(
                "INSERT INTO bookings (user_id, client_name, phone, service, price, starts_at, ends_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new.user_id, new.client_name, new.phone, new.service, new.price,
                 new.starts_at.isoformat(), ends_at.isoformat()),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return Booking(cursor.lastrowid, new.user_id, new.client_name, new.phone, new.service, new.price,
                       new.starts_at, ends_at)

    def upcoming_for_user(self, user_id: int, now: datetime) -> list[Booking]:
        rows = self._conn.execute(
            "SELECT * FROM bookings WHERE user_id = ? AND status = 'active' AND starts_at >= ? ORDER BY starts_at",
            (user_id, now.isoformat()),
        ).fetchall()
        return [Booking.from_row(r) for r in rows]

    def for_day(self, day: date) -> list[Booking]:
        rows = self._conn.execute(
            "SELECT * FROM bookings WHERE status = 'active' AND starts_at >= ? AND starts_at < ? ORDER BY starts_at",
            (day.isoformat(), (day + timedelta(days=1)).isoformat()),
        ).fetchall()
        return [Booking.from_row(r) for r in rows]

    def cancel(self, booking_id: int, user_id: int) -> Booking | None:
        """Отменяет только свою активную запись. None — записи нет или она чужая."""
        row = self._conn.execute(
            "SELECT * FROM bookings WHERE id = ? AND user_id = ? AND status = 'active'", (booking_id, user_id),
        ).fetchone()
        if row is None:
            return None
        self._conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        return Booking.from_row(row)
