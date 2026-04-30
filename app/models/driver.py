from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vk_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
