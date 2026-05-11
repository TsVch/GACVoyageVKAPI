import calendar
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.fsm.states import DialogState
from app.fsm.storage import FSMStorage
from app.schemas.vk import VKObjectMessage
from app.services.booking_calendar import BookingCalendar
from app.services.booking_service import BookingService
from app.services.notification_service import notify_drivers
from app.services.pdf_service import PDFService
from app.services.vk_service import VKService

logger = logging.getLogger(__name__)
router = APIRouter()
storage = FSMStorage()


def _button(label: str, payload: dict, color: str = "secondary") -> dict:
    return {"action": {"type": "text", "label": label, "payload": json.dumps(payload)}, "color": color}


def tour_keyboard(tour_id: int) -> dict:
    return {"inline": True, "buttons": [[_button("Select tour", {"tour_id": tour_id}, "primary")]]}


def main_menu_keyboard() -> dict:
    return {"inline": True, "buttons": [[_button("Мои бронирования", {"cmd": "my_bookings"})]]}


def booking_action_keyboard(booking_date: date) -> dict:
    return {"inline": True, "buttons": [[_button("Забронировать", {"cmd": f"book:{booking_date.isoformat()}"}, "positive")]]}


def consent_keyboard() -> dict:
    return {
        "inline": True,
        "buttons": [[_button("✅ Согласен на обработку персональных данных", {"cmd": "consent:yes"}, "positive")]],
    }


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    if month < 1:
        return year - 1, 12
    if month > 12:
        return year + 1, 1
    return year, month


def _month_title(year: int, month: int) -> str:
    month_names = {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    }
    return f"{month_names[month]} {year}"


async def build_compact_calendar_keyboard(cal: BookingCalendar, year: int, month: int) -> dict:
    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    month_title = _month_title(year, month)
    nav_row = [
        _button("◀", {"cmd": f"cal_nav:{prev_year:04d}-{prev_month:02d}"}),
        _button(month_title, {"cmd": "noop"}),
        _button("▶", {"cmd": f"cal_nav:{next_year:04d}-{next_month:02d}"}),
    ]
    weekday_row = [_button(day, {"cmd": "noop"}) for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]]
    month_data = await cal.get_month_data(cal.tour.id, year, month)
    week_rows = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)[:5]:
        row = []
        for day in week:
            if day.month != month:
                continue
            status = cal.get_day_status(day, month_data["days"].get(day))
            row.append(_button(f"{day.day}{status.emoji}", {"cmd": f"date:{day.isoformat()}"}))
        if row:
            week_rows.append(row[:7])
    return {"inline": True, "buttons": [nav_row, weekday_row, *week_rows][:7]}


def day_status_title(status: str) -> str:
    return {
        "blocked": "❌ Дата заблокирована",
        "full": "🚫 Мест нет",
        "low": "🔴 Осталось 1 место",
        "medium": "🟡 Места есть",
        "high": "🟢 Много свободных мест",
    }.get(status, "⚪ Дата недоступна")


async def send_month_calendar(vk: VKService, user_id: int, cal: BookingCalendar, year: int, month: int) -> None:
    keyboard = await build_compact_calendar_keyboard(cal, year, month)
    await vk.send_message(user_id, "Выберите дату:", keyboard=keyboard)


async def send_day_details(vk: VKService, user_id: int, cal: BookingCalendar, selected: date) -> None:
    capacity = await cal.get_day_capacity(selected)
    if capacity.status == "blocked":
        message = (
            f"📅 {selected.strftime('%d.%m.%Y')}\n\n"
            "❌ Дата заблокирована для бронирования\n\n"
            "Выберите другую дату."
        )
        await vk.send_message(user_id, message)
        return
    if capacity.status == "full":
        message = (
            f"📅 {selected.strftime('%d.%m.%Y')}\n\n"
            "🚫 Мест нет\n\n"
            f"👥 Всего мест: {capacity.total_places}\n"
            f"❌ Занято: {capacity.booked_places}\n\n"
            "Выберите другую дату."
        )
        await vk.send_message(user_id, message)
        return

    message = (
        f"📅 {selected.strftime('%d.%m.%Y')}\n\n"
        f"{day_status_title(capacity.status)}\n\n"
        f"👥 Всего мест: {capacity.total_places}\n"
        f"✅ Свободно: {capacity.available_places}\n"
        f"❌ Занято: {capacity.booked_places}\n\n"
        f"{_day_message(capacity.status, capacity.available_places, capacity.total_places)}"
    )
    await vk.send_message(user_id, message, keyboard=booking_action_keyboard(selected))


