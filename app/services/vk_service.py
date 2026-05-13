import json
import random
from pathlib import Path

import httpx

from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


class VKService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = "https://api.vk.com/method"
        self.api_version = "5.199"

    async def send_message(
        self,
        user_id: int,
        text: str,
        keyboard: dict | None = None,
        attachment: str | None = None,
    ) -> None:
        if not self.settings.vk_token:
            logger.warning("VK_TOKEN not set, skipping send_message")
            return

        payload: dict = {
            "access_token": self.settings.vk_token,
            "v": self.api_version,
            "peer_id": user_id,
            "random_id": random.randint(1, 10_000_000),
            "message": text,
        }
        if keyboard:
            payload["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
        if attachment:
            payload["attachment"] = attachment

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{self.base_url}/messages.send", data=payload)
            body = response.text
            logger.info("VK API messages.send → %s", body)
            print("VK RESPONSE STATUS:", response.status_code)
            print("VK RESPONSE BODY:", body)
            data = response.json()
            if "error" in data:
                logger.error("VK API error in send_message: %s", data["error"])

    async def send_document(
        self,
        user_id: int,
        file_path: str,
        title: str | None = None,
    ) -> None:
        """Отправляет PDF-документ как ссылку для скачивания.

        VK группы (community token) запрещают docs.getUploadServer (error 27).
        Вместо этого файл отдаётся через эндпоинт /files/{filename} самого
        приложения. Имя файла содержит UUID — случайный перебор нецелесообразен.

        Требует: APP_BASE_URL в .env, например:
            APP_BASE_URL=https://gacvoyagevkapi-production.up.railway.app
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("Document not found: %s", file_path)
            await self.send_message(user_id, f"⚠️ Документ не найден: {path.name}")
            return

        doc_title = title or path.stem
        base_url = (self.settings.app_base_url or "").rstrip("/")

        if not base_url:
            logger.warning("APP_BASE_URL not set — sending filename only")
            await self.send_message(user_id, f"📄 {doc_title}\n(настройте APP_BASE_URL для ссылки)")
            return

        link = f"{base_url}/files/{path.name}"
        text = f"📄 {doc_title}\n🔗 Скачать: {link}"
        await self.send_message(user_id, text)
        logger.info("Sent document link '%s' to user_id=%s", link, user_id)
