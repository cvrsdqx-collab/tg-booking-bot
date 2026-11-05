"""Диалог записи: услуга → день → время → имя → телефон → подтверждение. Плюс «Мои записи» и /today для админа."""
from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot, F, Router, html
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Settings
from .schedule import Catalog, booking_days, free_slots, normalize_phone
from .storage import Booking, BookingRepository, NewBooking, SlotTakenError

router = Router()
log = logging.getLogger(__name__)

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
DAY_FORMAT = "%Y%m%d"
SLOT_FORMAT = "%H%M"   # без двоеточия: «:» — разделитель в callback_data
MAX_NAME_LENGTH = 50


class Form(StatesGroup):
    name = State()
    phone = State()
    confirm = State()


class ServiceCb(CallbackData, prefix="svc"):
    code: str


class DayCb(CallbackData, prefix="day"):
    value: str


class SlotCb(CallbackData, prefix="slot"):
    value: str


class ConfirmCb(CallbackData, prefix="ok"):
    accept: bool


class CancelCb(CallbackData, prefix="cancel"):
    booking_id: int


def local_now(settings: Settings) -> datetime:
    """Время салона без зоны — в базе хранится так же."""
    return datetime.now(settings.timezone).replace(tzinfo=None)


def describe(booking: Booking) -> str:
    when = f"{WEEKDAYS[booking.starts_at.weekday()]} {booking.starts_at:%d.%m} в {booking.starts_at:%H:%M}"
    return f"{html.quote(booking.service)} — {when}, {booking.price} ₽"


def services_keyboard(catalog: Catalog):
    builder = InlineKeyboardBuilder()
    for service in catalog.services:
        builder.button(text=f"{service.title} · {service.price} ₽", callback_data=ServiceCb(code=service.code))
    return builder.adjust(1).as_markup()


def days_keyboard(days: list[date]):
    builder = InlineKeyboardBuilder()
    for day in days:
        builder.button(text=f"{WEEKDAYS[day.weekday()]} {day:%d.%m}", callback_data=DayCb(value=day.strftime(DAY_FORMAT)))
    return builder.adjust(3).as_markup()


def slots_keyboard(slots: list[datetime]):
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=f"{slot:%H:%M}", callback_data=SlotCb(value=slot.strftime(SLOT_FORMAT)))
    return builder.adjust(4).as_markup()


async def notify_admins(bot: Bot, settings: Settings, text: str) -> None:
    """Сбой у одного админа (не нажал /start, заблокировал бота) не мешает остальным."""
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError as exc:
            log.warning("Не удалось уведомить админа %s: %s", admin_id, exc)


async def edit(query: CallbackQuery, text: str, reply_markup=None) -> None:
    """Меняет сообщение с кнопками. Старое (недоступное) сообщение или повторное нажатие не роняют обработчик."""
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:  # «message is not modified» при двойном нажатии
            log.info("Сообщение не изменено: %s", exc)
    else:  # сообщение слишком старое для редактирования — отвечаем новым
        await query.bot.send_message(query.from_user.id, text, reply_markup=reply_markup)


def parse_moment(value: str, fmt: str) -> datetime | None:
    """callback_data приходит от клиента и может быть подделан."""
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, catalog: Catalog) -> None:
    await state.clear()
    await message.answer(
        "Здравствуйте! Здесь можно записаться без звонков.\nВыберите услугу:",
        reply_markup=services_keyboard(catalog),
    )


