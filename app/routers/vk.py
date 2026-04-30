import json
from datetime import date, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.fsm.states import DialogState
from app.fsm.storage import FSMStorage
from app.schemas.vk import VKCallbackEvent, VKObjectMessage
from app.services.booking_service import BookingService
from app.services.booking_calendar import BookingCalendar
from app.services.notification_service import notify_drivers
from app.services.pdf_service import PDFService
from app.services.vk_service import VKService

router = APIRouter()
storage = FSMStorage()


def tour_keyboard(tour_id: int) -> dict:
    return {"inline": True, "buttons": [[{"action": {"type": "text", "label": "Select tour", "payload": json.dumps({"tour_id": tour_id})}, "color": "primary"}]]}


@router.post("/vk", response_class=PlainTextResponse)
async def vk_callback(payload: VKCallbackEvent, db: AsyncSession = Depends(get_db)) -> str:
    settings = get_settings()
    vk = VKService()
    if payload.type == "confirmation":
        return settings.vk_confirmation_code
    if payload.type != "message_new":
        return "ok"

    msg = VKObjectMessage(**payload.object.get("message", {}))
    user_id = msg.from_id
    text = msg.text.strip()
    session = await storage.get(user_id)
    booking_service = BookingService(db)

    try:
        if text.lower() in {"start", "начать", "привет"}:
            tours = await booking_service.list_tours()
            for t in tours:
                media = "\n".join([f"Фото: {u}" for u in t.photo_urls[:3]])
                card = f"🏝 {t.name}\n{t.description}\n💵 {t.price} ₽\n⭐ {t.rating}\nАльбом: {t.vk_album_url or '-'}\nВидео: {t.video_url or '-'}\n{media}"
                await vk.send_message(user_id, card, keyboard=tour_keyboard(t.id))
            session.state = DialogState.SELECT_DATE
            await storage.set(user_id, session)
            return "ok"

        if msg.payload:
            payload_data = json.loads(msg.payload)
            if payload_data.get("tour_id"):
                session.payload["tour_id"] = int(payload_data["tour_id"])
                session.state = DialogState.SELECT_DATE
                await storage.set(user_id, session)
                tour = await booking_service.get_tour(int(session.payload["tour_id"]))
                if tour:
                    cal = BookingCalendar(db, tour)
                    now = datetime.utcnow()
                    legend = "🟢 4–6 places available\n🟡 2–3 places available\n🔴 1 place left\n🚫 no places\n❌ blocked\n⚪ unavailable"
                    await vk.send_message(user_id, legend)
                    await vk.send_message(user_id, "Выберите дату", keyboard=await cal.build_keyboard("user", now.year, now.month))
                return "ok"

        if session.state == DialogState.SELECT_DATE:
            if not msg.payload:
                await vk.send_message(user_id, "Выберите дату в календаре")
                return "ok"
            selected = date.fromisoformat(json.loads(msg.payload)["cmd"].split(":",1)[1])
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            if not tour or not await booking_service.is_available(tour, selected, 1):
                await vk.send_message(user_id, "Дата недоступна, выберите другую")
                return "ok"
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
                return "ok"
            tour = await booking_service.get_tour(int(session.payload["tour_id"]))
            booking_date = date.fromisoformat(session.payload["date"])
            if not tour or not await booking_service.is_available(tour, booking_date, int(session.payload["people_count"])):
                await vk.send_message(user_id, "Нет мест или дата заблокирована")
                await storage.clear(user_id)
                return "ok"
            booking = await booking_service.create_booking(user_id=user_id, tour_id=tour.id, date=booking_date, name=session.payload["name"], phone=session.payload["phone"], people_count=int(session.payload["people_count"]), status="confirmed")
            pdfs = PDFService().generate_booking_documents(booking)
            await vk.send_message(user_id, "Бронирование подтверждено")
            await notify_drivers(db, booking, pdfs)
            await storage.clear(user_id)
        else:
            await vk.send_message(user_id, "Напишите start")
    except Exception:
        await vk.send_message(user_id, "Ошибка. Напишите start")
    return "ok"
