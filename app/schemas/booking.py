from datetime import date
from typing import Optional

from pydantic import BaseModel


class BookingCreate(BaseModel):
    tour_id: int
    date: date
    name: str
    phone: str
    people_count: int
    vk_id: Optional[str] = None


class BookingOut(BaseModel):
    booking_id: int
    user_id: int
    user_name: str
    phone: str
    tour_id: int
    tour_name: str
    date: date
    count: int
    status: str
    price: float


class MyBookingOut(BaseModel):
    booking_id: int
    tour_name: str
    date: date
    people_count: int
    status: str


class BookingCancelOut(BaseModel):
    booking_id: int
    status: str
    released_places: int