"""Настройки из переменных окружения (и файла .env, если он есть). Токен нигде не печатается."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: Path
    catalog_path: Path
    timezone: ZoneInfo

    def __repr__(self) -> str:  # токен не должен попасть в логи даже случайно
        return f"Settings(admin_ids={sorted(self.admin_ids)}, db_path={self.db_path}, timezone={self.timezone})"


def read_env_file(path: Path) -> dict[str, str]:
    """Минимальный разбор .env: KEY=VALUE, комментарии #, кавычки вокруг значения."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_settings(env: dict[str, str] | None = None, env_file: Path = ROOT / ".env") -> Settings:
    """Переменные окружения важнее .env. Ошибки — понятным текстом, без значения токена."""
    merged = {**read_env_file(env_file), **(os.environ if env is None else env)}
    token = merged.get("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Не задан BOT_TOKEN: скопируйте .env.example в .env и вставьте токен от @BotFather")
    try:
        admin_ids = frozenset(int(x) for x in merged.get("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    except ValueError as exc:
        raise ValueError("ADMIN_IDS — числовые id Telegram через запятую") from exc
    try:
        timezone = ZoneInfo(merged.get("TIMEZONE", "Europe/Moscow"))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Неизвестный часовой пояс: {merged.get('TIMEZONE')}") from exc
    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=Path(merged.get("DB_PATH", ROOT / "data" / "bookings.db")),
        catalog_path=Path(merged.get("CATALOG_PATH", ROOT / "config" / "services.toml")),
        timezone=timezone,
    )
