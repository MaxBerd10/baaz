from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.enums import MediaType, ProductStatus, Role, StageRunStatus


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role), default=Role.pending, index=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    stage: Mapped["Stage | None"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.full_name} {self.role}>"


class Stage(Base):
    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StageCheckItem(Base):
    """Bosqich uchun sifat nazorati tekshiruv punkti (shablon)."""

    __tablename__ = "stage_check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), index=True)
    order_no: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StageRunCheck(Base):
    """QC ning aniq bir run uchun bitta punkt bo'yicha bahosi."""

    __tablename__ = "stage_run_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    check_item_id: Mapped[int] = mapped_column(ForeignKey("stage_check_items.id"), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(String(500))
    checked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    check_item: Mapped["StageCheckItem"] = relationship(lazy="selectin")


class TruckModel(Base):
    """Rahbar tuzadigan model ro'yxati (T1, T2, ...)."""

    __tablename__ = "truck_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(64), index=True)
    size_m: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(64))
    line: Mapped[str | None] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProductStatus] = mapped_column(
        SAEnum(ProductStatus), default=ProductStatus.in_production, index=True
    )
    current_stage_order: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id], lazy="selectin")
    stage_runs: Mapped[list["StageRun"]] = relationship(
        back_populates="product", order_by="StageRun.id", lazy="selectin"
    )


class StageRun(Base):
    """Bitta (mahsulot, bosqich, urinish) sikli."""

    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"))
    stage_order: Mapped[int] = mapped_column(Integer, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)

    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    qc_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    status: Mapped[StageRunStatus] = mapped_column(
        SAEnum(StageRunStatus), default=StageRunStatus.in_progress, index=True
    )
    worker_comment: Mapped[str | None] = mapped_column(Text)
    qc_comment: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped["Product"] = relationship(back_populates="stage_runs")
    stage: Mapped["Stage"] = relationship(lazy="selectin")
    worker: Mapped["User | None"] = relationship(foreign_keys=[worker_id], lazy="selectin")
    qc: Mapped["User | None"] = relationship(foreign_keys=[qc_id], lazy="selectin")
    media: Mapped[list["Media"]] = relationship(
        back_populates="stage_run", order_by="Media.id", lazy="selectin"
    )
    checks: Mapped[list["StageRunCheck"]] = relationship(
        order_by="StageRunCheck.id", lazy="selectin", cascade="all, delete-orphan"
    )


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    type: Mapped[MediaType] = mapped_column(SAEnum(MediaType))
    file_path: Mapped[str] = mapped_column(String(512))
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    stage_run: Mapped["StageRun"] = relationship(back_populates="media")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    stage_run_id: Mapped[int | None] = mapped_column(ForeignKey("stage_runs.id"))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
