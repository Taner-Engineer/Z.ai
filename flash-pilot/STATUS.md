# STATUS: 2brain — DJVU без потери текста (этап завершён 2026-09-10)

Сессия, не видевшая прошлой переписки: читай это + `git log --oneline -5`.

## Что сделано

Инцидент: книга «Уманский 1960» (DJVU с OCR-слоем 4,5 млн симв.) конвертировалась
в PDF без текста и зря уходила в 1,5-часовой CPU-OCR. Причина: в
`processors.djvu_to_pdf` вызов `dpsprep -q` падал мгновенно — в dpsprep 2.8.3
`-q` это `--quality <int>`, а не «quiet»; молчаливый фолбэк на ddjvu (картинка
без текста, Producer «libtiff / tiff2pdf»).

1. **Фикс вызова** (`2brain/processors.py`): `--quality 85` + stderr-лог при
   падении dpsprep на фолбэк (виден в `state/cron.log` на homelab).
2. **Проверка текст-слоя** (делегировано по flash-delegate, TASK-djvu-verify.md):
   - `2brain/router.py::pdf_analyze` — выборка 15 страниц из середины книги
     (первые страницы — титул/форзац — давали ложное «нет слоя»);
   - `2brain/daemon.py::_handle_pdf(..., src_has_text=)` — если у DJVU был
     OCR-слой, а в PDF текста нет: ERROR в `_daemon.log`, задание уходит в OCR
     честно (не молча).
   - Тесты: `2brain/tests/` — 7 unittest, зелёные локально (venv воркера) и на
     homelab (`/opt/2brain-venv`).

## Валидация на реальной книге

dpsprep на homelab (4 ядра, пул по умолчанию): 1043 стр. за ~2 мин 15 с,
PDF 120 МБ, текст-слой сохранён: 4666 симв./стр. (первые 15), 2476 (середина),
2,95 млн симв. на книгу. Такая книга теперь маршрутизируется как `convert`
(docling без OCR, минуты), а не `ocr` (1,5 ч).

## Deploy

- Homelab `/opt/2brain/`: daemon.py, router.py, processors.py заменены
  (scp + chown twobrain, py_compile OK). Бэкапы рядом: `*.bak-q`,
  `*.bak-txtcheck`. Демон подхватит новые файлы со следующего прохода cron
  (каждые 5 мин), перезапуск не нужен.
- Зеркало `C:\Users\Us\zcode-sync\2brain\` идентично homelab (md5 сверены).

## Архитектурное решение (зафиксировано)

Перенос шага DJVU→PDF на рабочий ПК **отвергнут**: dpsprep требует
`djvulibre-python` (C-биндинги, Windows-wheels нет), WSL не установлен
(нужны админ-права + перезагрузка), а homelab конвертирует книгу за ~2 мин —
узкого места нет. Если понадобится — сначала `wsl --install`, затем функция
`run_djvu` в worker.py (конвертация + та же проверка текст-слоя на воркере).

## Что дальше (опции, не обязательно)

- Перегнать «Уманского» новым путём (если нужен исходный библиотечный OCR вместо
  docling-OCR): кинуть DJVU из `_Drop/_processed/` обратно в `_Drop` — уйдёт
  как `convert` за минуты. Текущий docling-результат уже лежит во вложении
  2026-09-08-…Уманск.md.
- OCR-сканы на воркере идут по-прежнему на CPU (torch 2.14.0+cpu): cu-сборка
  torch в `C:\Users\Us\2brain-worker\venv` ускорит `kind=ocr` в разы.
- Обновить HANDOFF.md (homelab + github Z.ai) под новое поведение DJVU.
