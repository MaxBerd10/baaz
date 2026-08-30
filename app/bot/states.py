from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class WorkerFlow(StatesGroup):
    collecting_media = State()  # data: {"run_id": int}
    writing_comment = State()   # data: {"run_id": int}


class QcFlow(StatesGroup):
    return_reason = State()     # data: {"run_id": int}
    approve_note = State()      # data: {"run_id": int}


class AdminFlow(StatesGroup):
    product_name = State()
    product_line = State()      # data: {"name": str}
    product_note = State()      # data: {"name": str, "line": str}
    stage_name = State()
    stage_rename = State()      # data: {"stage_id": int}
    stage_desc = State()        # data: {"stage_id": int}
    check_add = State()         # data: {"stage_id": int}
    assign_stage = State()      # data: {"user_id": int}
