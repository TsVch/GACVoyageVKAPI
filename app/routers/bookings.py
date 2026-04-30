from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.booking import BookingCreate
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/create")
async def create_booking(payload: BookingCreate, db: AsyncSession = Depends(get_db)) -> dict:
    service = BookingService(db)
    try:
        booking = await service.create_booking(**payload.model_dump(), status="confirmed")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"booking_id": booking.id, "status": booking.status}
