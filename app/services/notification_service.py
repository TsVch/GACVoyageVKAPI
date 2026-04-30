import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.driver import Driver
from app.services.vk_service import VKService


async def notify_drivers(db: AsyncSession, booking: Booking, pdf_paths: dict[str, str]) -> None:
    vk = VKService()
    drivers = (await db.execute(select(Driver).where(Driver.is_active.is_(True)))).scalars().all()

    async def _notify(driver: Driver) -> None:
        text = f"Новая бронь: {booking.tour.name}\nДата: {booking.date}\nКлиент: {booking.name}\nТел: {booking.phone}\nЛюдей: {booking.people_count}"
        await vk.send_message(driver.vk_user_id, text)
        await asyncio.gather(*[vk.send_document(driver.vk_user_id, p) for p in pdf_paths.values()])

    await asyncio.gather(*[_notify(driver) for driver in drivers])
