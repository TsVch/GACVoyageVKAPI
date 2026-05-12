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
        """Загружает PDF-документ через VK Docs API и отправляет пользователю.

        Требует scope=docs у токена. При ошибке — отправляет текстовое уведомление.
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("Document not found: %s", file_path)
            await self.send_message(user_id, f"⚠️ Документ не найден: {path.name}")
            return

        doc_title = title or path.stem

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Получаем URL сервера загрузки
            r1 = await client.post(
                f"{self.base_url}/docs.getUploadServer",
                data={
                    "access_token": self.settings.vk_token,
                    "v": self.api_version,
                    "type": "doc",
                    "peer_id": user_id,
                },
            )
            d1 = r1.json()
            if "error" in d1:
                logger.error("docs.getUploadServer error: %s", d1["error"])
                await self.send_message(user_id, f"📄 Документ готов: {doc_title} (ошибка загрузки)")
                return
            upload_url: str = d1["response"]["upload_url"]

            # 2. Загружаем файл
            with open(file_path, "rb") as f:
                r2 = await client.post(
                    upload_url,
                    files={"file": (path.name, f, "application/pdf")},
                )
            file_key = r2.json().get("file")
            if not file_key:
                logger.error("VK file upload failed: %s", r2.text)
                await self.send_message(user_id, f"📄 Документ готов: {doc_title} (ошибка загрузки)")
                return

            # 3. Сохраняем документ
            r3 = await client.post(
                f"{self.base_url}/docs.save",
                data={
                    "access_token": self.settings.vk_token,
                    "v": self.api_version,
                    "file": file_key,
                    "title": doc_title,
                },
            )
            d3 = r3.json()
            if "error" in d3:
                logger.error("docs.save error: %s", d3["error"])
                await self.send_message(user_id, f"📄 Документ готов: {doc_title} (ошибка сохранения)")
                return
            doc = d3["response"]["doc"]
            attachment = f"doc{doc['owner_id']}_{doc['id']}"

        # 4. Отправляем сообщение с вложением
        await self.send_message(user_id, f"📄 {doc_title}", attachment=attachment)
        logger.info("Sent document '%s' to user_id=%s", doc_title, user_id)