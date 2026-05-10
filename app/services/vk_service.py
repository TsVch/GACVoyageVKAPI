import json
import random

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
            print("VK TOKEN NOT SET")
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

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/messages.send",
                data=payload
            )
            logger.info("VK API response: %s", response.text)

            print("VK RESPONSE STATUS:", response.status_code)
            print("VK RESPONSE BODY:", response.text)

    async def send_document(self, user_id: int, file_path: str) -> None:
        await self.send_message(user_id, f"PDF: {file_path}")