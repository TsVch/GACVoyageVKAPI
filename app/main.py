import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text, select

from app.db import Base, AsyncSessionLocal, engine
from app.models import Driver, Tour
from app.routers.admin import router as admin_router
from app.routers.vk import router as vk_router
from app.routers.public import router as public_router
from app.routers.bookings import router as bookings_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Tour Booking Chatbot")
app.include_router(vk_router)
app.include_router(admin_router)
app.include_router(public_router)
app.include_router(bookings_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/files/{filename}")
async def serve_file(filename: str) -> FileResponse:
    """Отдаёт PDF-документ по имени файла.

    Ссылка генерируется ботом и передаётся клиенту/водителю в сообщении.
    Файл технически публичен по URL — без авторизации, без листинга.
    Имена файлов содержат UUID, что делает случайный перебор нецелесообразным.
    """
    from app.config import get_settings
    settings = get_settings()
    path = Path(settings.file_storage_path) / filename
    # Блокируем path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
    )


@app.on_event("startup")
async def startup_event() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE tours ADD COLUMN IF NOT EXISTS start_time VARCHAR(20)"))
        await conn.execute(text("ALTER TABLE tours ADD COLUMN IF NOT EXISTS meeting_point VARCHAR(512)"))
        await conn.execute(text("ALTER TABLE tours ADD COLUMN IF NOT EXISTS duration VARCHAR(64)"))

    async with AsyncSessionLocal() as session:
        tours_exist = (await session.execute(select(Tour.id).limit(1))).first()
        if not tours_exist:
            session.add_all([
                Tour(name="Обзорная по Владивостоку", description="Центр + Токаревский маяк", price=3500, rating=4.8, photo_urls=["https://example.com/tour1.jpg"], vk_album_url="https://vk.com/album-1_1"),
                Tour(name="Остров Русский", description="Мосты, кампус ДВФУ, мыс", price=4500, rating=4.9, photo_urls=["https://example.com/tour2.jpg"], vk_album_url="https://vk.com/album-1_2"),
            ])
            session.add(Driver(name="Диспетчер", vk_user_id=1, is_active=True))
            await session.commit()