import calendar
import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.calendar_day import CalendarDay
from app.models.tour import Tour

logger = logging.getLogger(__name__)

# ─── Русские названия ───────────────────────────────────────────────────────
_MONTH_NOM = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
_MONTH_GEN = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
_WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_WEEKDAY_FULL = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]


def month_name(month: int, genitive: bool = False) -> str:
    return _MONTH_GEN[month] if genitive else _MONTH_NOM[month]


def weekday_name(wd: int, full: bool = False) -> str:
    """wd=0 → Пн/Понедельник, wd=6 → Вс/Воскресенье."""
    return _WEEKDAY_FULL[wd] if full else _WEEKDAY_SHORT[wd]


def format_date_ru(d: date, with_weekday: bool = True) -> str:
    """Например: '13 мая 2026, Среда'."""
    base = f"{d.day} {_MONTH_GEN[d.month]} {d.year}"
    if with_weekday:
        wd = _WEEKDAY_FULL[d.weekday()]
        return f"{base}, {wd}"
    return base


# ─── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class DayStatus:
    emoji: str
    free_places: int


@dataclass
class DayCapacity:
    total_places: int
    booked_places: int
    available_places: int
    is_blocked: bool
    status: str


# ─── BookingCalendar ─────────────────────────────────────────────────────────

