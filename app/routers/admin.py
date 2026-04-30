from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.tour import Tour
from app.schemas.admin import BlockDatePayload, TourCreate
from app.services.booking_calendar import BookingCalendar

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/tours")
async def create_tour(payload: TourCreate, db: AsyncSession = Depends(get_db)) -> dict:
    tour = Tour(**payload.model_dump())
    db.add(tour)
    await db.commit()
    await db.refresh(tour)
    return {"id": tour.id, "name": tour.name}


@router.post("/block-date")
async def block_date(payload: BlockDatePayload, db: AsyncSession = Depends(get_db)) -> dict:
    tour = await db.get(Tour, payload.tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    await BookingCalendar(db, tour).block_date(payload.date)
    return {"status": "blocked"}


@router.delete("/block-date")
async def unblock_date(payload: BlockDatePayload, db: AsyncSession = Depends(get_db)) -> dict:
    tour = await db.get(Tour, payload.tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    await BookingCalendar(db, tour).unblock_date(payload.date)
    return {"status": "unblocked"}


@router.get("/calendar")
async def admin_calendar(tour_id: int = Query(...), year: int = Query(...), month: int = Query(...), db: AsyncSession = Depends(get_db)) -> dict:
    tour = await db.get(Tour, tour_id)
    if not tour:
        raise HTTPException(404, "Tour not found")
    kb = await BookingCalendar(db, tour).build_keyboard("admin", year, month)
    return {"legend": "🟢4-6 🟡2-3 🔴1 🚫0 ❌blocked ⚪na", "keyboard": kb}
