from datetime import date

from pydantic import BaseModel


class BookingCreate(BaseModel):
    user_id: int
    tour_id: int
    date: date
    name: str
    phone: str
    people_count: int


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
