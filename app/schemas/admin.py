from datetime import date

from pydantic import BaseModel, Field


class TourCreate(BaseModel):
    name: str
    description: str = ""
    price: float
    max_people_per_day: int = 6
    photo_urls: list[str] = Field(default_factory=list)
    vk_album_url: str | None = None
    video_url: str | None = None
    rating: float = 5.0
    start_time: str | None = None
    meeting_point: str | None = None
    duration: str | None = None


class TourUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    max_people_per_day: int | None = None
    photo_urls: list[str] | None = None
    vk_album_url: str | None = None
    video_url: str | None = None
    rating: float | None = None
    start_time: str | None = None
    meeting_point: str | None = None
    duration: str | None = None


class BlockDatePayload(BaseModel):
    tour_id: int
    date: date
