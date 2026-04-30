import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_day import CalendarDay
from app.models.tour import Tour


@dataclass
class DayStatus:
    emoji: str
    free_places: int


class BookingCalendar:
    def __init__(self, db: AsyncSession, tour: Tour) -> None:
        self.db = db
        self.tour = tour

    async def _get_or_create_day(self, day: date) -> CalendarDay:
        q = await self.db.execute(select(CalendarDay).where(CalendarDay.tour_id == self.tour.id, CalendarDay.date == day))
        row = q.scalar_one_or_none()
        if row:
            return row
        row = CalendarDay(tour_id=self.tour.id, date=day, booked_people_count=0, max_people=self.tour.max_people_per_day, is_blocked=False)
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_month_data(self, tour_id: int, year: int, month: int) -> dict:
        first = date(year, month, 1)
        _, days_in_month = calendar.monthrange(year, month)
        q = await self.db.execute(select(CalendarDay).where(CalendarDay.tour_id == tour_id, CalendarDay.date >= first, CalendarDay.date <= date(year, month, days_in_month)))
        items = {x.date: x for x in q.scalars().all()}
        return {"year": year, "month": month, "days": items}

    def get_day_status(self, day: date, row: CalendarDay | None) -> DayStatus:
        if day < date.today():
            return DayStatus("⚪", 0)
        if row and row.is_blocked:
            return DayStatus("❌", 0)
        max_people = row.max_people if row else self.tour.max_people_per_day
        booked = row.booked_people_count if row else 0
        free = max(0, max_people - booked)
        if free == 0:
            return DayStatus("🚫", free)
        if free == 1:
            return DayStatus("🔴", free)
        if 2 <= free <= 3:
            return DayStatus("🟡", free)
        return DayStatus("🟢", free)

    async def is_available(self, day: date, people_count: int) -> bool:
        row = await self._get_or_create_day(day)
        st = self.get_day_status(day, row)
        return (not row.is_blocked) and st.free_places >= people_count

    async def block_date(self, day: date) -> None:
        row = await self._get_or_create_day(day); row.is_blocked = True; await self.db.commit()

    async def unblock_date(self, day: date) -> None:
        row = await self._get_or_create_day(day); row.is_blocked = False; await self.db.commit()

    async def increment_booking(self, day: date, people_count: int) -> None:
        row = await self._get_or_create_day(day)
        await self.db.refresh(row, with_for_update=True)
        if row.is_blocked or row.booked_people_count + people_count > row.max_people:
            raise ValueError("No availability")
        row.booked_people_count += people_count
        await self.db.commit()

    async def build_keyboard(self, mode: str, year: int, month: int) -> dict:
        data = await self.get_month_data(self.tour.id, year, month)
        cal = calendar.Calendar(firstweekday=0)
        buttons = []
        for week in cal.monthdatescalendar(year, month):
            row = []
            for d in week:
                if d.month != month:
                    row.append({"action": {"type": "text", "label": " ", "payload": "{}"}, "color": "secondary"})
                    continue
                st = self.get_day_status(d, data["days"].get(d))
                payload = {"cmd": f"{'admin_date' if mode == 'admin' else 'date'}:{d.isoformat()}"}
                row.append({"action": {"type": "text", "label": f"{d.day}{st.emoji}", "payload": __import__('json').dumps(payload)}, "color": "secondary"})
            buttons.append(row)
        return {"inline": True, "buttons": buttons}
