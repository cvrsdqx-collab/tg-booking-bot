import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from booking_bot.schedule import WorkSchedule, booking_days, free_slots, load_catalog, normalize_phone

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = WorkSchedule(opens=time(10), closes=time(13), step_minutes=30, days_ahead=7,
                        days_off=frozenset({6}), min_lead_minutes=60)
MONDAY = date(2026, 11, 9)
SUNDAY = date(2026, 11, 8)
EARLY = datetime(2026, 11, 1, 9, 0)


class FreeSlotsTest(unittest.TestCase):
    def test_lists_slots_that_fit_before_closing(self) -> None:
        slots = free_slots(SCHEDULE, MONDAY, 60, [], EARLY)

        self.assertEqual([s.strftime("%H:%M") for s in slots], ["10:00", "10:30", "11:00", "11:30", "12:00"])

    def test_skips_slots_overlapping_existing_booking(self) -> None:
        busy = [(datetime(2026, 11, 9, 11, 0), datetime(2026, 11, 9, 12, 0))]

        slots = free_slots(SCHEDULE, MONDAY, 60, busy, EARLY)

        self.assertEqual([s.strftime("%H:%M") for s in slots], ["10:00", "12:00"])

    def test_back_to_back_booking_is_allowed(self) -> None:
        busy = [(datetime(2026, 11, 9, 10, 0), datetime(2026, 11, 9, 10, 30))]

        slots = free_slots(SCHEDULE, MONDAY, 30, busy, EARLY)

        self.assertEqual(slots[0].strftime("%H:%M"), "10:30")

    def test_respects_minimum_lead_time(self) -> None:
        now = datetime(2026, 11, 9, 10, 15)

        slots = free_slots(SCHEDULE, MONDAY, 30, [], now)

        self.assertEqual(slots[0].strftime("%H:%M"), "11:30")

    def test_no_slots_on_day_off(self) -> None:
        self.assertEqual(free_slots(SCHEDULE, SUNDAY, 30, [], EARLY), [])

    def test_no_slots_when_service_longer_than_day(self) -> None:
        self.assertEqual(free_slots(SCHEDULE, MONDAY, 240, [], EARLY), [])


class BookingDaysTest(unittest.TestCase):
    def test_skips_days_off(self) -> None:
        days = booking_days(SCHEDULE, date(2026, 11, 5))  # чт … ср, вс пропущено

        self.assertEqual(len(days), 6)
        self.assertNotIn(SUNDAY, days)


class NormalizePhoneTest(unittest.TestCase):
    def test_normalizes_russian_formats(self) -> None:
        for raw in ("8 (900) 123-45-67", "+7 900 123 45 67", "79001234567"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone(raw), "+79001234567")

    def test_rejects_garbage(self) -> None:
        for raw in ("", "привет", "12345", "1" * 16):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_phone(raw))


class LoadCatalogTest(unittest.TestCase):
    def test_loads_project_catalog(self) -> None:
        catalog = load_catalog(ROOT / "config" / "services.toml")

        self.assertEqual(catalog.service("haircut").minutes, 60)
        self.assertIsNone(catalog.service("missing"))

    def test_rejects_catalog_without_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            path.write_text('[schedule]\nopens = "10:00"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(path)

    def test_rejects_inverted_working_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            path.write_text('[schedule]\nopens = "20:00"\ncloses = "10:00"\n'
                            '[services.a]\ntitle = "A"\nminutes = 30\nprice = 100\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
