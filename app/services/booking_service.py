from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.tour import Tour
from app.services.booking_calendar import BookingCalendar


class BookingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_tours(self) -> list[Tour]:
        return list((await self.db.execute(select(Tour).order_by(Tour.id))).scalars().all())

    async def get_tour(self, tour_id: int) -> Tour | None:
        return await self.db.get(Tour, tour_id)

    async def is_available(self, tour: Tour, booking_date: date, people_count: int) -> bool:
        return await BookingCalendar(self.db, tour).is_available(booking_date, people_count)

    async def create_booking(self, **kwargs) -> Booking:
        tour = await self.get_tour(kwargs["tour_id"])
        if not tour:
            raise ValueError("tour not found")
        calendar = BookingCalendar(self.db, tour)
        if not await calendar.is_available(kwargs["date"], kwargs["people_count"]):
            raise ValueError("No availability")
        await calendar.increment_booking(kwargs["date"], kwargs["people_count"])
        booking = Booking(**kwargs)
        self.db.add(booking)
        await self.db.commit()
        await self.db.refresh(booking, attribute_names=["tour"])
        return booking
