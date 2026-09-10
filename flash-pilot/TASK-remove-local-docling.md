# TASK: удалить локальный docling-путь на homelab (2brain)

Цель одной фразой: docling (PDF→MD) исполняется ТОЛЬКО на рабочем ПК через
GPU-очередь — вычистить из кода мёртвый путь запуска docling-контейнера на
homelab, чтобы нарушить это было невозможно.

Контекст: репозиторий `C:\Users\Us\zcode-sync`, каталог `2brain/` — зеркало
homelab `/opt/2brain`. Реальный поток давно другой: `daemon._handle_pdf` ставит
ВСЕ PDF в очередь (`gpu_queue.enqueue`), воркер на рабочем ПК исполняет. Ниже —
остатки старого дизайна, которые никем не вызываются (проверено grep'ом:
`do_pdf` не встречается нигде вне processors.py).

## Что удалить/изменить (точечный FIXLIST)

1. `2brain/processors.py`:
   - строка 15: `_LAST_DOCLING_ERROR: list[str] = [] ...` — удалить;
   - строки 168-218: блок `# --- PDF через docling (в контейнере) ---`, функции
     `_docling_convert` и `do_pdf` целиком — удалить (включая комментарий-
     разделитель).
   - Больше ничего в файле не трогать (djvu_to_pdf и пр. — свежепочиненные).
2. `2brain/config.py`: строки 29-30 `DOCLING_IMAGE` и `DOCLING_CACHE` —
   удалить. `OCR_SEC_PER_PAGE` (строка 54) используется gpu_queue.py — НЕ трогать.
3. Файл `2brain/convert_one.py` — удалить полностью (использовался только
   _docling_convert).
4. `2brain/daemon.py` строка 10 в докстринге модуля: фраза
   `(текст-слой -> docling без OCR; скан >50 стр. -> GPU-очередь;` устарела —
   заменить одной строкой по смыслу: PDF/DJVU -> PDF -> GPU-очередь (рабочий ПК).
   Точную текущую шапку прочитай в файле (строки 1-20) и правь минимально.

## Проверки (приёмка)

1. `cd C:\Users\Us\zcode-sync && C:/Users/Us/2brain-worker/venv/Scripts/python.exe -m unittest discover -s 2brain/tests -v` — все 7 тестов зелёные.
2. `grep -rn "do_pdf\|_docling_convert\|DOCLING_IMAGE\|DOCLING_CACHE\|convert_one\|_LAST_DOCLING" 2brain/` — пусто (кроме, возможно, .bak-файлов).
3. `C:/Users/Us/2brain-worker/venv/Scripts/python.exe -c "import sys; sys.path.insert(0, '2brain'); import processors, daemon"` — импорт без ошибок.

## Ограничения

- Дифф — почти чистое удаление, ≤120 строк; новых файлов и зависимостей нет.
- НЕ трогать: worker.py, gpu_queue.py, vault.py, router.py, win-worker/, тесты,
  HANDOFF*.md, flash-pilot/.
- Комментарии по-русски, стиль как в соседних строках.
