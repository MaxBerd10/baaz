from __future__ import annotations

import enum


class Role(str, enum.Enum):
    pending = "pending"  # ro'yxatdan o'tgan, lekin rahbar rol bermagan
    worker = "worker"
    qc = "qc"
    admin = "admin"


class ProductStatus(str, enum.Enum):
    in_production = "in_production"  # ishchi joriy bosqichda ishlayapti
    qc_pending = "qc_pending"        # sifat nazorati qarorini kutmoqda
    returned = "returned"            # sifat qaytardi, ishchi tuzatishi kerak
    done = "done"                    # barcha bosqichlardan o'tdi
    cancelled = "cancelled"


class StageRunStatus(str, enum.Enum):
    in_progress = "in_progress"
    qc_pending = "qc_pending"
    approved = "approved"
    returned = "returned"


class MediaType(str, enum.Enum):
    photo = "photo"
    video = "video"


PRODUCT_STATUS_LABEL = {
    ProductStatus.in_production: "🔵 Ishlab chiqarishda",
    ProductStatus.qc_pending: "🟡 Sifat nazoratida",
    ProductStatus.returned: "🔴 Qaytarilgan",
    ProductStatus.done: "🟢 Tayyor",
    ProductStatus.cancelled: "⚫️ Bekor qilingan",
}

ROLE_LABEL = {
    Role.pending: "⏳ Tayinlanmagan",
    Role.worker: "👷 Ishchi",
    Role.qc: "🔍 Sifat nazorati",
    Role.admin: "👑 Rahbar",
}
