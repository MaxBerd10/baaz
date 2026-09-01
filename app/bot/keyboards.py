from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.enums import Role
from app.bot.texts import truck_name
from app.models import Product, Stage, StageRun, User

# --------------------------------------------------------------------------- #
# Reply (asosiy menyu) klaviaturalari
# --------------------------------------------------------------------------- #
WORKER_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📦 Mening ishlarim"), KeyboardButton(text="🔴 Qaytarilganlar")],
        [KeyboardButton(text="✅ Tugatganlarim"), KeyboardButton(text="ℹ️ Men kim")],
    ],
    resize_keyboard=True,
)

QC_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Tekshiruv navbati")],
        [KeyboardButton(text="📜 So'nggi qarorlar"), KeyboardButton(text="ℹ️ Men kim")],
    ],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Boshqaruv paneli"), KeyboardButton(text="🚚 Trucklar")],
        [KeyboardButton(text="➕ Yangi truck"), KeyboardButton(text="👥 Xodimlar")],
        [KeyboardButton(text="🏭 Liniyalar"), KeyboardButton(text="🚚 Modellar")],
        [KeyboardButton(text="📈 Hisobot")],
    ],
    resize_keyboard=True,
)

PENDING_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="ℹ️ Men kim")]],
    resize_keyboard=True,
)


def menu_for(user: User | None) -> ReplyKeyboardMarkup:
    if user is None:
        return PENDING_MENU
    return {
        Role.admin: ADMIN_MENU,
        Role.qc: QC_MENU,
        Role.worker: WORKER_MENU,
        Role.pending: PENDING_MENU,
    }[user.role]


# --------------------------------------------------------------------------- #
# Ishchi — inline
# --------------------------------------------------------------------------- #
def worker_product_list(products: list[Product], kind: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📦 {truck_name(p)}", callback_data=f"w:open:{p.id}")]
        for p in products
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="— bo'sh —", callback_data="noop")]])


def worker_product_card(run: StageRun, kind: str = "active") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📸 Rasm / Video qo'shish", callback_data=f"w:media:{run.id}")],
        [InlineKeyboardButton(text="📝 Izoh yozish", callback_data=f"w:comment:{run.id}")],
        [InlineKeyboardButton(text="🚀 Sifat nazoratiga yuborish", callback_data=f"w:submit:{run.id}")],
        [InlineKeyboardButton(text="⬅️ Ro'yxatga", callback_data=f"w:list:{kind}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def open_button(kind: str, obj_id: int, label: str = "Ochish") -> InlineKeyboardMarkup:
    """Bildirishnomalar uchun bitta '↗️ Ochish' tugmasi. kind: 'w' | 'q'."""
    cb = f"w:open:{obj_id}" if kind == "w" else f"q:open:{obj_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"↗️ {label}", callback_data=cb)]]
    )


def worker_collecting(run: StageRun) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Media qo'shishni yakunlash", callback_data=f"w:mediadone:{run.id}")]
        ]
    )


# --------------------------------------------------------------------------- #
# Sifat nazorati — inline
# --------------------------------------------------------------------------- #
def qc_queue_list(runs: list[StageRun]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📦 {truck_name(r.product)} · {r.stage_order}-bosqich",
                callback_data=f"q:open:{r.id}",
            )
        ]
        for r in runs
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=rows or [[InlineKeyboardButton(text="— navbat bo'sh —", callback_data="noop")]]
    )


_MARK = {True: "✅", False: "❌", None: "⬜️"}


def qc_decision(run: StageRun) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ TASDIQLASH", callback_data=f"q:approve:{run.id}"),
                InlineKeyboardButton(text="❌ QAYTARISH", callback_data=f"q:return:{run.id}"),
            ],
            [
                InlineKeyboardButton(text="📜 Mahsulot tarixi", callback_data=f"q:hist:{run.id}"),
                InlineKeyboardButton(text="🔄 Navbat", callback_data="q:queue"),
            ],
        ]
    )