def _day_message(status: str, available_places: int, total_places: int) -> str:
    if status == "blocked":
        return "Дата заблокирована для бронирования"
    if status == "full":
        return "Мест нет"
    return f"Свободно {available_places} из {total_places} мест. Хотите забронировать?"


@router.post("/vk/callback", response_class=PlainTextResponse)
async def vk_callback(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    settings = get_settings()
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Invalid or empty request body from %s", request.client)
        return PlainTextResponse("ok", status_code=200)

    if payload.get("type") == "confirmation":
        return PlainTextResponse(settings.vk_confirmation_code, status_code=200)

    if payload.get("type") != "message_new":
        return PlainTextResponse("ok", status_code=200)

    vk = VKService()
    msg = VKObjectMessage(**payload.get("object", {}).get("message", {}))
    user_id = msg.from_id
    text = msg.text.strip()
    session = await storage.get(user_id)
    booking_service = BookingService(db)

    try:
        payload_data = {}
        if msg.payload:
            try:
                payload_data = json.loads(msg.payload)
            except json.JSONDecodeError:
                payload_data = {}

        if text.lower() in {"start", "начать", "привет"}:
            tours = await booking_service.list_tours()
            await vk.send_message(user_id, "Выберите действие или экскурсию", keyboard=main_menu_keyboard())
            for t in tours:
                media = "\n".join([f"Фото: {u}" for u in t.photo_urls[:3]])
                card = (
                    f"🏝 {t.name}\n{t.description}\n💵 {t.price} ₽\n⭐ {t.rating}\n"
                    f"Альбом: {t.vk_album_url or '-'}\nВидео: {t.video_url or '-'}\n{media}"
                )
                await vk.send_message(user_id, card, keyboard=tour_keyboard(t.id))
            session.state = DialogState.SELECT_DATE
            await storage.set(user_id, session)
            return PlainTextResponse("ok", status_code=200)

        if payload_data.get("cmd") == "my_bookings":
            internal_user_id = session.payload.get("user_id")
            if internal_user_id is None:
                user = await booking_service.get_user(vk_id=str(user_id))
                if user:
                    internal_user_id = user.id
                    session.payload["user_id"] = internal_user_id
                    await storage.set(user_id, session)
            if internal_user_id is None:
                await vk.send_message(user_id, "У вас пока нет бронирований.")
                return PlainTextResponse("ok", status_code=200)
            bookings = await booking_service.list_user_bookings(user_id=int(internal_user_id))
            if not bookings:
                await vk.send_message(user_id, "У вас пока нет бронирований.")
                return PlainTextResponse("ok", status_code=200)
            lines = [
                f"#{b.id}: {b.tour.name if b.tour else 'Экскурсия'} — {b.date}, "
                f"{b.people_count} чел., статус: {b.status}"
                for b in bookings
            ]
            await vk.send_message(user_id, "Ваши бронирования:\n" + "\n".join(lines))
            return PlainTextResponse("ok", status_code=200)

        if payload_data.get("tour_id"):
            session.payload["tour_id"] = int(payload_data["tour_id"])
            session.state = DialogState.SELECT_DATE
            await storage.set(user_id, session)
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            if tour:
                cal = BookingCalendar(db, tour)
                now = datetime.utcnow()
                legend = (
                    "🟢 4–6 мест свободно\n🟡 2–3 места свободно\n🔴 1 место осталось\n"
                    "🚫 мест нет\n❌ дата заблокирована\n⚪ дата недоступна"
                )
                await vk.send_message(user_id, legend)
                await send_month_calendar(vk, user_id, cal, now.year, now.month)
            return PlainTextResponse("ok", status_code=200)

        cmd_val = payload_data.get("cmd", "")
        if cmd_val == "noop":
            return PlainTextResponse("ok", status_code=200)

        if cmd_val.startswith("cal_nav:") and session.state == DialogState.SELECT_DATE:
            nav_ym = cmd_val.split(":", 1)[1]
            nav_year, nav_month = int(nav_ym[:4]), int(nav_ym[5:7])
            tour_id = session.payload.get("tour_id")
            if tour_id:
                tour = await booking_service.get_tour(int(tour_id))
                if tour:
                    await send_month_calendar(vk, user_id, BookingCalendar(db, tour), nav_year, nav_month)
            return PlainTextResponse("ok", status_code=200)

        if cmd_val.startswith("date:") and session.state == DialogState.SELECT_DATE:
            selected = date.fromisoformat(cmd_val.split(":", 1)[1])
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            if not tour:
                await vk.send_message(user_id, "Экскурсия не найдена. Напишите start")
                return PlainTextResponse("ok", status_code=200)
            await send_day_details(vk, user_id, BookingCalendar(db, tour), selected)
            return PlainTextResponse("ok", status_code=200)

        if cmd_val.startswith("book:") and session.state == DialogState.SELECT_DATE:
            selected = date.fromisoformat(cmd_val.split(":", 1)[1])
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            if not tour or not await booking_service.is_available(tour, selected, 1):
                await vk.send_message(user_id, "Дата недоступна, выберите другую")
                return PlainTextResponse("ok", status_code=200)
            session.payload["date"] = selected.isoformat()
            session.state = DialogState.INPUT_NAME
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите ФИО")
            return PlainTextResponse("ok", status_code=200)

        if session.state == DialogState.SELECT_DATE:
            await vk.send_message(user_id, "Выберите дату в календаре")
            return PlainTextResponse("ok", status_code=200)
        elif session.state == DialogState.INPUT_NAME:
            session.payload["name"] = text
            session.state = DialogState.INPUT_PHONE
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите телефон")
            return PlainTextResponse("ok", status_code=200)
        elif session.state == DialogState.INPUT_PHONE:
            session.payload["phone"] = text
            session.state = DialogState.INPUT_PEOPLE_COUNT
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите количество человек")
            return PlainTextResponse("ok", status_code=200)
        elif session.state == DialogState.INPUT_PEOPLE_COUNT:
            people = int(text)
            session.payload["people_count"] = people
            session.state = DialogState.CONFIRM
            await storage.set(user_id, session)
            await vk.send_message(
                user_id,
                "Перед подтверждением примите согласие на обработку персональных данных.",
                keyboard=consent_keyboard(),
            )
            return PlainTextResponse("ok", status_code=200)
        elif session.state == DialogState.CONFIRM:
            consent_accepted = cmd_val == "consent:yes"
            if not consent_accepted:
                await vk.send_message(
                    user_id,
                    "Для бронирования нажмите кнопку согласия на обработку персональных данных.",
                    keyboard=consent_keyboard(),
                )
                return PlainTextResponse("ok", status_code=200)
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            booking_date = date.fromisoformat(session.payload["date"])
            if not tour or not await booking_service.is_available(
                tour,
                booking_date,
                int(session.payload["people_count"]),
            ):
                await vk.send_message(user_id, "Нет мест или дата заблокирована")
                await storage.clear(user_id)
                return PlainTextResponse("ok", status_code=200)
            booking = await booking_service.create_booking(
                vk_id=str(user_id),
                tour_id=tour.id,
                date=booking_date,
                name=session.payload["name"],
                phone=session.payload["phone"],
                people_count=int(session.payload["people_count"]),
                status="confirmed",
            )
            session.payload["user_id"] = booking.user_id
            await storage.set(user_id, session)
            pdfs = PDFService().generate_booking_documents(booking)
            await vk.send_message(user_id, "Бронирование подтверждено. Отправляю документы.")
            for path in pdfs.values():
                await vk.send_document(user_id, path)
            await notify_drivers(db, booking, pdfs)
            await storage.clear(user_id)
        else:
            await vk.send_message(user_id, "Напишите start")
    except Exception:
        logger.exception("Unhandled error in VK callback for user %s", user_id)
        try:
            await vk.send_message(user_id, "Ошибка. Напишите start")
        except Exception:
            logger.exception("Failed to send error message to user %s", user_id)

    return PlainTextResponse("ok", status_code=200)