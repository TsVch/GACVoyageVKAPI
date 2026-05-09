from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.calendar_day import CalendarDay
from app.models.tour import Tour
from app.services.booking_calendar import BookingCalendar

router = APIRouter(tags=["public"])

CALENDAR_LEGEND = "🟢4-6 🟡2-3 🔴1 🚫0 ❌blocked ⚪na"


@router.get("/tours")
async def list_tours(db: AsyncSession = Depends(get_db)) -> list[dict]:
    tours = (await db.execute(select(Tour).order_by(Tour.id))).scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "price": float(t.price),
            "start_time": t.start_time,
            "meeting_point": t.meeting_point,
            "duration": t.duration,
        }
        for t in tours
    ]


@router.get("/calendar/month")
async def get_calendar_month(
    tour_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    mode: str = Query("user"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tour = await db.get(Tour, tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    keyboard_mode = "admin" if mode == "admin" else "user"
    keyboard = await BookingCalendar(db, tour).build_keyboard(keyboard_mode, year, month)
    return {"legend": CALENDAR_LEGEND, "keyboard": keyboard}


@router.get("/calendar/day")
async def get_calendar_day(tour_id: int, date: date, db: AsyncSession = Depends(get_db)) -> dict:
    tour = await db.get(Tour, tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    capacity = await BookingCalendar(db, tour).get_day_capacity(date)
    if capacity.status == "blocked":
        message = "Дата заблокирована для бронирования"
    elif capacity.status == "full":
        message = "Мест нет"
    else:
        message = f"Свободно {capacity.available_places} из {capacity.total_places} мест. Хотите забронировать?"

    actions = []
    if capacity.status not in {"blocked", "full"}:
        actions.append({"label": "Забронировать", "payload": f"book:{date.isoformat()}"})

    return {
        "date": date,
        "total_places": capacity.total_places,
        "booked_places": capacity.booked_places,
        "available_places": capacity.available_places,
        "is_blocked": capacity.is_blocked,
        "status": capacity.status,
        "message": message,
        "actions": actions,
    }


@router.get("/calendar/{tour_id}", deprecated=True)
async def get_calendar(tour_id: int, db: AsyncSession = Depends(get_db), from_date: date | None = Query(None), days: int = Query(30)) -> list[dict]:
    tour = await db.get(Tour, tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    cal = BookingCalendar(db, tour)
    start = from_date or date.today()
    rows = (
        await db.execute(
            select(CalendarDay)
            .where(CalendarDay.tour_id == tour_id, CalendarDay.date >= start)
            .order_by(CalendarDay.date)
            .limit(days)
        )
    ).scalars().all()
    out = []
    for row in rows:
        st = cal.get_day_status(row.date, row).emoji
        map_status = {"🟢": "green", "🟡": "yellow", "🔴": "red", "🚫": "full", "❌": "blocked", "⚪": "none"}
        out.append(
            {
                "date": row.date,
                "available_places": max(0, row.max_people - row.booked_people_count),
                "is_blocked": row.is_blocked,
                "status": map_status.get(st, "none"),
            }
        )
    return out