def qc_checklist(run: StageRun, state: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for s in state:
        it = s["item"]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{_MARK[s['ok']]} {it.order_no}. {it.text[:44]}",
                    callback_data=f"q:chk:{run.id}:{it.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✅ TASDIQLASH", callback_data=f"q:approve:{run.id}"),
            InlineKeyboardButton(text="❌ QAYTARISH", callback_data=f"q:return:{run.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="📜 Mahsulot tarixi", callback_data=f"q:hist:{run.id}"),
            InlineKeyboardButton(text="🔄 Navbat", callback_data="q:queue"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# Rahbar — inline
# --------------------------------------------------------------------------- #
def admin_product_list(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{truck_name(p)}", callback_data=f"a:prod:{p.id}"
            )
        ]
        for p in products
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=rows or [[InlineKeyboardButton(text="— bo'sh —", callback_data="noop")]]
    )


def admin_users_list(users: list[User]) -> InlineKeyboardMarkup:
    from app.enums import ROLE_LABEL

    rows = [
        [
            InlineKeyboardButton(
                text=f"{ROLE_LABEL[u.role]} {u.full_name}"
                + ("" if u.is_active else " (o'chirilgan)"),
                callback_data=f"a:user:{u.id}",
            )
        ]
        for u in users
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=rows or [[InlineKeyboardButton(text="— xodim yo'q —", callback_data="noop")]]
    )


def admin_user_card(target: User) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👷 Ishchi", callback_data=f"a:setrole:{target.id}:worker"),
            InlineKeyboardButton(text="🔍 Sifat", callback_data=f"a:setrole:{target.id}:qc"),
            InlineKeyboardButton(text="👑 Rahbar", callback_data=f"a:setrole:{target.id}:admin"),
        ],
        [
            InlineKeyboardButton(
                text=("🚫 O'chirish" if target.is_active else "♻️ Faollashtirish"),
                callback_data=f"a:toggleuser:{target.id}",
            ),
            InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data="a:users"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_stage(user_id: int, stages: list[Stage]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{s.order_no}. {s.name}",
                callback_data=f"a:setstage:{user_id}:{s.order_no}",
            )
        ]
        for s in stages
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_stages_list(stages: list[Stage]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{s.order_no}. {s.name}", callback_data=f"a:stage:{s.id}")]
        for s in stages
    ]
    rows.append([InlineKeyboardButton(text="➕ Bosqich qo'shish", callback_data="a:stageadd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_stage_card(stage: Stage) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Nomi", callback_data=f"a:stagerename:{stage.id}"),
                InlineKeyboardButton(text="📝 Tavsif", callback_data=f"a:stagedesc:{stage.id}"),
            ],
            [InlineKeyboardButton(text="📋 Tekshiruv ro'yxati", callback_data=f"a:chklist:{stage.id}")],
            [InlineKeyboardButton(text="⬅️ Bosqichlar", callback_data="a:stages")],
        ]
    )


def admin_checklist(stage: Stage, items: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {it.order_no}. {it.text[:40]}", callback_data=f"a:chkdel:{it.id}"
            )
        ]
        for it in items
    ]
    rows.append([InlineKeyboardButton(text="➕ Punkt qo'shish", callback_data=f"a:chkadd:{stage.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Bosqich", callback_data=f"a:stage:{stage.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_product_open(product: Product) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Trucklar", callback_data="a:products")]
        ]
    )


def admin_pick_model(models: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🚚 {m.name}", callback_data=f"a:npmodel:{m.id}")]
        for m in models
    ]
    rows.append([InlineKeyboardButton(text="✏️ Yangi model", callback_data="a:npmodel:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="✏️ Model qo'shish", callback_data="a:npmodel:new")]])


def admin_pick_size(sizes: list[int]) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=f"{s} m", callback_data=f"a:npsize:{s}") for s in sizes]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def admin_models_list(models: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🗑 {m.name}", callback_data=f"a:modeldel:{m.id}")]
        for m in models
    ]
    rows.append([InlineKeyboardButton(text="➕ Model qo'shish", callback_data="a:modeladd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
