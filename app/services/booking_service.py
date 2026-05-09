import logging
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.tour import Tour
from app.models.user import User
from app.services.booking_calendar import BookingCalendar

logger = logging.getLogger(__name__)


class BookingUnavailableError(ValueError):
    def __init__(self, reason: str, message: str, available_places: int | None = None) -> None:
        self.reason = reason
        self.available_places = available_places
        super().__init__(message)


class BookingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_tours(self) -> list[Tour]:
        return list((await self.db.execute(select(Tour).order_by(Tour.id))).scalars().all())

    async def get_tour(self, tour_id: int) -> Tour | None:
        return await self.db.get(Tour, tour_id)

    async def is_available(self, tour: Tour, booking_date: date, people_count: int) -> bool:
        return await BookingCalendar(self.db, tour).is_available(booking_date, people_count)

    async def _get_or_create_user(self, name: str, phone: str, vk_id: str | None) -> User:
        if vk_id is not None:
            query = select(User).where(User.vk_id == vk_id)
        else:
            query = select(User).where(and_(User.name == name, User.phone == phone))

        user = (await self.db.execute(query)).scalars().first()
        if user:
            if vk_id is not None:
                if not user.name and name:
                    user.name = name
                if not user.phone and phone:
                    user.phone = phone
            await self.db.flush()
            return user

        user = User(name=name, phone=phone, vk_id=vk_id)
        self.db.add(user)
        await self.db.flush()
        return user

    async def get_user(self, user_id: int | None = None, vk_id: str | None = None) -> User | None:
        if user_id is not None:
            return await self.db.get(User, user_id)
        if vk_id is not None:
            return (await self.db.execute(select(User).where(User.vk_id == vk_id))).scalars().first()
        return None

    async def create_booking(self, **kwargs) -> Booking:
        tour = await self.get_tour(kwargs["tour_id"])
        if not tour:
            raise ValueError("tour not found")

        calendar = BookingCalendar(self.db, tour)
        capacity = await calendar.get_day_capacity(kwargs["date"])
        if capacity.is_blocked:
            raise BookingUnavailableError("blocked", "Дата заблокирована для бронирования")
        if capacity.available_places < kwargs["people_count"]:
            raise BookingUnavailableError("capacity", "Недостаточно свободных мест", capacity.available_places)

        user = await self._get_or_create_user(kwargs["name"], kwargs["phone"], kwargs.get("vk_id"))
        try:
            await calendar.increment_booking(kwargs["date"], kwargs["people_count"], commit=False)
        except ValueError as exc:
            capacity = await calendar.get_day_capacity(kwargs["date"])
            if capacity.is_blocked:
                raise BookingUnavailableError("blocked", "Дата заблокирована для бронирования") from exc
            raise BookingUnavailableError("capacity", "Недостаточно свободных мест", capacity.available_places) from exc

        booking = Booking(
            user_id=user.id,
            tour_id=kwargs["tour_id"],
            date=kwargs["date"],
            name=kwargs["name"],
            phone=kwargs["phone"],
            people_count=kwargs["people_count"],
            status=kwargs.get("status", "confirmed"),
        )
        self.db.add(booking)
        await self.db.commit()
        await self.db.refresh(booking, attribute_names=["tour", "user"])
        logger.info("Created booking_id=%s user_id=%s tour_id=%s date=%s", booking.id, user.id, tour.id, booking.date)
        return booking

    async def list_user_bookings(self, user_id: int) -> list[Booking]:
        rows = await self.db.execute(select(Booking).where(Booking.user_id == user_id).order_by(Booking.created_at.desc()))
        return list(rows.scalars().all())

    async def cancel_booking(self, booking_id: int, user_id: int | None = None) -> tuple[Booking, int]:
        booking = await self.db.get(Booking, booking_id)
        if not booking:
            raise ValueError("booking not found")

        if user_id is not None and booking.user_id != user_id:
            raise PermissionError("booking does not belong to user")

        if booking.status == "canceled":
            return booking, 0

        tour = await self.get_tour(booking.tour_id)
        if not tour:
            raise ValueError("tour not found")
        booking.status = "canceled"
        await BookingCalendar(self.db, tour).decrement_booking(booking.date, booking.people_count, commit=False)
        await self.db.commit()
        await self.db.refresh(booking, attribute_names=["tour", "user"])
        logger.info("Canceled booking_id=%s user_id=%s tour_id=%s date=%s", booking.id, booking.user_id, booking.tour_id, booking.date)
        return booking, booking.people_count