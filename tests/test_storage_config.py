import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from booking_bot.config import load_settings
from booking_bot.storage import BookingRepository, NewBooking, SlotTakenError

START = datetime(2026, 11, 9, 11, 0)


def new_booking(user_id: int = 1, starts_at: datetime = START, minutes: int = 60) -> NewBooking:
    return NewBooking(user_id=user_id, client_name="Анна", phone="+79001234567", service="Стрижка",
                      price=1500, starts_at=starts_at, minutes=minutes)


class BookingRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = BookingRepository(Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self.repo.close()
        self._tmp.cleanup()

    def test_created_booking_occupies_its_interval(self) -> None:
        booking = self.repo.create(new_booking())

        self.assertEqual(booking.ends_at, datetime(2026, 11, 9, 12, 0))
        self.assertEqual(self.repo.busy_intervals(date(2026, 11, 9)), [(booking.starts_at, booking.ends_at)])

    def test_overlapping_booking_is_refused(self) -> None:
        self.repo.create(new_booking())

        with self.assertRaises(SlotTakenError):
            self.repo.create(new_booking(user_id=2, starts_at=datetime(2026, 11, 9, 11, 30)))

    def test_adjacent_booking_is_allowed(self) -> None:
        self.repo.create(new_booking())

        self.repo.create(new_booking(user_id=2, starts_at=datetime(2026, 11, 9, 12, 0)))

        self.assertEqual(len(self.repo.for_day(date(2026, 11, 9))), 2)

    def test_user_cannot_cancel_someone_elses_booking(self) -> None:
        booking = self.repo.create(new_booking(user_id=1))

        self.assertIsNone(self.repo.cancel(booking.id, user_id=2))
        self.assertEqual(len(self.repo.for_day(date(2026, 11, 9))), 1)

    def test_cancel_frees_the_slot(self) -> None:
        booking = self.repo.create(new_booking())

        self.assertIsNotNone(self.repo.cancel(booking.id, user_id=1))

        self.assertEqual(self.repo.busy_intervals(date(2026, 11, 9)), [])
        self.repo.create(new_booking(user_id=2))  # окно снова свободно

    def test_upcoming_lists_only_future_bookings_of_user(self) -> None:
        self.repo.create(new_booking(user_id=1, starts_at=datetime(2026, 11, 2, 10, 0)))
        future = self.repo.create(new_booking(user_id=1))
        self.repo.create(new_booking(user_id=2, starts_at=datetime(2026, 11, 9, 15, 0)))

        upcoming = self.repo.upcoming_for_user(1, now=datetime(2026, 11, 5, 12, 0))

        self.assertEqual([b.id for b in upcoming], [future.id])


class LoadSettingsTest(unittest.TestCase):
    NO_FILE = Path("/nonexistent/.env")

    def test_requires_token(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            load_settings({}, env_file=self.NO_FILE)
        self.assertIn("BOT_TOKEN", str(ctx.exception))

    def test_parses_admin_ids(self) -> None:
        settings = load_settings({"BOT_TOKEN": "t", "ADMIN_IDS": "1, 22"}, env_file=self.NO_FILE)

        self.assertEqual(settings.admin_ids, frozenset({1, 22}))

    def test_rejects_non_numeric_admin_ids(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"BOT_TOKEN": "t", "ADMIN_IDS": "anna"}, env_file=self.NO_FILE)

    def test_repr_never_contains_token(self) -> None:
        settings = load_settings({"BOT_TOKEN": "123:SECRET"}, env_file=self.NO_FILE)

        self.assertNotIn("SECRET", repr(settings))

    def test_env_file_is_read_and_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text('# comment\nBOT_TOKEN="from-file"\nTIMEZONE=Europe/Samara\n', encoding="utf-8")

            settings = load_settings({"TIMEZONE": "Asia/Yekaterinburg"}, env_file=env_file)

        self.assertEqual(settings.bot_token, "from-file")
        self.assertEqual(str(settings.timezone), "Asia/Yekaterinburg")


if __name__ == "__main__":
    unittest.main()