class BookingCalendar:
    def __init__(self, db: AsyncSession, tour: Tour) -> None:
        self.db = db
        self.tour = tour

    # ── internal helpers ────────────────────────────────────────────────────

    async def _get_or_create_day(self, day: date) -> CalendarDay:
        q = await self.db.execute(
            select(CalendarDay).where(
                CalendarDay.tour_id == self.tour.id,
                CalendarDay.date == day,
            )
        )
        row = q.scalar_one_or_none()
        if row:
            return row
        row = CalendarDay(
            tour_id=self.tour.id,
            date=day,
            booked_people_count=0,
            max_people=self.tour.max_people_per_day,
            is_blocked=False,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    # ── public data methods ─────────────────────────────────────────────────

    async def get_month_data(self, tour_id: int, year: int, month: int) -> dict:
        first = date(year, month, 1)
        _, days_in_month = calendar.monthrange(year, month)
        q = await self.db.execute(
            select(CalendarDay).where(
                CalendarDay.tour_id == tour_id,
                CalendarDay.date >= first,
                CalendarDay.date <= date(year, month, days_in_month),
            )
        )
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

    def _api_status(self, day: date, row: CalendarDay) -> str:
        if row.is_blocked:
            return "blocked"
        available = max(0, row.max_people - row.booked_people_count)
        if available == 0:
            return "full"
        if available == 1:
            return "low"
        if available in {2, 3}:
            return "medium"
        return "high"

    async def get_day_capacity(self, day: date) -> DayCapacity:
        row = await self._get_or_create_day(day)
        available = max(0, row.max_people - row.booked_people_count)
        return DayCapacity(
            total_places=row.max_people,
            booked_places=row.booked_people_count,
            available_places=available,
            is_blocked=row.is_blocked,
            status=self._api_status(day, row),
        )

    async def is_available(self, day: date, people_count: int) -> bool:
        capacity = await self.get_day_capacity(day)
        return (not capacity.is_blocked) and capacity.available_places >= people_count

    # ── booking operations ──────────────────────────────────────────────────

    async def cancel_bookings_for_day(self, day: date, commit: bool = True) -> int:
        result = await self.db.execute(
            update(Booking)
            .where(
                Booking.tour_id == self.tour.id,
                Booking.date == day,
                Booking.status != "canceled",
            )
            .values(status="canceled")
        )
        canceled_count = result.rowcount or 0
        if commit:
            await self.db.commit()
        if canceled_count:
            logger.info(
                "Canceled %s bookings for tour_id=%s date=%s",
                canceled_count, self.tour.id, day,
            )
        return canceled_count

    async def block_date(self, day: date) -> int:
        row = await self._get_or_create_day(day)
        row.is_blocked = True
        canceled_count = await self.cancel_bookings_for_day(day, commit=False)
        if canceled_count:
            row.booked_people_count = 0
        await self.db.commit()
        return canceled_count

    async def unblock_date(self, day: date) -> None:
        row = await self._get_or_create_day(day)
        row.is_blocked = False
        await self.db.commit()

    async def increment_booking(
        self, day: date, people_count: int, commit: bool = True
    ) -> None:
        q = await self.db.execute(
            select(CalendarDay)
            .where(CalendarDay.tour_id == self.tour.id, CalendarDay.date == day)
            .with_for_update()
        )
        row = q.scalar_one_or_none()
        if not row:
            row = CalendarDay(
                tour_id=self.tour.id,
                date=day,
                booked_people_count=0,
                max_people=self.tour.max_people_per_day,
                is_blocked=False,
            )
            self.db.add(row)
            await self.db.flush()
        if row.is_blocked or row.booked_people_count + people_count > row.max_people:
            raise ValueError("No availability")
        row.booked_people_count += people_count
        if row.booked_people_count >= row.max_people:
            logger.info(
                "Calendar day reached full capacity for tour_id=%s date=%s",
                self.tour.id, day,
            )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def decrement_booking(
        self, day: date, people_count: int, commit: bool = True
    ) -> None:
        q = await self.db.execute(
            select(CalendarDay)
            .where(CalendarDay.tour_id == self.tour.id, CalendarDay.date == day)
            .with_for_update()
        )
        row = q.scalar_one_or_none()
        if not row:
            return
        row.booked_people_count = max(0, row.booked_people_count - people_count)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    # ── calendar text & keyboard ─────────────────────────────────────────────


    async def build_keyboard(self, mode: str, year: int, month: int) -> dict:
        """
        Строит VK-клавиатуру (one_time) для выбора даты.

        Ограничения VK:
        • inline-клавиатура: макс. 6 строк, 5 кнопок в строке
        • обычная (one_time): макс. 10 строк, 5 кнопок в строке

        Структура:
        • Строка 0: ◀  «Месяц YYYY»  ▶  (навигация)
        • Строки 1-7: числа месяца по 5 в строке
        Итого для 31-дневного месяца: 1 + 7 = 8 строк — укладывается.
        """
        data = await self.get_month_data(self.tour.id, year, month)
        date_cmd = "admin_date" if mode == "admin" else "date"

        prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
        next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)

        nav_row = [
            {
                "action": {
                    "type": "text",
                    "label": "◀",
                    "payload": json.dumps({"cmd": f"cal_nav:{prev_year}-{prev_month:02d}"}),
                },
                "color": "secondary",
            },
            {
                "action": {
                    "type": "text",
                    "label": f"{_MONTH_NOM[month]} {year}",
                    "payload": "{}",
                },
                "color": "secondary",
            },
            {
                "action": {
                    "type": "text",
                    "label": "▶",
                    "payload": json.dumps({"cmd": f"cal_nav:{next_year}-{next_month:02d}"}),
                },
                "color": "secondary",
            },
        ]

        _, days_in_month = calendar.monthrange(year, month)
        day_buttons: list[dict] = []

        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            st = self.get_day_status(d, data["days"].get(d))

            if d < date.today():
                btn = {
                    "action": {"type": "text", "label": f"{day_num}⚪", "payload": "{}"},
                    "color": "secondary",
                }
            else:
                btn = {
                    "action": {
                        "type": "text",
                        "label": f"{day_num}{st.emoji}",
                        "payload": json.dumps({"cmd": f"{date_cmd}:{d.isoformat()}"}),
                    },
                    "color": "secondary",
                }
            day_buttons.append(btn)

        CHUNK = 5
        day_rows = [day_buttons[i: i + CHUNK] for i in range(0, len(day_buttons), CHUNK)]
        buttons = [nav_row] + day_rows
        # one_time = клавиатура исчезает после нажатия (не inline, лимит 10 строк)
        return {"one_time": True, "buttons": buttons}
