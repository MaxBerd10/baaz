from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import Role
from app.models import User


async def get_by_telegram(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_or_create(session: AsyncSession, tg_user) -> tuple[User, bool]:
    """tg_user — aiogram types.User. (User, yangi_yaratildimi) qaytaradi."""
    user = await get_by_telegram(session, tg_user.id)
    created = False
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            full_name=(tg_user.full_name or str(tg_user.id))[:255],
            username=tg_user.username,
            role=Role.pending,
        )
        session.add(user)
        created = True
    else:
        # ismni yangilab turamiz
        if tg_user.full_name and user.full_name != tg_user.full_name:
            user.full_name = tg_user.full_name[:255]
        user.username = tg_user.username

    # Bootstrap adminlar
    if tg_user.id in settings.admin_ids and user.role != Role.admin:
        user.role = Role.admin
        user.stage_id = None

    await session.flush()
    return user, created


async def list_by_role(session: AsyncSession, role: Role) -> list[User]:
    return list(
        (
            await session.scalars(
                select(User).where(User.role == role).order_by(User.full_name)
            )
        ).all()
    )


async def list_pending(session: AsyncSession) -> list[User]:
    return await list_by_role(session, Role.pending)


async def all_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.role, User.full_name))).all())


async def qc_recipients(session: AsyncSession) -> list[User]:
    return list(
        (
            await session.scalars(
                select(User).where(
                    User.role == Role.qc, User.is_active.is_(True), User.telegram_id.is_not(None)
                )
            )
        ).all()
    )


async def admin_recipients(session: AsyncSession) -> list[User]:
    return list(
        (
            await session.scalars(
                select(User).where(
                    User.role == Role.admin,
                    User.is_active.is_(True),
                    User.telegram_id.is_not(None),
                )
            )
        ).all()
    )


async def workers_at_stage(session: AsyncSession, stage_order: int) -> list[User]:
    from app.models import Stage

    return list(
        (
            await session.scalars(
                select(User)
                .join(Stage, User.stage_id == Stage.id)
                .where(
                    User.role == Role.worker,
                    User.is_active.is_(True),
                    User.telegram_id.is_not(None),
                    Stage.order_no == stage_order,
                )
            )
        ).all()
    )


async def assign(
    session: AsyncSession, user: User, role: Role, stage_id: int | None = None
) -> None:
    user.role = role
    user.stage_id = stage_id if role == Role.worker else None
    user.is_active = True


async def set_active(session: AsyncSession, user: User, active: bool) -> None:
    user.is_active = active
