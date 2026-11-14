# -*- coding: utf-8 -*-
"""Бесплатный автоответчик Instagram: комментарии + директ.

Работает через официальный Instagram Graph API (graph.facebook.com)
от имени Страницы Facebook, к которой привязан Instagram.
Запуск: python bot.py   (переменные окружения ниже)

  IG_TOKEN   — маркер доступа Страницы (бессрочный, обязательно)
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

import ai
from replies import (COMMENT_REPLY_NO_DM, COMPETITORS, HIDE_MODE, PRIVATE_REPLY_CATALOG, classify_comment,
                     classify_dm, foreign_contact, is_buyer, mentions_dm, needs_ai, with_warning)

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ.get("IG_TOKEN", "").strip()
DRY = os.environ.get("DRY_RUN", "0") == "1"
POSTS = int(os.environ.get("POSTS", "15"))
MAX_AGE = timedelta(hours=int(os.environ.get("MAX_AGE_H", "72")))
NOW = datetime.now(timezone.utc)
DM_WINDOW = timedelta(hours=24)  # Instagram разрешает писать только в течение 24 ч
HIDE_AGE = timedelta(days=30)    # скрываем комментарии не старше 30 дней
HIDE_PER_RUN = 40                # не больше 40 скрытий за запуск (старые — постепенно)
hidden_count = 0


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


def hide(c, user, why):
    """Скрыть комментарий: его будут видеть только автор и владелец аккаунта."""
    global hidden_count
    if hidden_count >= HIDE_PER_RUN:
        return  # остальные скроем при следующих запусках
    hidden_count += 1
    preview = c.get("text", "").replace("\n", " ")[:50]
    desc = f"скрыт коммент @{user} ({why}): «{preview}»"
    if HIDE_MODE != "on":
        print("[ПРОБНО-СКРЫТИЕ] " + desc)
        return
    send(desc, "POST", c["id"], {"hide": "true"})


def handle_comments(me):
    media = call("GET", f"{me['id']}/media", {"fields": "id,caption,timestamp,permalink", "limit": POSTS})["data"]
    done, dm_sent = 0, set()
    for m in media:
        comments = get_all(f"{m['id']}/comments", {
            "fields": "id,text,timestamp,username,from,hidden,replies{id,username}",
            "limit": 50,
        })
        for c in comments:
            user = c.get("username") or c.get("from", {}).get("username", "")
            if user == me["username"]:
                continue
            text = c.get("text", "")
            age = NOW - ts(c["timestamp"])
            hidden = c.get("hidden", False)
            if HIDE_MODE != "off" and age <= HIDE_AGE:
                if user.lower() in COMPETITORS:
                    if not hidden:
                        hide(c, user, "конкурент")
                    continue
                if foreign_contact(text):
                    if not hidden:
                        hide(c, user, "чужой номер/ссылка")
                    continue
            replies = c.get("replies", {}).get("data", [])
            if any(r.get("username") == me["username"] for r in replies):
                # уже ответили — покупательский комментарий прячем от чужих глаз
                if HIDE_MODE != "off" and not hidden and age <= HIDE_AGE and is_buyer(text):
                    hide(c, user, "покупатель")
                continue
            if age > MAX_AGE:
                continue
            decision = classify_comment(text)
            if not decision:
                continue
            public, private = decision
            if ai.enabled() and needs_ai(text):
                r = ai.comment_reply(text)
                if r is None:
                    print(f"   пропуск (нейросеть: спам) @{user}: {text[:60]}")
                    continue
                if r:
                    public = r
                    p = ai.dm_reply(text)
                    private = None if p is None else (p or private or PRIVATE_REPLY_CATALOG)
            text_preview = text.replace("\n", " ")[:60]
            # Сначала личное сообщение: если оно не ушло, в комментарии не пишем «в директ»
            dm_ok = user in dm_sent
            if private and not dm_ok:
                dm_ok = send(f"личное сообщение @{user}", "POST", f"{me['page']}/messages",
                             body={"recipient": {"comment_id": c["id"]},
                                   "message": {"text": with_warning(private)}})
                if dm_ok:
                    dm_sent.add(user)
            if not dm_ok and mentions_dm(public):
                public = COMMENT_REPLY_NO_DM
            ok = send(f"коммент @{user}: «{text_preview}» → {public}",
                      "POST", f"{c['id']}/replies", {"message": f"@{user} {public}"})
            if ok and HIDE_MODE != "off" and is_buyer(text):
                hide(c, user, "покупатель")
            done += 1
    return done


def handle_dms(me):
    convs = call("GET", f"{me['page']}/conversations", {
        "platform": "instagram",
        "fields": "id,updated_time,messages.limit(20){id,from,message,created_time}",
        "limit": 25,
    }).get("data", [])
    print(f"Переписок в директе проверено: {len(convs)}")
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
        text = "\n".join(reversed(client_text))
        reply = classify_dm(text, first_contact=not mine)
        if ai.enabled() and needs_ai(text):
            history = "\n".join(
                ("Я: " if x in mine else "Клиент: ") + x.get("message", "")
                for x in reversed(msgs[len(client_text):len(client_text) + 8]))
            r = ai.dm_reply(text, history)
            if r is None:
                print(f"   пропуск (нейросеть: спам): {text[:60]}")
                continue
            reply = r or reply
        if not reply:
            continue
        preview = text.replace("\n", " ")[:60]
        send(f"директ @{sender.get('username', sender.get('id'))}: «{preview}» → {reply[:50]}…",
             "POST", f"{me['page']}/messages",
             body={"recipient": {"id": sender["id"]}, "message": {"text": with_warning(reply)}})
        done += 1
    return done


def main():
    if not TOKEN:
        sys.exit("Нет токена: задайте переменную IG_TOKEN")
    page = call("GET", "me", {"fields": "id,name,instagram_business_account{id,username}"})
    ig = page.get("instagram_business_account")
    if not ig:
        sys.exit("К этой Странице Facebook не привязан профессиональный Instagram")
    me = {"id": ig["id"], "username": ig["username"], "page": page["id"]}
    print(f"Аккаунт @{me['username']}  {'(пробный режим)' if DRY else ''}"
          f"  нейросеть: {'вкл (' + ai.MODEL + ')' if ai.enabled() else 'выкл'}")
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
