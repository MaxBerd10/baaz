from __future__ import annotations

from functools import cached_property

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./baaz.db"
    admin_telegram_ids: str = ""
    media_root: str = "./media"

    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_password: str = "admin"
    secret_key: str = "change-me"

    default_stage_count: int = 6
    timezone: str = "Asia/Tashkent"

    # Sifatga yuborishdan oldin talab qilinadigan minimal media soni
    min_media_to_submit: int = 1

    @field_validator(
        "web_port", "default_stage_count", "min_media_to_submit", mode="before"
    )
    @classmethod
    def _blank_int_to_default(cls, v, info):
        # Ba'zi hostinglar (Vercel) bo'sh muhit o'zgaruvchisini "" sifatida beradi —
        # bunday holda maydonning standart qiymatiga qaytamiz.
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return cls.model_fields[info.field_name].default
        return v

    @cached_property
    def admin_ids(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.admin_telegram_ids.replace(" ", "").split(","):
            if chunk:
                try:
                    out.add(int(chunk))
                except ValueError:
                    pass
        return out


settings = Settings()
