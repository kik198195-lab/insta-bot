# -*- coding: utf-8 -*-
"""Бесплатный автоответчик Instagram: комментарии + директ.

Работает через официальный Instagram API (graph.instagram.com).
Запуск: python bot.py   (переменные окружения ниже)

  IG_TOKEN   — токен доступа (обязательно)
  DRY_RUN    — "1": только показать, что бот ответил бы, ничего не отправлять
  POSTS      — сколько последних публикаций проверять (по умолчанию 15)
  MAX_AGE_H  — отвечать только на комментарии моложе N часов (по умолчанию 72)

Бот сам понимает, что уже ответил: если под комментарием есть ответ от аккаунта
(бота, SMMBOT или Ильмиры) — пропускает. Поэтому база данных не нужна.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from replies import classify_comment, classify_dm

API = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("IG_TOKEN", "").strip()
DRY = os.environ.get("DRY_RUN", "0") == "1"
POSTS = int(os.environ.get("POSTS", "15"))
MAX_AGE = timedelta(hours=int(os.environ.get("MAX_AGE_H", "72")))
NOW = datetime.now(timezone.utc)
DM_WINDOW = timedelta(hours=24)  # Instagram разрешает писать только в течение 24 ч


def call(method, path, params=None, body=None):
    params = dict(params or {})
    params["access_token"] = TOKEN
    url = f"{API}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {err}") from None


def get_all(path, params, limit_pages=3):
    out, page = [], call("GET", path, params)
    for _ in range(limit_pages):
        out += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        with urllib.request.urlopen(nxt, timeout=30) as r:
            page = json.loads(r.read().decode())
    return out


def ts(s):
    # "2026-11-12T08:15:00+0000"
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def send(desc, method, path, params=None, body=None):
    print(("[ПРОБНО] " if DRY else "[ОТПРАВЛЕНО] ") + desc)
    if DRY:
        return True
    try:
        call(method, path, params, body)
        time.sleep(2)  # не спешим — меньше шансов на ограничения Instagram
        return True
    except RuntimeError as e:
        print("   ошибка:", e)
        return False


def handle_comments(me):
    media = call("GET", "me/media", {"fields": "id,caption,timestamp,permalink", "limit": POSTS})["data"]
    done = 0
    for m in media:
        comments = get_all(f"{m['id']}/comments", {
            "fields": "id,text,timestamp,username,from,replies{id,username}",
            "limit": 50,
        })
        for c in comments:
            user = c.get("username") or c.get("from", {}).get("username", "")
            if user == me["username"]:
                continue
            if NOW - ts(c["timestamp"]) > MAX_AGE:
                continue
            replies = c.get("replies", {}).get("data", [])
            if any(r.get("username") == me["username"] for r in replies):
                continue  # уже ответили
            decision = classify_comment(c.get("text", ""))
            if not decision:
                continue
            public, private = decision
            text_preview = c.get("text", "").replace("\n", " ")[:60]
            ok = send(f"коммент @{user}: «{text_preview}» → {public}",
                      "POST", f"{c['id']}/replies", {"message": f"@{user} {public}"})
            if ok and private:
                send(f"   личное сообщение @{user}", "POST", "me/messages",
                     body={"recipient": {"comment_id": c["id"]}, "message": {"text": private}})
            done += 1
    return done


def handle_dms(me):
    convs = call("GET", "me/conversations", {
        "platform": "instagram",
        "fields": "id,updated_time,messages.limit(20){id,from,message,created_time}",
        "limit": 25,
    }).get("data", [])
    done = 0
    for cv in convs:
        msgs = cv.get("messages", {}).get("data", [])  # новые — первыми
        if not msgs:
            continue
        last = msgs[0]
        sender = last.get("from", {})
        if sender.get("id") == me["id"] or sender.get("username") == me["username"]:
            continue  # последнее сообщение наше — ждём клиента
        if NOW - ts(last["created_time"]) > DM_WINDOW:
            continue
        mine = [x for x in msgs if x.get("from", {}).get("id") == me["id"]
                or x.get("from", {}).get("username") == me["username"]]
        if any(NOW - ts(x["created_time"]) < DM_WINDOW for x in mine):
            continue  # сегодня уже общались — дальше отвечает человек
        # все непрочитанные сообщения клиента после нашего последнего
        client_text = []
        for x in msgs:
            if x in mine:
                break
            client_text.append(x.get("message", ""))
        reply = classify_dm(" ".join(client_text), first_contact=not mine)
        if not reply:
            continue
        preview = " ".join(client_text).replace("\n", " ")[:60]
        send(f"директ @{sender.get('username', sender.get('id'))}: «{preview}» → {reply[:50]}…",
             "POST", "me/messages",
             body={"recipient": {"id": sender["id"]}, "message": {"text": reply}})
        done += 1
    return done


def main():
    if not TOKEN:
        sys.exit("Нет токена: задайте переменную IG_TOKEN")
    me = call("GET", "me", {"fields": "id,user_id,username"})
    # в сообщениях отправитель указывается через user_id (IGSID аккаунта)
    me["id"] = me.get("user_id", me["id"])
    print(f"Аккаунт @{me['username']}  {'(пробный режим)' if DRY else ''}")
    errors = 0
    for name, fn in (("Комментарии", handle_comments), ("Директ", handle_dms)):
        try:
            print(f"{name}: ответов — {fn(me)}")
        except RuntimeError as e:
            errors += 1
            print(f"{name}: ошибка — {e}")
    sys.exit(1 if errors == 2 else 0)


if __name__ == "__main__":
    main()
