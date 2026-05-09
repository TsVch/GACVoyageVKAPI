import json
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

router = APIRouter()
storage = FSMStorage()


def tour_keyboard(tour_id: int) -> dict:
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "Select tour",
                        "payload": json.dumps({"tour_id": tour_id}),
                    },
                    "color": "primary",
                }
            ]
        ],
    }


def main_menu_keyboard() -> dict:
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "Мои бронирования",
                        "payload": json.dumps({"cmd": "my_bookings"}),
                    },
                    "color": "secondary",
                }
            ]
        ],
    }


@router.post("/vk/callback", response_class=PlainTextResponse)
async def vk_callback(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    settings = get_settings()
    payload = await request.json()

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

        if msg.payload:
            payload_data = json.loads(msg.payload)
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
                        "🟢 4–6 places available\n🟡 2–3 places available\n🔴 1 place left\n"
                        "🚫 no places\n❌ blocked\n⚪ unavailable"
                    )
                    await vk.send_message(user_id, legend)
                    await vk.send_message(
                        user_id,
                        "Выберите дату",
                        keyboard=await cal.build_keyboard("user", now.year, now.month),
                    )
                return PlainTextResponse("ok", status_code=200)

        if session.state == DialogState.SELECT_DATE:
            if not msg.payload:
                await vk.send_message(user_id, "Выберите дату в календаре")
                return PlainTextResponse("ok", status_code=200)
            selected = date.fromisoformat(json.loads(msg.payload)["cmd"].split(":", 1)[1])
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            if not tour or not await booking_service.is_available(tour, selected, 1):
                await vk.send_message(user_id, "Дата недоступна, выберите другую")
                return PlainTextResponse("ok", status_code=200)
            session.payload["date"] = selected.isoformat()
            session.state = DialogState.INPUT_NAME
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите ФИО")
        elif session.state == DialogState.INPUT_NAME:
            session.payload["name"] = text
            session.state = DialogState.INPUT_PHONE
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите телефон")
        elif session.state == DialogState.INPUT_PHONE:
            session.payload["phone"] = text
            session.state = DialogState.INPUT_PEOPLE_COUNT
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Введите количество человек")
        elif session.state == DialogState.INPUT_PEOPLE_COUNT:
            people = int(text)
            session.payload["people_count"] = people
            session.state = DialogState.CONFIRM
            await storage.set(user_id, session)
            await vk.send_message(user_id, "Подтвердите бронирование: да/нет")
        elif session.state == DialogState.CONFIRM:
            if text.lower() not in {"да", "yes", "y"}:
                await vk.send_message(user_id, "Отменено")
                await storage.clear(user_id)
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
            await vk.send_message(user_id, "Бронирование подтверждено")
            await notify_drivers(db, booking, pdfs)
            await storage.clear(user_id)
        else:
            await vk.send_message(user_id, "Напишите start")
    except Exception:
        await vk.send_message(user_id, "Ошибка. Напишите start")

    return PlainTextResponse("ok", status_code=200)