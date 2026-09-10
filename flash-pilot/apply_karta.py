# -*- coding: utf-8 -*-
"""Разовая замена «## Суть» → «## Карта» в 7 заметках 2brain + шаблоне.
Черновики Карт — из karta-drafts/ (приняты флагманом). Хранилище правится
по прямому указанию владельца: «Суть убрать, должна быть только Карта»."""
import re
import sys
from pathlib import Path

VAULT = Path(r"C:\Users\Us\Vaults\2brain")
DRAFTS = Path(r"C:\Users\Us\zcode-sync\flash-pilot\karta-drafts")

ZOO = ("* **«Me at the zoo» — видео 2005 г. (19 с, канал jawed)** — короткий монолог автора "
       "у вольера со слонами в зоопарке: длинные хоботы слонов и «это почти всё, "
       "что можно о них рассказать».")
FAQ = ("* **FAQ по Syncthing (официальная документация)** — ответы на частые вопросы о работе "
       "синхронизации: прямая передача между устройствами без облака, разбиение файлов на блоки "
       "с параллельной загрузкой, сохранение содержимого и времени изменения файлов, "
       "проверочный маркер .stfolder.")


def draft_bullets(slug: str) -> str:
    text = (DRAFTS / f"{slug}.md").read_text(encoding="utf-8")
    m = re.search(r"## Карта\n\n(.*?)\n\n## Сверка", text, re.S)
    if not m:
        sys.exit(f"нет блока Карты в {slug}.md")
    return m.group(1).strip()


TARGETS = {
    "Knowledge/СП 56.13330.2021 Производственные здания СНиП 31-03-2001_Текст.md": draft_bullets("sp56"),
    "Knowledge/СП 155.13130.2014 Склады нефти и нефтепродуктов. Требования пожарной безопасности (с Изменениями №..._Текст.md": draft_bullets("sp155"),
    "Knowledge/СП 252.1325800.2016 Здания дошкольных общеобразовательных организаций (с поиском).md": draft_bullets("sp252"),
    "Knowledge/How to Get Claude to Actually Read Construction Drawings (Drawing Set → Database).md": draft_bullets("claude-drawings"),
    "Knowledge/Me at the zoo.md": ZOO,
    "Projects/homelab/FAQ — Syncthing documentation.md": FAQ,
    "Knowledge/Hermes Agent Zero to Personal AI Assistant (1 Hour Course).md": "",  # пустая заглушка: только заголовок
}

for rel, bullets in TARGETS.items():
    p = VAULT / rel
    text = p.read_text(encoding="utf-8")
    new_body = "\n## Карта\n\n" + bullets + "\n" if bullets else "\n## Карта\n"
    text2, n = re.subn(r"\n## Суть\n.*?(?=\n## Заметки)", new_body, text, count=1, flags=re.S)
    if n != 1:
        sys.exit(f"FAIL: раздел Суть не найден в {rel}")
    if rel.endswith("(с поиском).md"):  # СП 252: Карта написана — статус в extracted
        text2 = re.sub(r'(^status: )"queued"', r'\1"extracted"', text2, count=1, flags=re.M)
    p.write_text(text2, encoding="utf-8")
    print(f"OK  {rel}  bullets={bullets.count(chr(10)) + 1 if bullets else 0}")

tpl = VAULT / "_Templates" / "Заметка.md"
t = tpl.read_text(encoding="utf-8")
assert "## Суть" in t
tpl.write_text(t.replace("## Суть", "## Карта"), encoding="utf-8")
print("OK  _Templates/Заметка.md")
