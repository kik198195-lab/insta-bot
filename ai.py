# -*- coding: utf-8 -*-
"""Ответы нейросетью Google Gemini (бесплатный тариф) на нестандартные вопросы.

GEMINI_API_KEY — ключ из aistudio.google.com (секрет GitHub).
GEMINI_MODEL   — модель (по умолчанию gemini-flash-latest).
Если ключа нет или Gemini не ответил — бот использует обычные шаблоны.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from replies import CATALOG, WHATSAPP

KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-latest"
HERE = os.path.dirname(os.path.abspath(__file__))

HANDOFF_DM = ("Спасибо, что написали! 💛 Я отвечу вам лично в ближайшее время.\n"
              f"Быстрее всего — в WhatsApp: {WHATSAPP}")
HANDOFF_COMMENT = "Напишите мне, пожалуйста, в директ или WhatsApp — отвечу лично 💛"

# Защита: даже если нейросеть ошибётся, такие ответы не уйдут
_MONEY = re.compile(r"\d[\d\s]*\s*(₸|тг|тенге|₽|руб|сум|сом)", re.I)
_TOOLS = re.compile(r"chat\s?gpt|openai|\bgpt|claude|anthropic|gemini|deepseek|copilot|"
                    r"cursor|lovable|bolt\.new|v0\.dev|replit|canva|wordwall|genially|"
                    r"learningapps|kahoot|tilda|python|javascript", re.I)
_PAY = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b|\+?\d[\d\s()-]{9,}\d", re.I)  # карты/телефоны

_games_cache = None


def enabled():
    # AI_ON=1 (переменная репозитория) — нейросеть отвечает по-настоящему
    return bool(KEY) and os.environ.get("AI_ON", "0") == "1"


def _games():
    """Список игр берём прямо с сайта каталога — новые игры подхватятся сами."""
    global _games_cache
    if _games_cache is not None:
        return _games_cache
    try:
        with urllib.request.urlopen(CATALOG, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        rows = re.findall(r'name:"([^"]+)",\s*subject:"([^"]+)",\s*cls:"([^"]+)",\s*desc:"([^"]*)"', html)
        _games_cache = "\n".join(f"- {n} ({s}, {c} класс): {d}" for n, s, c, d in rows)
    except Exception as e:  # каталог недоступен — работаем без списка
        print("   каталог недоступен:", e)
        _games_cache = "(список временно недоступен — отправляй в каталог)"
    return _games_cache


def _system():
    with open(os.path.join(HERE, "knowledge.md"), encoding="utf-8") as f:
        kb = f.read()
    return kb + "\n\n## Игры в каталоге\n" + _games()


# Запасные модели: если одна перегружена (503) или исчезла (404) — пробуем следующую
MODELS = [MODEL] + [m for m in ("gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest",
                                "gemini-2.5-flash-lite") if m != MODEL]


def _ask(prompt):
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": _system()}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }).encode()
    for model in list(MODELS):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode())
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if model != MODELS[0]:  # запомним рабочую модель до конца запуска
                    MODELS.remove(model)
                    MODELS.insert(0, model)
                time.sleep(4)  # бесплатный тариф: не больше ~15 запросов в минуту
                return text
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:200].replace("\n", " ")
                if e.code in (429, 500, 503) and attempt == 0:
                    time.sleep(20)
                    continue
                print(f"   Gemini {model}: ошибка {e.code} {msg}")
                break  # следующая модель
            except Exception as e:
                print(f"   Gemini {model}: ошибка {e}")
                break
    return None


def _clean(text):
    return re.sub(r"\*\*|__|^#+\s*", "", text, flags=re.M).strip()


def comment_reply(text):
    """Короткий публичный ответ под комментарием. None — пропустить, '' — ошибка."""
    out = _ask(
        "Это КОММЕНТАРИЙ под твоим постом в Instagram. Ответ увидят все.\n"
        "Ответь 1–2 короткими предложениями (до 200 символов). ЦЕН В КОММЕНТАРИЯХ НЕ ПИШИ — "
        "только «напишу вам в директ 📩» или «подробности в WhatsApp». Ссылки не вставляй.\n\n"
        f"Комментарий: «{text}»")
    if not out:
        return ""
    if "ПРОПУСТИТЬ" in out:
        return None
    if "ПЕРЕДАТЬ" in out:
        return HANDOFF_COMMENT
    out = _clean(out)
    if _MONEY.search(out) or _TOOLS.search(out) or _PAY.search(out) or "http" in out or len(out) > 300:
        print("   ответ нейросети отклонён фильтром:", out[:120])
        return ""
    return out


def dm_reply(text, history=""):
    """Ответ в директе. None — пропустить, '' — ошибка (используем шаблон)."""
    out = _ask(
        "Это ЛИЧНОЕ СООБЩЕНИЕ в директ Instagram. Здесь цены называть можно.\n"
        "Ответь по делу, до 600 символов. Если уместно, дай ссылку на каталог "
        f"{CATALOG} и/или WhatsApp {WHATSAPP} (других ссылок не давай).\n"
        + (f"\nПредыдущая переписка (старое сверху):\n{history}\n" if history else "")
        + f"\nНовое сообщение клиента: «{text}»")
    if not out:
        return ""
    if "ПРОПУСТИТЬ" in out:
        return None
    if "ПЕРЕДАТЬ" in out:
        return HANDOFF_DM
    out = _clean(out)
    links = re.findall(r"https?://\S+", out)
    if _TOOLS.search(out) or _PAY.search(out) or len(out) > 1000 or \
            any(not (l.startswith(CATALOG.rstrip("/")) or l.startswith(WHATSAPP)) for l in links):
        print("   ответ нейросети отклонён фильтром:", out[:120])
        return ""
    return out
