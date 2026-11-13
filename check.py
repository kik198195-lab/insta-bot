# -*- coding: utf-8 -*-
"""Проверка: появлялся ли конкурент в комментариях под постами и в директе.
Ничего не отправляет. Запуск на GitHub: Run workflow → mode: check
"""
import re

import bot
from replies import COMPETITORS

POSTS_TO_SCAN = 100


def main():
    page = bot.call("GET", "me", {"fields": "id,instagram_business_account{id,username}"})
    ig = page["instagram_business_account"]
    names = {n.lower() for n in COMPETITORS}
    mention = re.compile("|".join(re.escape("@" + n) for n in names), re.I)
    print("Ищу:", ", ".join("@" + n for n in names))

    media = bot.get_all(f"{ig['id']}/media", {"fields": "id,permalink,timestamp", "limit": 50}, limit_pages=2)
    media = media[:POSTS_TO_SCAN]
    found = 0
    total = 0
    for m in media:
        comments = bot.get_all(f"{m['id']}/comments", {
            "fields": "id,text,username,timestamp,replies{id,text,username,timestamp}", "limit": 50,
        }, limit_pages=10)
        for c in comments:
            total += 1
            thread = [c] + c.get("replies", {}).get("data", [])
            for x in thread:
                user = (x.get("username") or "").lower()
                text = x.get("text", "")
                if user in names or mention.search(text):
                    found += 1
                    who = "ОТВЕТ на комментарий @" + c.get("username", "?") if x is not c else "комментарий"
                    print(f"\n[{x['timestamp'][:10]}] {who}\n  @{x.get('username')}: «{text[:200]}»\n  {m['permalink']}")
    print(f"\nПроверено постов: {len(media)}, комментариев: {total}. Найдено упоминаний/комментариев: {found}")

    convs = bot.get_all(f"{page['id']}/conversations", {
        "platform": "instagram", "fields": "participants,updated_time", "limit": 50}, limit_pages=10)
    hit = [cv for cv in convs if any((p.get("username") or "").lower() in names
                                     for p in cv.get("participants", {}).get("data", []))]
    print(f"Проверено переписок в директе: {len(convs)}. С конкурентом: {len(hit)}")
    for cv in hit:
        print("  переписка обновлена", cv.get("updated_time", "")[:10])


if __name__ == "__main__":
    main()