@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cancel_dialog(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Запись прервана. Начать заново — /start", reply_markup=ReplyKeyboardRemove())


@router.callback_query(ServiceCb.filter())
async def choose_service(query: CallbackQuery, callback_data: ServiceCb, state: FSMContext,
                         catalog: Catalog, settings: Settings) -> None:
    service = catalog.service(callback_data.code)
    if service is None:
        await query.answer("Эта услуга больше недоступна", show_alert=True)
        return
    await state.clear()
    await state.set_data({"service": service.code})
    days = booking_days(catalog.schedule, local_now(settings).date())
    await edit(query, f"{html.quote(service.title)}, {service.minutes} мин. Выберите день:",
                                  reply_markup=days_keyboard(days))
    await query.answer()


@router.callback_query(DayCb.filter())
async def choose_day(query: CallbackQuery, callback_data: DayCb, state: FSMContext,
                     catalog: Catalog, settings: Settings, repo: BookingRepository) -> None:
    service = catalog.service((await state.get_data()).get("service", ""))
    moment = parse_moment(callback_data.value, DAY_FORMAT)
    now = local_now(settings)
    if service is None or moment is None or moment.date() not in booking_days(catalog.schedule, now.date()):
        await query.answer("Начните заново: /start", show_alert=True)
        return
    slots = free_slots(catalog.schedule, day, service.minutes, repo.busy_intervals(day), now)
    if not slots:
        await query.answer("На этот день свободных окон нет — выберите другой", show_alert=True)
        return
    day = moment.date()
    await state.update_data(day=callback_data.value)
    await edit(query, f"{WEEKDAYS[day.weekday()]} {day:%d.%m}. Свободное время:",
                                  reply_markup=slots_keyboard(slots))
    await query.answer()


@router.callback_query(SlotCb.filter())
async def choose_slot(query: CallbackQuery, callback_data: SlotCb, state: FSMContext,
                      catalog: Catalog, settings: Settings, repo: BookingRepository) -> None:
    data = await state.get_data()
    service = catalog.service(data.get("service", ""))
    starts_at = parse_moment(data.get("day", "") + callback_data.value, DAY_FORMAT + SLOT_FORMAT)
    if service is None or starts_at is None:
        await query.answer("Начните заново: /start", show_alert=True)
        return
    # callback_data приходит от клиента: проверяем, что окно действительно свободно, а не верим кнопке
    if starts_at not in free_slots(catalog.schedule, starts_at.date(), service.minutes,
                                   repo.busy_intervals(starts_at.date()), local_now(settings)):
        await query.answer("Это время уже занято, выберите другое", show_alert=True)
        return
    await state.update_data(starts_at=starts_at.isoformat())
    await state.set_state(Form.name)
    await edit(query, f"{starts_at:%d.%m} в {starts_at:%H:%M}. Как к вам обращаться?")
    await query.answer()


@router.message(Form.name, F.text, ~F.text.startswith("/"))  # команды (/my) не принимаем за имя
async def enter_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not 2 <= len(name) <= MAX_NAME_LENGTH:
        await message.answer(f"Имя — от 2 до {MAX_NAME_LENGTH} символов. Попробуйте ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(Form.phone)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)], [KeyboardButton(text="Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await message.answer("Оставьте телефон для связи — кнопкой ниже или текстом:", reply_markup=keyboard)


@router.message(Form.phone, ~F.text.startswith("/"))
async def enter_phone(message: Message, state: FSMContext, catalog: Catalog) -> None:
    raw = message.contact.phone_number if message.contact else (message.text or "")
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer("Не похоже на номер телефона. Пример: +7 900 123-45-67")
        return
    data = await state.update_data(phone=phone)
    service = catalog.service(data["service"])
    starts_at = datetime.fromisoformat(data["starts_at"])
    await state.set_state(Form.confirm)
    await message.answer("Проверьте данные:", reply_markup=ReplyKeyboardRemove())
    builder = InlineKeyboardBuilder()
    builder.button(text="Записаться", callback_data=ConfirmCb(accept=True))
    builder.button(text="Отменить", callback_data=ConfirmCb(accept=False))
    await message.answer(
        f"<b>{html.quote(service.title)}</b>, {service.price} ₽\n"
        f"{WEEKDAYS[starts_at.weekday()]} {starts_at:%d.%m} в {starts_at:%H:%M}\n"
        f"{html.quote(data['name'])}, {phone}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(Form.confirm, ConfirmCb.filter())
async def confirm(query: CallbackQuery, callback_data: ConfirmCb, state: FSMContext, bot: Bot,
                  catalog: Catalog, settings: Settings, repo: BookingRepository) -> None:
    data = await state.get_data()
    await state.clear()
    if not callback_data.accept:
        await edit(query, "Запись отменена. Начать заново — /start")
        await query.answer()
        return
    service = catalog.service(data.get("service", ""))
    if service is None or "starts_at" not in data:
        await edit(query, "Данные записи устарели. Начните заново: /start")
        await query.answer()
        return
    if datetime.fromisoformat(data["starts_at"]) <= local_now(settings):
        await edit(query, "Это время уже прошло. Выберите другое: /start")
        await query.answer()
        return
    try:
        booking = repo.create(NewBooking(
            user_id=query.from_user.id, client_name=data["name"], phone=data["phone"], service=service.title,
            price=service.price, starts_at=datetime.fromisoformat(data["starts_at"]), minutes=service.minutes,
        ))
    except SlotTakenError:
        await edit(query, "Пока вы заполняли данные, это время заняли. Выберите другое: /start")
        await query.answer()
        return
    await edit(query, f"Готово, вы записаны: {describe(booking)}.\nОтменить — /my")
    await query.answer()
    await notify_admins(bot, settings, f"Новая запись: {describe(booking)}\n"
                                       f"{html.quote(booking.client_name)}, {booking.phone}")


@router.message(Command("my"))
async def my_bookings(message: Message, repo: BookingRepository, settings: Settings) -> None:
    bookings = repo.upcoming_for_user(message.from_user.id, local_now(settings))
    if not bookings:
        await message.answer("Активных записей нет. Записаться — /start")
        return
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        builder.button(text=f"Отменить {booking.starts_at:%d.%m %H:%M}", callback_data=CancelCb(booking_id=booking.id))
    await message.answer("Ваши записи:\n" + "\n".join(describe(b) for b in bookings),
                         reply_markup=builder.adjust(1).as_markup())


@router.callback_query(CancelCb.filter())
async def cancel_booking(query: CallbackQuery, callback_data: CancelCb, bot: Bot,
                         repo: BookingRepository, settings: Settings) -> None:
    booking = repo.cancel(callback_data.booking_id, query.from_user.id)
    if booking is None:
        await query.answer("Запись не найдена или уже отменена", show_alert=True)
        return
    await edit(query, f"Запись отменена: {describe(booking)}")
    await query.answer()
    await notify_admins(bot, settings, f"Отмена: {describe(booking)}\n{html.quote(booking.client_name)}, {booking.phone}")


@router.message(Command("today"))
async def today(message: Message, repo: BookingRepository, settings: Settings) -> None:
    if message.from_user.id not in settings.admin_ids:
        return  # для клиентов команды нет
    bookings = repo.for_day(local_now(settings).date())
    lines = [f"{b.starts_at:%H:%M}–{b.ends_at:%H:%M} {html.quote(b.service)} · "
             f"{html.quote(b.client_name)}, {b.phone}" for b in bookings]
    await message.answer("Записи на сегодня:\n" + ("\n".join(lines) or "нет"))
