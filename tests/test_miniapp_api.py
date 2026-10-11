"""Telegram Mini App: kirish, ishchi oqimi, QC oqimi, ruxsatlar va statistika izchilligi."""
from __future__ import annotations

import io
import os
import time
import uuid

import pytest

from app.services import tg_auth

from .conftest import USERS, sql

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40
TOKEN = os.environ.get("BOT_TOKEN", "")


# ---------------------------------------------------------------- yordamchilar
def login(client, who: str) -> dict:
    tg, _, _ = USERS[who]
    init = tg_auth.make_init_data({"id": tg, "first_name": who}, TOKEN)
    r = client.post("/app/api/auth", json={"init_data": init})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_truck(model: str = "TST") -> tuple[int, str]:
    serial = f"UT-{uuid.uuid4().hex[:8]}"
    tid = sql("SELECT web.create_truck($1, $2, 'Sinov mijoz', 'normal', NULL) AS id", serial, model)[0]["id"]
    return tid, serial


def step_id(truck_id: int, n: int) -> int:
    return sql("SELECT id FROM public.truck_steps WHERE truck_id = $1 AND step_number = $2", truck_id, n)[0]["id"]


def upload(client, hdr, sid, data=JPEG, name="a.jpg"):
    return client.post(f"/app/api/step/{sid}/upload", headers=hdr, files={"file": (name, io.BytesIO(data))})


def go_through(client, truck_id, upto, msgs=None):
    """truckni 1..upto bosqichlarda ishchi yuboradi, QC tasdiqlaydi."""
    w = {1: "w1", 2: "w2"}
    qc = login(client, "qc")
    for n in range(1, upto + 1):
        who = w.get(n)
        if who is None:
            sql("UPDATE public.users SET step_number = $1 WHERE telegram_id = $2", n, USERS["w2"][0])
            who = "w2"
        hdr = login(client, who)
        sid = step_id(truck_id, n)
        assert upload(client, hdr, sid).status_code == 200
        assert client.post(f"/app/api/step/{sid}/submit", headers=hdr, json={"comment": f"{n}-bosqich"}).status_code == 200
        assert client.post(f"/app/api/step/{sid}/approve", headers=qc).status_code == 200
    sql("UPDATE public.users SET step_number = 2 WHERE telegram_id = $1", USERS["w2"][0])


# ---------------------------------------------------------------- initData
def test_init_data_valid_and_tampered():
    init = tg_auth.make_init_data({"id": 5, "first_name": "A"}, "123:ABC")
    assert tg_auth.validate_init_data(init, "123:ABC")["id"] == 5
    with pytest.raises(tg_auth.InitDataError):
        tg_auth.validate_init_data(init, "123:OTHER")                       # boshqa token
    with pytest.raises(tg_auth.InitDataError):
        tg_auth.validate_init_data(init.replace("A", "B", 1), "123:ABC")    # o'zgartirilgan
    old = tg_auth.make_init_data({"id": 5}, "123:ABC", auth_date=int(time.time()) - 3 * 86400)
    with pytest.raises(tg_auth.InitDataError):
        tg_auth.validate_init_data(old, "123:ABC")                          # eskirgan
    with pytest.raises(tg_auth.InitDataError):
        tg_auth.validate_init_data("", "123:ABC")


def test_session_token_roundtrip():
    t = tg_auth.make_session_token(42, "k")
    assert tg_auth.read_session_token(t, "k") == 42
    assert tg_auth.read_session_token(t, "other") is None
    assert tg_auth.read_session_token(t + "x", "k") is None


# ---------------------------------------------------------------- kirish
def test_auth_rejections(client):
    assert client.post("/app/api/auth", json={"init_data": "x"}).status_code == 401
    assert client.post("/app/api/auth", json={}).status_code == 401
    unknown = tg_auth.make_init_data({"id": 999999991, "first_name": "Begona"}, TOKEN)
    r = client.post("/app/api/auth", json={"init_data": unknown})
    assert r.status_code == 403 and r.json()["error"] == "not_registered"
    off = tg_auth.make_init_data({"id": USERS["off"][0], "first_name": "x"}, TOKEN)
    r = client.post("/app/api/auth", json={"init_data": off})
    assert r.status_code == 403 and r.json()["error"] == "inactive"
    assert client.get("/app/api/tasks").status_code == 401
    assert client.get("/app/api/tasks", headers={"Authorization": "Bearer yolgon"}).status_code == 401


