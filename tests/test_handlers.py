import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import date, datetime
from pathlib import Path

import tempfile
from zoneinfo import ZoneInfo

from booking_bot.config import Settings
from booking_bot.handlers import (
    DAY_FORMAT, DayCb, SlotCb, choose_day, days_keyboard, edit, local_now, parse_moment, services_keyboard,
    slots_keyboard,
)
from booking_bot.schedule import booking_days
from booking_bot.storage import BookingRepository
from booking_bot.schedule import load_catalog

ROOT = Path(__file__).resolve().parent.parent


class KeyboardsTest(unittest.TestCase):
    def test_service_buttons_carry_service_codes(self) -> None:
        markup = services_keyboard(load_catalog(ROOT / "config" / "services.toml"))

        data = [row[0].callback_data for row in markup.inline_keyboard]
        self.assertEqual(data, ["svc:haircut", "svc:beard", "svc:combo"])

    def test_day_and_slot_callbacks_round_trip(self) -> None:
        day_button = days_keyboard([date(2026, 11, 9)]).inline_keyboard[0][0]
        slot_button = slots_keyboard([datetime(2026, 11, 9, 10, 30)]).inline_keyboard[0][0]

        self.assertEqual(day_button.text, "Пн 09.11")
        self.assertEqual(DayCb.unpack(day_button.callback_data).value, "20261109")
        self.assertEqual(SlotCb.unpack(slot_button.callback_data).value, "1030")

    def test_callback_data_fits_telegram_limit(self) -> None:
        markup = slots_keyboard([datetime(2026, 11, 9, 10, 30)])

        self.assertLessEqual(len(markup.inline_keyboard[0][0].callback_data.encode()), 64)


class HelpersTest(unittest.TestCase):
    def test_forged_callback_value_is_rejected(self) -> None:
        self.assertIsNone(parse_moment("2026-13-99", DAY_FORMAT))
        self.assertEqual(parse_moment("20261109", DAY_FORMAT).day, 9)

    def test_edit_sends_new_message_when_original_is_inaccessible(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        query = SimpleNamespace(message=None, bot=bot, from_user=SimpleNamespace(id=42))

        asyncio.run(edit(query, "текст"))

        bot.send_message.assert_awaited_once_with(42, "текст", reply_markup=None)


class ChooseDayTest(unittest.TestCase):
    """Регрессия: выбор дня падал с UnboundLocalError (переменная day до присваивания)."""

    def test_shows_free_slots_for_selected_day(self) -> None:
        catalog = load_catalog(ROOT / "config" / "services.toml")
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings("t", frozenset(), Path(tmp) / "b.db", ROOT / "config" / "services.toml",
                                ZoneInfo("Europe/Moscow"))
            repo = BookingRepository(settings.db_path)
            day = booking_days(catalog.schedule, local_now(settings).date())[-1]  # последний день — окна точно есть
            bot = SimpleNamespace(send_message=AsyncMock())
            query = SimpleNamespace(message=None, bot=bot, from_user=SimpleNamespace(id=1), answer=AsyncMock())
            state = SimpleNamespace(get_data=AsyncMock(return_value={"service": "haircut"}), update_data=AsyncMock())

            asyncio.run(choose_day(query, DayCb(value=day.strftime(DAY_FORMAT)), state, catalog, settings, repo))
            repo.close()

        text = bot.send_message.await_args.args[1]
        self.assertIn("Свободное время", text)
        state.update_data.assert_awaited_once_with(day=day.strftime(DAY_FORMAT))


if __name__ == "__main__":
    unittest.main()
