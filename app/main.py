import logging

from fastapi import FastAPI
from sqlalchemy import select

from app.db import Base, AsyncSessionLocal, engine
from app.models import Driver, Tour
from app.routers.admin import router as admin_router
from app.routers.vk import router as vk_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Tour Booking Chatbot")
app.include_router(vk_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        tours_exist = (await session.execute(select(Tour.id).limit(1))).first()
        if not tours_exist:
            session.add_all([
                Tour(name="Обзорная по Владивостоку", description="Центр + Токаревский маяк", price=3500, rating=4.8, photo_urls=["https://example.com/tour1.jpg"], vk_album_url="https://vk.com/album-1_1"),
                Tour(name="Остров Русский", description="Мосты, кампус ДВФУ, мыс", price=4500, rating=4.9, photo_urls=["https://example.com/tour2.jpg"], vk_album_url="https://vk.com/album-1_2"),
            ])
            session.add(Driver(name="Диспетчер", vk_user_id=1, is_active=True))
            await session.commit()
