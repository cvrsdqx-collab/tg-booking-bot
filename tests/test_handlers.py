import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import date, datetime
from pathlib import Path

from booking_bot.handlers import (
    DAY_FORMAT, DayCb, SlotCb, days_keyboard, edit, parse_moment, services_keyboard, slots_keyboard,
)
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


if __name__ == "__main__":
    unittest.main()
