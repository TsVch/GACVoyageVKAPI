from sqlalchemy import Float, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    max_people_per_day: Mapped[int] = mapped_column(Integer, default=6)
    photo_urls: Mapped[list[str]] = mapped_column(JSONB, default=list)
    vk_album_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    start_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meeting_point: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[str | None] = mapped_column(String(64), nullable=True)

    bookings = relationship("Booking", back_populates="tour", lazy="selectin")
    calendar_days = relationship("CalendarDay", back_populates="tour", lazy="selectin")