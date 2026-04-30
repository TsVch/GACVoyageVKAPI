from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Tour Booking Bot"
    vk_token: str = Field(default="", alias="VK_TOKEN")
    vk_confirmation_code: str = Field(default="", alias="VK_CONFIRMATION_CODE")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    max_people_per_day: int = Field(default=6, alias="MAX_PEOPLE_PER_DAY")
    file_storage_path: str = Field(default="/tmp/contracts", alias="FILE_STORAGE_PATH")


@lru_cache
def get_settings() -> Settings:
    return Settings()
