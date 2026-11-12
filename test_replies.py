# -*- coding: utf-8 -*-
"""Проверка: python test_replies.py — покажет, что бот ответит на примеры."""
from replies import classify_comment, classify_dm

COMMENTS = [
    "Фонетика", "Сколько стоит?", "Хочу!", "+", "Класс! 😍", "🔥🔥🔥", "❤️",
    "@aigul_88 @dana.k", "Что за программа?", "Как записаться на курс?",
    "Где можно взять эту игру?", "Для 2 класса есть?", "Спасибо большое",
]
DMS = [
    ("Здравствуйте, сколько стоит игра?", True), ("Хочу на курс", True),
    ("Привет", True), ("Привет", False), ("Скиньте каталог", False),
    ("В какой программе вы делаете?", True),
]

for c in COMMENTS:
    r = classify_comment(c)
    print(f"КОММЕНТ «{c}» →", "(пропуск)" if r is None else f"{r[0]}  | ЛС: {'да' if r[1] else 'нет'}")
    if r:
        assert "₸" not in r[0] and "₽" not in r[0], "цена в комментарии!"
print()
for t, first in DMS:
    r = classify_dm(t, first)
    print(f"ДИРЕКТ «{t}» (впервые={first}) →", "(пропуск)" if r is None else r.split("\n")[0] + " … " + r.split("\n")[2][:40])
print("\nOK")
