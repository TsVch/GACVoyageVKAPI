"""VK Callback router — диалог бронирования экскурсий."""
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
from app.services.booking_calendar import BookingCalendar, format_date_ru
from app.services.booking_service import BookingService
from app.services.notification_service import notify_drivers
from app.services.pdf_service import PDFService
from app.services.vk_service import VKService

logger = logging.getLogger(__name__)
router = APIRouter()
storage = FSMStorage()

_OK = PlainTextResponse("ok", status_code=200)


# ─── Keyboard builders ────────────────────────────────────────────────────────

def tour_keyboard(tour_id: int) -> dict:
    return {
        "inline": True,
        "buttons": [[{
            "action": {
                "type": "text",
                "label": "Выбрать тур",
                "payload": json.dumps({"tour_id": tour_id}),
            },
            "color": "primary",
        }]],
    }


def main_menu_keyboard() -> dict:
    return {
        "inline": True,
        "buttons": [[{
            "action": {
                "type": "text",
                "label": "📋 Мои бронирования",
                "payload": json.dumps({"cmd": "my_bookings"}),
            },
            "color": "secondary",
        }]],
    }


def book_day_keyboard(iso_date: str) -> dict:
    """Inline-кнопка «Забронировать» под карточкой дня."""
    return {
        "inline": True,
        "buttons": [
            [{
                "action": {
                    "type": "text",
                    "label": "🎫 Забронировать",
                    "payload": json.dumps({"cmd": f"book:{iso_date}"}),
                },
                "color": "positive",
            }],
            [{
                "action": {
                    "type": "text",
                    "label": "← Выбрать другую дату",
                    "payload": json.dumps({"cmd": "back_to_calendar"}),
                },
                "color": "secondary",
            }],
        ],
    }


def no_places_keyboard() -> dict:
    """Кнопка возврата к календарю когда мест нет."""
    return {
        "inline": True,
        "buttons": [[{
            "action": {
                "type": "text",
                "label": "← Выбрать другую дату",
                "payload": json.dumps({"cmd": "back_to_calendar"}),
            },
            "color": "secondary",
        }]],
    }


def consent_keyboard() -> dict:
    """Inline-кнопки для согласия на обработку персональных данных."""
    return {
        "inline": True,
        "buttons": [
            [{
                "action": {
                    "type": "text",
                    "label": "✅ Принимаю",
                    "payload": json.dumps({"cmd": "consent_accept"}),
                },
                "color": "positive",
            }],
            [{
                "action": {
                    "type": "text",
                    "label": "❌ Отмена",
                    "payload": json.dumps({"cmd": "consent_decline"}),
                },
                "color": "negative",
            }],
        ],
    }


def clear_keyboard() -> dict:
    """Убирает клавиатуру (пустая one_time)."""
    return {"buttons": []}


# ─── Message formatters ──────────────────────────────────────────────────────

def format_day_card(
    tour_name: str,
    price: float,
    selected: date,
    total: int,
    booked: int,
    available: int,
    is_blocked: bool,
    status: str,
) -> str:
    """Карточка дня: показывает занятость и подсказку."""
    header = f"📅 {format_date_ru(selected)}\n🏝 {tour_name}\n💵 {price:,.0f} ₽ / чел.\n"

    if is_blocked:
        return header + "\n❌ Эта дата заблокирована.\nВыберите другую дату."

    status_icons = {
        "full": "🚫",
        "low": "🔴",
        "medium": "🟡",
        "high": "🟢",
    }
    icon = status_icons.get(status, "⚪")
    seats = (
        f"👥 Мест всего: {total}\n"
        f"{icon} Свободно: {available}\n"
        f"⛔ Занято: {booked}"
    )

    if available == 0:
        note = "\n\n❌ Мест нет. Выберите другую дату."
    elif available == 1:
        note = f"\n\n⚠️ Остался последний 1 из {total} мест!"
    elif available <= 3:
        note = f"\n\n🟡 Осталось {available} из {total} мест."
    else:
        note = f"\n\n🟢 Свободно {available} из {total} мест."

    return header + "\n" + seats + note


CONSENT_TEXT = (
    "📋 Согласие на обработку персональных данных\n\n"
    "Для оформления бронирования нам необходимо обработать ваши персональные данные "
    "(ФИО, номер телефона) в соответствии с Федеральным законом № 152-ФЗ "
    "«О персональных данных».\n\n"
    "Данные используются исключительно для организации экскурсии и не передаются "
    "третьим лицам.\n\n"
    "После подтверждения бронирования вам будет направлен договор фрахтования "
    "и подписанное согласие.\n\n"
    "Нажмите «✅ Принимаю» для продолжения."
)


