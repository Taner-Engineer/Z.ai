# TASK: проверка текст-слоя после DJVU→PDF (2brain)

Цель одной фразой: после конвертации DJVU→PDF демон должен замерять реальный
текст в страницах PDF (выборка из середины книги) и громко логировать потерю
OCR-слоя источника, вместо тихой отправки книги в многочасовой OCR.

Контекст: репозиторий `C:\Users\Us\zcode-sync`, каталог `2brain/` — зеркало кода
homelab `/opt/2brain` (файлы идентичны). Инцидент, который это лечит: dpsprep
падал (неверный флаг), фолбэк ddjvu делал PDF без текста, книга «Уманский»
зря ушла в 1.5-часовой OCR. Вызов dpsprep уже починен в `2brain/processors.py`
(строки ~230-241, "--quality 85" + stderr при фолбэке) — ЭТИ СТРОКИ НЕ ТРОГАТЬ.

## Изменение 1: `2brain/router.py`, функция `pdf_analyze` (строки 77-88)

Сейчас: выборка первых 15 страниц. У книг первые страницы (титул, форзац,
выходные данные) почти без текста → ложное «нет слоя» → текстовую книгу зря
гонят в медленный OCR.

Заменить на выборку из середины документа:
- `start = max(0, n // 2 - 7)`, конец `min(start + 15, n)`;
- вырожденный случай `n == 0`: вернуть `{"pages": 0, "text_layer": False,
  "chars_per_page": 0}` без деления на ноль;
- ключи возврата и типы НЕ менять: `{"pages": int, "text_layer": bool,
  "chars_per_page": int}`; порог остаётся `config.PDF_CHARS_PER_PAGE`;
- однострочный русский комментарий: почему выборка из середины.

## Изменение 2: `2brain/daemon.py`, функция `_handle_pdf` (строки ~171-189)

- Сигнатура: добавить параметр в конец:
  `def _handle_pdf(p: Path, title_hint: str, source_url: str, scope: str = "global", src_has_text: bool = False) -> None:`
- Сразу после `info = router.pdf_analyze(p)` добавить:

```python
    if src_has_text and not info["text_layer"]:
        log(f"ОШИБКА {p.name}: у DJVU был OCR-слой, но в PDF текста нет — "
            f"потерян при конвертации (dpsprep упал? см. state/cron.log); уходит в OCR")
```

- Ветка `.djvu` (строки ~158-168, `if ext in (".djvu", ".djv"):`) передаёт
  `src_has_text=has_text` в вызов `_handle_pdf(pdf, ...)`.
- Ветка `.pdf` вызывает `_handle_pdf` как раньше, без нового параметра.
- Больше в daemon.py НИЧЕГО не менять (STATS, enqueue, create_note — не трогать).

## Тесты (создать): `2brain/tests/`

- `__init__.py` — пустой файл.
- `test_router_pdf_analyze.py` — реальные PDF во временных файлах (tempfile),
  pymupdf уже установлен в venv:
  1. PDF 30 стр.: середина (страницы ~15-17) с абзацем текста >= 300 символов
     → `text_layer` True, `pages` 30;
  2. PDF 30 стр.: текст ТОЛЬКО на страницах 0-2, середина пустая
     → `text_layer` False (это новое поведение, раньше было бы True);
  3. PDF без текста вообще (пустые страницы) → False;
  4. PDF с 0 страницами → `pages` 0, `text_layer` False, без исключений.
- `test_daemon_handle_pdf.py` — через `unittest.mock.patch` в namespace модуля
  daemon: `router.pdf_analyze` (возвращает словарь-заглушку), `vault.create_note`
  (возвращает `Path("NUL")`), `vault.set_status`, `gpu_queue.enqueue`,
  `daemon.log`, `daemon.STATS` (очищать между тестами). Импорт daemon:
  `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` в начале
  модуля тестов. Сценарии:
  a) `src_has_text=True`, `text_layer=True` → `gpu_queue.enqueue` вызван с
     `kind="convert"`, среди вызовов `log` нет строки с "OCR-слоя";
  b) `src_has_text=True`, `text_layer=False` → `kind="ocr"`, `log` вызван со
     строкой, содержащей "у DJVU был OCR-слой";
  c) `src_has_text=False`, `text_layer=False` → `kind="ocr"`, предупреждения НЕТ.
  Примечание: daemon импортирует vault/processors/gpu_queue/router/config —
  все они импортируются на Windows чисто (config = только константы). Если
  импорт всё же упадёт — записать точный traceback в отчёт, костылями не обходить.

## Критерий приёмки

```
cd C:\Users\Us\zcode-sync && C:/Users/Us/2brain-worker/venv/Scripts/python.exe -m unittest discover -s 2brain/tests -v
```
Все тесты зелёные, выход без ошибок.

## Ограничения

- Дифф ≤ 300 строк; без новых зависимостей (pymupdf уже есть, unittest — stdlib).
- НЕ трогать: `processors.py`, `worker.py`, `gpu_queue.py`, `vault.py`,
  `config.py`, `win-worker/`, `HANDOFF*.md`, `flash-pilot/TASK.md`.
- Комментарии по-русски, плотность как в окружающем коде; кавычки и стиль —
  как в соседних строках.
