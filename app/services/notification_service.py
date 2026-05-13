import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.driver import Driver
from app.services.vk_service import VKService


async def notify_drivers(
    db: AsyncSession,
    booking: Booking,
    pdf_links: dict[str, str]
) -> None:
    vk = VKService()

    drivers = (
        await db.execute(
            select(Driver).where(Driver.is_active.is_(True))
        )
    ).scalars().all()

    async def _notify(driver: Driver) -> None:
        text = (
            f"Новая бронь: {booking.tour.name}\n"
            f"Дата: {booking.date}\n"
            f"Клиент: {booking.name}\n"
            f"Тел: {booking.phone}\n"
            f"Людей: {booking.people_count}\n\n"
            f"Документы:\n"
            f"Договор: {pdf_links['contract']}\n"
            f"Согласие: {pdf_links['consent']}"
        )

        await vk.send_message(driver.vk_user_id, text)

    await asyncio.gather(*[_notify(driver) for driver in drivers])