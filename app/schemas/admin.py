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


class BlockDatePayload(BaseModel):
    tour_id: int
    date: date
