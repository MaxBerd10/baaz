from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.enums import Role
from app.models import User


class RoleFilter(BaseFilter):
    def __init__(self, *roles: Role) -> None:
        self.roles = roles

    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return user is not None and user.is_active and user.role in self.roles
