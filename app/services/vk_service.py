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

        payload = {
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
            response = await client.post(
                f"{self.base_url}/messages.send",
                data=payload,
            )

            body = response.text
            logger.info("VK API messages.send → %s", body)

            try:
                data = response.json()
                if "error" in data:
                    logger.error("VK API error: %s", data["error"])
            except Exception:
                logger.error("VK response not JSON: %s", body)

    async def send_document(
        self,
        user_id: int,
        file_path: str,
        title: str | None = None,
    ) -> None:
        """
        УНИВЕРСАЛЬНЫЙ режим:
        - если file_path = URL → просто отправляем ссылку
        - если file_path = локальный путь → делаем ссылку через app_base_url
        """

        doc_title = title or "Документ"
        base_url = (self.settings.app_base_url or "").rstrip("/")

        # CASE 1: уже готовый URL
        if file_path.startswith("http"):
            link = file_path

        # CASE 2: /files/... (из твоего FastAPI)
        elif file_path.startswith("/files/"):
            if not base_url:
                await self.send_message(
                    user_id,
                    f"📄 {doc_title}\n(не настроен APP_BASE_URL)",
                )
                return
            link = f"{base_url}{file_path}"

        # CASE 3: локальный файл на сервере
        else:
            path = Path(file_path)

            if not path.exists():
                logger.error("Document not found: %s", file_path)
                await self.send_message(
                    user_id,
                    f"⚠️ Документ не найден: {path.name}",
                )
                return

            if not base_url:
                await self.send_message(
                    user_id,
                    f"📄 {doc_title}\n(не настроен APP_BASE_URL)",
                )
                return

            link = f"{base_url}/files/{path.name}"

        text = f"📄 {doc_title}\n🔗 Скачать: {link}"

        await self.send_message(user_id, text)

        logger.info("Sent document to user_id=%s → %s", user_id, link)