def test_app_page_is_embeddable_and_not_cached(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert "frame-ancestors" in r.headers.get("content-security-policy", "")
    assert "x-frame-options" not in r.headers and r.headers["cache-control"] == "no-store"
    assert client.get("/login").headers.get("x-frame-options") == "DENY"      # admin panel himoyasi o'zgarmagan


# ---------------------------------------------------------------- ishchi oqimi
def test_worker_sees_only_own_stage(client):
    tid, serial = new_truck()
    w1, w2 = login(client, "w1"), login(client, "w2")
    mine = [t["serial_number"] for t in client.get("/app/api/tasks", headers=w1).json()["items"]]
    assert serial in mine
    assert serial not in [t["serial_number"] for t in client.get("/app/api/tasks", headers=w2).json()["items"]]
    # boshqa bosqich ishchisi yuklay/yubora olmaydi
    assert upload(client, w2, step_id(tid, 1)).status_code == 409
    # QC vazifalar ro'yxatiga kira olmaydi
    assert client.get("/app/api/tasks", headers=login(client, "qc")).status_code == 403


def test_upload_validation_and_limits(client):
    tid, _ = new_truck()
    hdr, sid = login(client, "w1"), step_id(tid, 1)
    assert upload(client, hdr, sid, b"salom dunyo", "x.txt").status_code == 415
    assert upload(client, hdr, sid, b"", "x.jpg").status_code == 415
    for _ in range(10):
        assert upload(client, hdr, sid).status_code == 200
    r = upload(client, hdr, sid)
    assert r.status_code == 409 and r.json()["error"] == "limit_photos"
    for _ in range(5):
        assert upload(client, hdr, sid, MP4, "v.mp4").status_code == 200
    assert upload(client, hdr, sid, MP4, "v.mp4").json()["error"] == "limit_videos"
    d = client.get(f"/app/api/step/{sid}", headers=hdr).json()
    assert len(d["drafts"]) == 15 and d["can_work"] is True
    # qoralamani o'chirish
    mid = d["drafts"][0]["id"]
    assert client.delete(f"/app/api/step/{sid}/media/{mid}", headers=hdr).status_code == 200
    assert len(client.get(f"/app/api/step/{sid}", headers=hdr).json()["drafts"]) == 14


def test_submit_requires_media_and_logs_event(client, sent):
    tid, serial = new_truck()
    hdr, sid = login(client, "w1"), step_id(tid, 1)
    r = client.post(f"/app/api/step/{sid}/submit", headers=hdr, json={})
    assert r.status_code == 422 and r.json()["error"] == "no_media"
    upload(client, hdr, sid), upload(client, hdr, sid, PNG, "b.png"), upload(client, hdr, sid, MP4, "c.mp4")
    r = client.post(f"/app/api/step/{sid}/submit", headers=hdr, json={"comment": "Payvand tayyor"})
    assert r.status_code == 200 and r.json()["files"] == 3
    st = sql("SELECT status::text s, media_type::text m, worker_comment c, worker_id FROM public.truck_steps WHERE id = $1", sid)[0]
    assert st["s"] == "in_review" and st["m"] == "photo" and st["c"] == "Payvand tayyor" and st["worker_id"]
    assert sql("SELECT count(*) n FROM public.truck_step_media WHERE step_id = $1 AND NOT draft", sid)[0]["n"] == 3
    assert [e["event"] for e in sql("SELECT event FROM public.truck_step_events WHERE step_id = $1 ORDER BY id", sid)] == ["submitted"]
    # qayta yuborib bo'lmaydi (allaqachon tekshiruvda)
    assert client.post(f"/app/api/step/{sid}/submit", headers=hdr, json={}).status_code == 409
    # QC ga xabar tugma bilan ketdi, ishchiga tasdiq (rasm bilan) ketdi
    qc_msgs = [m for m in sent if m["chat_id"] == USERS["qc"][0] and m["method"] == "sendMessage"]
    assert qc_msgs and serial in qc_msgs[0]["text"]
    assert qc_msgs[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"].startswith(os.environ["MINIAPP_URL"])
    assert any(m["chat_id"] == USERS["w1"][0] and m["has_file"] for m in sent)
    # bot orqali tekshiruvchi QC rasmni ko'rishi uchun file_id saqlangan
    assert sql("SELECT media_file_id f FROM public.truck_steps WHERE id = $1", sid)[0]["f"] == "FID-TEST"


# ---------------------------------------------------------------- QC oqimi
def test_reject_then_resubmit_then_approve_advances_truck(client, sent):
    tid, serial = new_truck()
    w1, qc = login(client, "w1"), login(client, "qc")
    sid = step_id(tid, 1)
    upload(client, w1, sid)
    client.post(f"/app/api/step/{sid}/submit", headers=w1, json={})
    assert serial in [i["serial_number"] for i in client.get("/app/api/queue", headers=qc).json()["items"]]
    # ishchi tasdiqlay olmaydi; sabab qisqa bo'lsa rad etilmaydi
    assert client.post(f"/app/api/step/{sid}/approve", headers=w1).status_code == 403
    assert client.post(f"/app/api/step/{sid}/reject", headers=qc, json={"reason": "x"}).json()["error"] == "reason_short"
    sent.clear()
    assert client.post(f"/app/api/step/{sid}/reject", headers=qc, json={"reason": "Payvand notekis"}).status_code == 200
    rej = [m for m in sent if m["chat_id"] == USERS["w1"][0]]
    assert rej and "Payvand notekis" in rej[0]["text"]
    # ishchi yana ko'radi: sabab bilan, qayta yuboradi
    task = next(t for t in client.get("/app/api/tasks", headers=w1).json()["items"] if t["serial_number"] == serial)
    assert task["status"] == "rejected" and task["qc_comment"] == "Payvand notekis"
    upload(client, w1, sid, PNG, "p.png")
    assert client.post(f"/app/api/step/{sid}/submit", headers=w1, json={}).status_code == 200
    # eski urinishning fayli almashtirildi (faqat yangisi qoldi)
    assert sql("SELECT count(*) n FROM public.truck_step_media WHERE step_id = $1 AND NOT draft", sid)[0]["n"] == 1
    sent.clear()
    assert client.post(f"/app/api/step/{sid}/approve", headers=qc).json()["completed"] is False
    assert sql("SELECT current_step c FROM public.trucks WHERE id = $1", tid)[0]["c"] == 2
    # ikkinchi marta tasdiqlab bo'lmaydi
    assert client.post(f"/app/api/step/{sid}/approve", headers=qc).status_code == 409
    # keyingi bosqich ishchisiga «yangi vazifa» ketdi, ishchiga «tasdiqlandi»
    assert any(m["chat_id"] == USERS["w2"][0] and "Yangi vazifa" in m["text"] for m in sent)
    assert any(m["chat_id"] == USERS["w1"][0] and "tasdiqlandi" in m["text"] for m in sent)
    # statistika: bu bosqichda IKKI urinish (1 qaytarilgan, 1 tasdiqlangan) — jurnaldan
    runs = sql("SELECT attempt_no, status FROM web.stage_runs WHERE product_id = $1 AND stage_order = 1 ORDER BY attempt_no", tid)
    assert [(r["attempt_no"], r["status"]) for r in runs] == [(1, "returned"), (2, "approved")]
    ev = [e["event"] for e in sql("SELECT event FROM public.truck_step_events WHERE step_id = $1 ORDER BY id", sid)]
    assert ev == ["submitted", "rejected", "submitted", "approved"]
    # 2-bosqich ishchisi endi vazifani ko'radi
    assert serial in [t["serial_number"] for t in client.get("/app/api/tasks", headers=login(client, "w2")).json()["items"]]


def test_full_line_completes_truck_and_notifies_admin(client, sent):
    tid, serial = new_truck()
    go_through(client, tid, 5)
    sent.clear()
    qc = login(client, "qc")
    sql("UPDATE public.users SET step_number = 6 WHERE telegram_id = $1", USERS["w2"][0])
    w = login(client, "w2")
    sid = step_id(tid, 6)
    upload(client, w, sid)
    client.post(f"/app/api/step/{sid}/submit", headers=w, json={})
    assert client.post(f"/app/api/step/{sid}/approve", headers=qc).json()["completed"] is True
    t = sql("SELECT status::text s, completed_at FROM public.trucks WHERE id = $1", tid)[0]
    assert t["s"] == "completed" and t["completed_at"] is not None
    assert any(m["chat_id"] == USERS["admin"][0] and "tayyor" in m["text"] for m in sent)
    sql("UPDATE public.users SET step_number = 2 WHERE telegram_id = $1", USERS["w2"][0])


# ---------------------------------------------------------------- ruxsat va xavfsizlik
def test_media_access_rules(client):
    tid, _ = new_truck()
    w1, w1b, w2 = login(client, "w1"), login(client, "w1b"), login(client, "w2")
    sid = step_id(tid, 1)
    mid = upload(client, w1, sid).json()["id"]
    url = f"/app/media/{mid}"
    assert client.get(url).status_code == 401                                   # tokensiz
    assert client.get(url, headers=w1).status_code == 200                       # egasi
    assert client.get(url, headers=w1b).status_code == 403                      # qoralamani boshqa ishchi ko'rmaydi
    k = w1["Authorization"].split()[1]
    assert client.get(f"{url}?k={k}").status_code == 200                        # <img src> uchun ?k=
    assert client.get("/app/media/m99999999", headers=w1).status_code == 404
    assert client.get("/app/media/xyz", headers=w1).status_code == 404
    # yuborilgach QC ko'ra oladi
    client.post(f"/app/api/step/{sid}/submit", headers=w1, json={})
    assert client.get(url, headers=login(client, "qc")).status_code == 200
    assert client.get(url, headers=w2).status_code == 403                       # boshqa bosqich ishchisi (tegishli emas)


def test_admin_has_counts_but_cannot_work(client):
    adm = login(client, "admin")
    h = client.get("/app/api/home", headers=adm).json()
    assert h["user"]["role"] == "admin" and {"active", "done", "review", "returned"} <= set(h["counts"])
    assert client.get("/app/api/queue", headers=adm).status_code == 403
    assert client.get("/app/api/tasks", headers=adm).status_code == 403


def test_deactivated_user_loses_access_immediately(client):
    hdr = login(client, "w1b")
    assert client.get("/app/api/tasks", headers=hdr).status_code == 200
    sql("UPDATE public.users SET is_active = false WHERE telegram_id = $1", USERS["w1b"][0])
    try:
        assert client.get("/app/api/tasks", headers=hdr).status_code == 403
    finally:
        sql("UPDATE public.users SET is_active = true WHERE telegram_id = $1", USERS["w1b"][0])


def test_history_lists(client):
    tid, serial = new_truck()
    w1, qc = login(client, "w1"), login(client, "qc")
    sid = step_id(tid, 1)
    upload(client, w1, sid)
    client.post(f"/app/api/step/{sid}/submit", headers=w1, json={})
    assert serial in [i["serial_number"] for i in client.get("/app/api/history", headers=w1).json()["items"]]
    client.post(f"/app/api/step/{sid}/approve", headers=qc)
    items = client.get("/app/api/history", headers=qc).json()["items"]
    assert serial in [i["serial_number"] for i in items]


def test_admin_truck_list_and_detail_are_admin_only(client, sent):
    tid, serial = new_truck()
    w1, qc, adm = login(client, "w1"), login(client, "qc"), login(client, "admin")
    sid = step_id(tid, 1)
    upload(client, w1, sid)
    client.post(f"/app/api/step/{sid}/submit", headers=w1, json={})
    client.post(f"/app/api/step/{sid}/reject", headers=qc, json={"reason": "Rasm xira, qayta yuboring"})
    upload(client, w1, sid)
    client.post(f"/app/api/step/{sid}/submit", headers=w1, json={})

    # ro'yxat: tekshiruvdagi truck ko'rinadi, noto'g'ri filtr 404
    items = client.get("/app/api/trucks?f=review", headers=adm).json()["items"]
    assert serial in [i["serial_number"] for i in items]
    assert client.get("/app/api/trucks?f=zzz", headers=adm).status_code == 404

    # batafsil: 6 bosqich, 1-bosqich bir marta qaytarilgan va hozir tekshiruvda
    d = client.get(f"/app/api/truck/{tid}", headers=adm).json()
    assert d["serial_number"] == serial and len(d["stages"]) == 6
    s1 = d["stages"][0]
    assert s1["status"] == "in_review" and s1["rejects"] == 1 and s1["is_current"] and s1["media_count"] >= 1
    assert d["stages"][1]["status"] == "pending" and not d["stages"][1]["is_current"]
    assert client.get("/app/api/truck/99999999", headers=adm).status_code == 404

    # tasdiqlangach vaqt hisoblanadi
    client.post(f"/app/api/step/{sid}/approve", headers=qc)
    s1 = client.get(f"/app/api/truck/{tid}", headers=adm).json()["stages"][0]
    assert s1["status"] == "approved" and s1["seconds"] >= 0

    # ishchi va QC kira olmaydi
    for hdr in (w1, qc):
        assert client.get("/app/api/trucks?f=active", headers=hdr).status_code == 403
        assert client.get(f"/app/api/truck/{tid}", headers=hdr).status_code == 403
    # admin ishning ichini ko'ra oladi, lekin tasdiqlay olmaydi
    assert client.get(f"/app/api/step/{sid}", headers=adm).status_code == 200
    assert client.post(f"/app/api/step/{sid}/approve", headers=adm).status_code == 403