def format_confirm_card(session_payload: dict, tour_name: str, price: float) -> str:
    selected = date.fromisoformat(session_payload["date"])
    people = int(session_payload["people_count"])
    total_price = price * people
    return (
        "📋 Проверьте данные бронирования:\n\n"
        f"🏝 Экскурсия: {tour_name}\n"
        f"📅 Дата: {format_date_ru(selected, with_weekday=True)}\n"
        f"👤 ФИО: {session_payload['name']}\n"
        f"📞 Телефон: {session_payload['phone']}\n"
        f"👥 Человек: {people}\n"
        f"💵 Итого: {total_price:,.0f} ₽\n\n"
        "Всё верно? Напишите «да» для подтверждения или «нет» для отмены."
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _show_calendar(
    vk: VKService,
    user_id: int,
    db: AsyncSession,
    booking_service: BookingService,
    tour_id: int,
    year: int,
    month: int,
) -> None:
    """Отправляет текстовый календарь + кнопки выбора даты."""
    tour = await booking_service.get_tour(tour_id)
    if not tour:
        await vk.send_message(user_id, "Тур не найден. Напишите start.")
        return
    cal = BookingCalendar(db, tour)
    text = BookingCalendar.build_month_text(year, month)
    keyboard = await cal.build_keyboard("user", year, month)
    await vk.send_message(user_id, text, keyboard=keyboard)


# ─── Main callback handler ────────────────────────────────────────────────────

@router.post("/vk/callback", response_class=PlainTextResponse)
async def vk_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    settings = get_settings()

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Invalid request body from %s", request.client)
        return _OK

    if payload.get("type") == "confirmation":
        return PlainTextResponse(settings.vk_confirmation_code, status_code=200)

    if payload.get("type") != "message_new":
        return _OK

    vk = VKService()
    msg = VKObjectMessage(**payload.get("object", {}).get("message", {}))
    user_id = msg.from_id
    text = msg.text.strip()
    session = await storage.get(user_id)
    booking_service = BookingService(db)

    try:
        # ── Команды запуска ──────────────────────────────────────────────────
        if text.lower() in {"start", "начать", "привет", "/start"}:
            await storage.clear(user_id)
            session = await storage.get(user_id)
            tours = await booking_service.list_tours()
            await vk.send_message(
                user_id,
                "👋 Привет! Выберите экскурсию для бронирования.",
                keyboard=main_menu_keyboard(),
            )
            for t in tours:
                media = "\n".join([f"Фото: {u}" for u in t.photo_urls[:3]])
                card = (
                    f"🏝 {t.name}\n"
                    f"{t.description}\n"
                    f"💵 {float(t.price):,.0f} ₽ / чел.\n"
                    f"⭐ {t.rating}\n"
                    + (f"📍 {t.meeting_point}\n" if t.meeting_point else "")
                    + (f"⏱ {t.duration}\n" if t.duration else "")
                    + (f"Альбом: {t.vk_album_url}\n" if t.vk_album_url else "")
                    + (f"Видео: {t.video_url}\n" if t.video_url else "")
                    + media
                )
                await vk.send_message(user_id, card, keyboard=tour_keyboard(t.id))
            return _OK

        # ── Обработка payload-кнопок ─────────────────────────────────────────
        if msg.payload:
            payload_data = json.loads(msg.payload)
            cmd = payload_data.get("cmd", "")

            # Мои бронирования
            if cmd == "my_bookings":
                internal_uid = session.payload.get("user_id")
                if not internal_uid:
                    user = await booking_service.get_user(vk_id=str(user_id))
                    if user:
                        internal_uid = user.id
                        session.payload["user_id"] = internal_uid
                        await storage.set(user_id, session)
                if not internal_uid:
                    await vk.send_message(user_id, "У вас пока нет бронирований.")
                    return _OK
                bookings = await booking_service.list_user_bookings(user_id=int(internal_uid))
                if not bookings:
                    await vk.send_message(user_id, "У вас пока нет бронирований.")
                    return _OK
                lines = [
                    f"#{b.id}: {b.tour.name if b.tour else '?'} — "
                    f"{format_date_ru(b.date, with_weekday=False)}, "
                    f"{b.people_count} чел., {b.status}"
                    for b in bookings
                ]
                await vk.send_message(user_id, "📋 Ваши бронирования:\n\n" + "\n".join(lines))
                return _OK

            # Выбор тура → показать календарь
            if payload_data.get("tour_id"):
                tour_id = int(payload_data["tour_id"])
                session.payload["tour_id"] = tour_id
                session.state = DialogState.SELECT_DATE
                await storage.set(user_id, session)
                now = datetime.utcnow()
                await _show_calendar(vk, user_id, db, booking_service, tour_id, now.year, now.month)
                return _OK

            # Навигация по месяцам ◀ / ▶
            if cmd.startswith("cal_nav:"):
                nav_ym = cmd.split(":", 1)[1]          # "2026-06"
                nav_year = int(nav_ym[:4])
                nav_month = int(nav_ym[5:7])
                tour_id = session.payload.get("tour_id")
                if tour_id:
                    await _show_calendar(
                        vk, user_id, db, booking_service,
                        int(tour_id), nav_year, nav_month,
                    )
                return _OK

            # Возврат к календарю из карточки дня
            if cmd == "back_to_calendar":
                tour_id = session.payload.get("tour_id")
                session.state = DialogState.SELECT_DATE
                await storage.set(user_id, session)
                if tour_id:
                    now = datetime.utcnow()
                    await _show_calendar(
                        vk, user_id, db, booking_service,
                        int(tour_id), now.year, now.month,
                    )
                return _OK

            # Нажатие «Забронировать» из карточки дня
            if cmd.startswith("book:") and session.state == DialogState.VIEW_DAY:
                iso_date = cmd.split(":", 1)[1]
                session.payload["date"] = iso_date
                session.state = DialogState.CONSENT
                await storage.set(user_id, session)
                await vk.send_message(user_id, CONSENT_TEXT, keyboard=consent_keyboard())
                return _OK

            # Согласие принято
            if cmd == "consent_accept" and session.state == DialogState.CONSENT:
                session.state = DialogState.INPUT_NAME
                await storage.set(user_id, session)
                await vk.send_message(
                    user_id,
                    "📝 Введите ваше ФИО (Фамилия Имя Отчество):",
                    keyboard=clear_keyboard(),
                )
                return _OK

            # Согласие отклонено / отмена
            if cmd in {"consent_decline"} or (
                cmd == "consent_decline" and session.state == DialogState.CONSENT
            ):
                await vk.send_message(user_id, "Бронирование отменено. Напишите start, чтобы начать заново.")
                await storage.clear(user_id)
                return _OK

        # ── Диалог по состояниям ─────────────────────────────────────────────

        # SELECT_DATE: ожидаем нажатие на дату
        if session.state == DialogState.SELECT_DATE:
            if not msg.payload:
                await vk.send_message(user_id, "Выберите дату из календаря выше.")
                return _OK
            payload_cmd = json.loads(msg.payload).get("cmd", "")
            if not payload_cmd.startswith("date:"):
                return _OK
            selected = date.fromisoformat(payload_cmd.split(":", 1)[1])
            tour_id = session.payload.get("tour_id")
            if not tour_id:
                await vk.send_message(user_id, "Напишите start.")
                return _OK

            tour = await booking_service.get_tour(int(tour_id))
            if not tour:
                await vk.send_message(user_id, "Тур не найден. Напишите start.")
                return _OK

            # Получаем данные дня (аналог /calendar/day)
            cal = BookingCalendar(db, tour)
            capacity = await cal.get_day_capacity(selected)

            card = format_day_card(
                tour_name=tour.name,
                price=float(tour.price),
                selected=selected,
                total=capacity.total_places,
                booked=capacity.booked_places,
                available=capacity.available_places,
                is_blocked=capacity.is_blocked,
                status=capacity.status,
            )
            session.state = DialogState.VIEW_DAY
            session.payload["date"] = selected.isoformat()
            await storage.set(user_id, session)

            if capacity.status in {"blocked", "full"}:
                await vk.send_message(user_id, card, keyboard=no_places_keyboard())
            else:
                await vk.send_message(user_id, card, keyboard=book_day_keyboard(selected.isoformat()))
            return _OK

        # VIEW_DAY: ждём нажатие кнопки (обрабатывается в payload-секции выше)
        if session.state == DialogState.VIEW_DAY:
            if msg.payload:
                return _OK  # обработано выше
            await vk.send_message(user_id, "Воспользуйтесь кнопками выше.")
            return _OK

        # CONSENT: ждём нажатие кнопки (обрабатывается в payload-секции выше)
        if session.state == DialogState.CONSENT:
            if msg.payload:
                return _OK  # обработано выше
            await vk.send_message(user_id, "Пожалуйста, нажмите кнопку «✅ Принимаю» или «❌ Отмена».")
            return _OK

        # INPUT_NAME
        if session.state == DialogState.INPUT_NAME:
            if not text:
                await vk.send_message(user_id, "Пожалуйста, введите ваше ФИО.")
                return _OK
            session.payload["name"] = text
            session.state = DialogState.INPUT_PHONE
            await storage.set(user_id, session)
            await vk.send_message(user_id, "📞 Введите номер телефона:")
            return _OK

        # INPUT_PHONE
        if session.state == DialogState.INPUT_PHONE:
            if not text:
                await vk.send_message(user_id, "Пожалуйста, введите номер телефона.")
                return _OK
            session.payload["phone"] = text
            session.state = DialogState.INPUT_PEOPLE_COUNT
            await storage.set(user_id, session)
            tour_id = session.payload.get("tour_id")
            tour = await booking_service.get_tour(int(tour_id)) if tour_id else None
            max_p = tour.max_people_per_day if tour else 6
            await vk.send_message(user_id, f"👥 Введите количество человек (максимум {max_p}):")
            return _OK

        # INPUT_PEOPLE_COUNT
        if session.state == DialogState.INPUT_PEOPLE_COUNT:
            try:
                people = int(text)
                if people < 1:
                    raise ValueError
            except ValueError:
                await vk.send_message(user_id, "Введите целое число от 1 и выше.")
                return _OK
            tour_id = session.payload.get("tour_id")
            tour = await booking_service.get_tour(int(tour_id)) if tour_id else None
            selected = date.fromisoformat(session.payload["date"])
            if tour:
                cal = BookingCalendar(db, tour)
                capacity = await cal.get_day_capacity(selected)
                if people > capacity.available_places:
                    await vk.send_message(
                        user_id,
                        f"❌ Свободно только {capacity.available_places} мест.\n"
                        f"Введите число от 1 до {capacity.available_places}:",
                    )
                    return _OK

            session.payload["people_count"] = people
            session.state = DialogState.CONFIRM
            await storage.set(user_id, session)

            confirm_text = format_confirm_card(
                session.payload, tour.name if tour else "Экскурсия", float(tour.price) if tour else 0
            )
            await vk.send_message(user_id, confirm_text)
            return _OK

        # CONFIRM
        if session.state == DialogState.CONFIRM:
            if text.lower() in {"нет", "no", "n", "отмена"}:
                await vk.send_message(user_id, "❌ Бронирование отменено. Напишите start для нового.")
                await storage.clear(user_id)
                return _OK
            if text.lower() not in {"да", "yes", "y"}:
                await vk.send_message(user_id, "Напишите «да» для подтверждения или «нет» для отмены.")
                return _OK

            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            booking_date = date.fromisoformat(session.payload["date"])
            people = int(session.payload["people_count"])

            booking = await booking_service.create_booking(
                vk_id=str(user_id),
                tour_id=tour.id,
                date=booking_date,
                name=session.payload["name"],
                phone=session.payload["phone"],
                people_count=people,
                status="confirmed",
            )
            session.payload["user_id"] = booking.user_id
            await storage.set(user_id, session)

            # Генерация документов
            await vk.send_message(user_id, "✅ Бронирование подтверждено!\n\nГотовим документы…")
            pdf_service = PDFService()
            pdfs = pdf_service.generate_booking_documents(booking)

            # Отправка клиенту
            await vk.send_message(
                user_id,
                f"📄 Ваши документы по бронированию #{booking.id}:",
            )
            await vk.send_document(user_id, pdfs["contract"], title=f"Договор фрахтования #{booking.id}")
            await vk.send_document(user_id, pdfs["consent"], title=f"Согласие на обработку ПД #{booking.id}")

            # Итоговое сообщение клиенту
            await vk.send_message(
                user_id,
                f"🎉 Всё готово! Ждём вас {format_date_ru(booking_date)}.\n"
                f"Если есть вопросы — напишите нам.\n\n"
                f"Номер бронирования: #{booking.id}",
                keyboard=main_menu_keyboard(),
            )

            # Уведомление водителей + документы им тоже
            await notify_drivers(db, booking, pdfs)
            await storage.clear(user_id)
            return _OK

        # Неизвестное состояние / начало без команды
        await vk.send_message(
            user_id,
            "Напишите «start» чтобы начать бронирование 👋",
        )

    except Exception:
        logger.exception("Unhandled error in VK callback for user_id=%s", user_id)
        try:
            await vk.send_message(user_id, "⚠️ Произошла ошибка. Напишите start для нового сеанса.")
        except Exception:
            logger.exception("Failed to send error message to user_id=%s", user_id)

    return _OK