"""Запуск: python -m booking_bot"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_settings
from .handlers import router
from .schedule import load_catalog
from .storage import BookingRepository

COMMANDS = [
    BotCommand(command="start", description="Записаться"),
    BotCommand(command="my", description="Мои записи"),
    BotCommand(command="cancel", description="Прервать запись"),
]


async def run() -> None:
    settings = load_settings()
    catalog = load_catalog(settings.catalog_path)
    repo = BookingRepository(settings.db_path)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(catalog=catalog, settings=settings, repo=repo)
    dispatcher.include_router(router)
    try:
        await bot.set_my_commands(COMMANDS)
        await dispatcher.start_polling(bot)
    finally:
        repo.close()
        await bot.session.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run())
    except ValueError as exc:  # ошибки настроек и каталога — понятным текстом
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
