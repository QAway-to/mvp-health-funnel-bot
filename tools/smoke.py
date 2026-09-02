"""Сквозная проверка живого сервиса: всё, что проверяется без человека.

Запуск:  TASKS_SECRET=... python tools/smoke.py

ЗАЧЕМ ОТДЕЛЬНО ОТ ТЕСТОВ. Юнит-тесты проверяют код на этой машине. Здесь
проверяется то, что доехало до прода: выкатился ли деплой, отвечают ли
страницы, вооружён ли приём оплаты, не разошлась ли цена звёзд с кнопкой.
Половина поломок за этот проект была именно такой — код верный, а в проде
старая сборка или незаданная переменная.

Чего эта проверка НЕ делает: не разговаривает с ботом. Написать боту как
пользователь может только человек, и сценарий на пять минут — в
site/docs/smoke-manual.md.
"""

import os
import re
import sys

import requests

BASE = "https://mvp-health-funnel-bot.onrender.com"
KEY = os.getenv("TASKS_SECRET", "")

ok, bad = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (ok if condition else bad).append(f"{name}{' — ' + detail if detail else ''}")


def main() -> None:
    if not KEY:
        sys.exit("Нужен TASKS_SECRET: часть проверок читает служебные маршруты.")

    # --- сервис -------------------------------------------------------------
    debug = requests.get(f"{BASE}/debug", timeout=120).json()
    content = debug["content"]
    check("бот в режиме вебхука", debug["mode"] == "webhook", debug["mode"])
    check("состояние в Postgres", debug["store"] == "Postgres", debug["store"])
    check("сайт собран", debug["site_built"])
    check("библиотека без пропусков в разметке", content["untagged"] == 0,
          f"без тегов: {content['untagged']}")
    check("роликов в библиотеке 32", content["total"] == 32, str(content["total"]))

    logs = " ".join(e["message"] for e in debug["logs"])
    check("курсы загружены: 6 направлений, 68 шагов",
          "направлений — 6" in logs or "Курсов загружено: 6" in logs)
    check("цена звёзд сходится с кнопкой", "не сходится" not in logs,
          "в логе есть расхождение звёзд")
    check("оффер настроен", "Оффер настроен" in logs)

    # --- оплата -------------------------------------------------------------
    pay = requests.post(f"{BASE}/payments/lavatop", params={"key": "неверный"},
                        json={"ping": 1}, timeout=90)
    check("вебхук оплаты вооружён", pay.status_code == 403,
          f"{pay.status_code}: {pay.text[:80]}")

    # --- сайт ---------------------------------------------------------------
    pages = ["/", "/son/", "/massazh/", "/zakalivanie/", "/beg/", "/zaryadka/",
             "/vrednye-privychki/", "/start/", "/oferta/", "/politika/",
             "/en/", "/en/son/", "/en/massazh/", "/en/zakalivanie/",
             "/en/beg/", "/en/zaryadka/", "/en/vrednye-privychki/"]
    for path in pages:
        r = requests.get(BASE + path, timeout=60)
        check(f"страница {path}", r.status_code == 200, str(r.status_code))

    home = requests.get(BASE + "/", timeout=60).text
    check("три поп-апа оплаты на главной", home.count("data-pay-dialog") >= 3)
    check("ссылка на кассу стоит", "app.lava.top" in home)
    check("ссылки «звёздами» несут уровень",
          len(re.findall(r"start=buy_\w+__", home)) == 3,
          str(len(re.findall(r"start=buy_\w+__", home))))
    check("цены на главной $10/$20/$100",
          all(p in home for p in ("$10", "$20", "$100")))
    check("отзыв из книги подписан", "из книги Федерации" in home)
    check("подвал ведёт на оферту", "/oferta/" in home)

    offer = requests.get(BASE + "/oferta/", timeout=60).text
    check("оферта опубликована", "1. Общие положения" in offer)
    check("оферта называет сторону", "Федерация здоровья" in offer)
    check("в оферте нет пустых реквизитов",
          "Регистрационный номер:</" not in offer and "Адрес:</" not in offer)

    en = requests.get(BASE + "/en/", timeout=60).text
    check("английская страница честна про язык", "material is in Russian" in en)
    en_son = requests.get(BASE + "/en/son/", timeout=60).text
    nav = re.search(r'<nav class="header__nav".*?</nav>', en_son, re.S)
    hrefs = re.findall(r'href="(/[^"#?]*)"', nav.group(0)) if nav else []
    check("меню английской страницы не уводит на русский",
          all(h.startswith("/en/") for h in hrefs), str([h for h in hrefs if not h.startswith("/en/")]))

    # --- библиотека против шагов -------------------------------------------
    lib = requests.get(f"{BASE}/tasks/library", params={"key": KEY}, timeout=120).json()
    free = sum(1 for i in lib["items"] if i["tier"] == "free")
    check("бесплатных роликов 17", free == 17, str(free))
    check("маршрут разбора библиотеки отвечает", lib.get("ok") is True)

    print(f"\n{'=' * 60}")
    print(f"ПРОШЛО: {len(ok)}")
    for line in ok:
        print(f"  ✓ {line}")
    if bad:
        print(f"\nНЕ ПРОШЛО: {len(bad)}")
        for line in bad:
            print(f"  ✗ {line}")
    print("=" * 60)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
