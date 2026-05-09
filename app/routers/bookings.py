from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.booking import BookingCancelOut, BookingCreate, MyBookingOut
from app.services.booking_service import BookingService, BookingUnavailableError

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _booking_payload(booking) -> MyBookingOut:
    return MyBookingOut(
        booking_id=booking.id,
        tour_name=booking.tour.name if booking.tour else "",
        date=booking.date,
        people_count=booking.people_count,
        status=booking.status,
    )


def _unavailable_response(exc: BookingUnavailableError) -> JSONResponse:
    content = {"success": False, "reason": exc.reason, "message": str(exc)}
    if exc.reason == "capacity":
        content["available_places"] = exc.available_places or 0
    return JSONResponse(status_code=409, content=content)


@router.post("/create")
async def create_booking(payload: BookingCreate, db: AsyncSession = Depends(get_db)) -> dict:
    service = BookingService(db)
    try:
        booking = await service.create_booking(**payload.model_dump(), status="confirmed")
    except BookingUnavailableError as exc:
        return _unavailable_response(exc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"booking_id": booking.id, "status": booking.status, "user_id": booking.user_id}


@router.get("/my", response_model=list[MyBookingOut])
async def my_bookings(user_id: int = Query(...), db: AsyncSession = Depends(get_db)) -> list[MyBookingOut]:
    bookings = await BookingService(db).list_user_bookings(user_id=user_id)
    return [_booking_payload(booking) for booking in bookings]


@router.patch("/{booking_id}/cancel", response_model=BookingCancelOut)
async def cancel_booking(
    booking_id: int,
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BookingCancelOut:
    try:
        booking, released_places = await BookingService(db).cancel_booking(booking_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return BookingCancelOut(booking_id=booking.id, status=booking.status, released_places=released_places)


@router.post("/{booking_id}/cancel", response_model=BookingCancelOut)
async def cancel_booking_post(
    booking_id: int,
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BookingCancelOut:
    return await cancel_booking(booking_id, user_id=user_id, db=db)