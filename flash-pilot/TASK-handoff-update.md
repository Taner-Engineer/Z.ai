# TASK: обновить HANDOFF.md и HANDOFF-homelab.md под три изменения 2026-09-10

Цель одной фразой: оба файла-передачи (точка входа ZCode на любой машине и
снимок homelab) должны отражать текущее состояние конвейера после коммитов
e7d4573, 6427f08, 2cfb8a7, f2028ce.

## Файлы

- ИЗМЕНИТЬ: `C:\Users\Us\zcode-sync\HANDOFF.md`
- ИЗМЕНИТЬ: `C:\Users\Us\zcode-sync\2brain\HANDOFF-homelab.md`
- НЕ ТРОГАТЬ: всё остальное (код, STATUS.md, тесты).

## Факты (использовать только их, ничего не выдумывать)

Источник истины: `flash-pilot/STATUS.md` (прочитай первым) + этот список.

### Изменение 1 — фикс dpsprep (коммит e7d4573, 2brain/processors.py)
- У dpsprep флаг `-q` — это `--quality`, а НЕ quiet. Старый вызов падал,
  фолбэк на ddjvu молча терял OCR-слой.
- Теперь: `--quality 85`; при падении dpsprep stderr пишется в cron.log.
- dpsprep 2.8.3, ~2 мин на книгу 1043 стр. на 4 ядрах homelab.
- Решение: DJVU→PDF ОСТАЁТСЯ на homelab навсегда. Перенос на рабочий ПК
  отвергнут: dpsprep требует C-биндинги djvulibre-python, на Windows нужен
  WSL (не установлен, нужны админ-права + перезагрузка).

### Изменение 2 — проверка текст-слоя (коммит 6427f08, router.py + daemon.py)
- `router.pdf_analyze` меряет текст в 15 страницах из СЕРЕДИНЫ книги
  (первые страницы — титул — давали ложное «нет слоя»).
- `daemon._handle_pdf(src_has_text=)` пишет ERROR в _daemon.log, если у DJVU
  был OCR-слой, а в PDF текста нет (потерян при конвертации).
- Валидация на «Уманском»: 1043 стр. за ~2 мин, 4666 симв./стр. — книга с
  текст-слоем идёт как `convert` (docling без OCR, минуты), а не `ocr` (1,5 ч).
- Тесты: `2brain/tests/` — 7 unittest, зелёные на Windows (venv воркера)
  и на homelab (/opt/2brain-venv).

### Изменение 3 — docling только на GPU-воркере (коммиты 2cfb8a7, f2028ce)
- Локальный docling:cpu-контейнер удалён из кода homelab (2cfb8a7, −87 строк:
  do_pdf/_docling_convert/convert_one). ВСЕ PDF/DJVU идут через GPU-очередь
  на рабочий ПК. Требование владельца.
- Воркер использует RTX 3050 6 ГБ:
  - torch 2.14.0+cu130 (установка: `pip install --no-deps --force-reinstall
    torch==2.14.0+cu130 --index-url https://download.pytorch.org/whl/cu130`;
    обычный `pip install torch==2.14.0` с cu-индексом промахивается — pip
    считает установленную +cpu удовлетворяющей требованию);
  - onnxruntime-gpu 1.29.0 вместо onnxruntime — OCR-движок docling (RapidOCR,
    onnx) сам ставит CUDAExecutionProvider первым;
  - `worker.py::_ensure_cuda_dlls()` подкладывает CUDA/cuDNN DLL из torch/lib
    в PATH; без этого ORT тихо падает в CPU («cublasLt64_13.dll is missing»).
    Доказано: провайдеры [CPU] без хелпера → [CUDA, CPU] с хелпером;
    smoke-тест 12 стр. через воркер — код 0.
- Прочие версии venv воркера: docling 2.123.0, rapidocr 3.9.2, pymupdf 1.28.2,
  faster-whisper 1.2.1.

### Deploy-состояние
- Homelab /opt/2brain: daemon.py, router.py, processors.py, config.py,
  worker.py — синхронны зеркалу (md5 сверены). Бэкапы на месте: `*.bak-q`,
  `*.bak-txtcheck`, `convert_one.py.bak-docling`.
- Docker-образ docling:cpu и `/opt/2brain/model_cache` на homelab больше не
  используются кодом — можно удалить вручную при чистке диска.
- Рабочий ПК: код воркера `C:\Users\Us\zcode-sync\2brain\gpu-worker\worker.py`,
  venv `C:\Users\Us\2brain-worker\venv` (torch cu130 + onnxruntime-gpu).

## Правки HANDOFF.md (корень)

1. Шапка: дату «2026-09-08» → «2026-09-10».
2. «Срочно знать при старте новой сессии»: добавить первым пунктом краткую
   сводку трёх изменений 2026-09-10 с коммитами и отсылкой к
   `flash-pilot/STATUS.md`. Существующие пункты не удалять.
3. «Железо-роли», подпункт «Рабочий ПК»: дописать CUDA-стек (torch
   2.14.0+cu130, onnxruntime-gpu 1.29.0, `worker.py::_ensure_cuda_dlls()` сам
   подкладывает CUDA/cuDNN DLL из torch/lib — GPU-провайдеры включаются без
   настройки; RTX 3050 реально используется).
4. «Открытые хвосты», пункт про DJVU→PDF на homelab: переписать — решение
   принято: остаётся на homelab насовсем (dpsprep требует djvulibre
   C-биндинги, на Windows нужен WSL — отвергнуто); фикс `-q`→`--quality 85`
   уже в проде (e7d4573).
5. «Открытые хвосты»: добавить два пункта:
   - на homelab не используются кодом docling:cpu-образ и
     /opt/2brain/model_cache — удалить вручную при чистке диска;
   - vast.ai-образ воркера (torch 2.5.1 cu124) не пересобран под
     onnxruntime-gpu — при нужде повторить рецепт рабочего ПК (f2028ce).
6. «Как продолжить на новой машине», шаг 3: заменить pip-строку на
   актуальную: `pip install docling==2.123.0 onnxruntime-gpu pymupdf
   faster-whisper yt-dlp`, затем torch:
   `pip install --no-deps --force-reinstall torch==2.14.0+cu130 --index-url
   https://download.pytorch.org/whl/cu130` (предупредить про ловушку +cpu);
   CUDA DLL подтянет worker.py сам.

## Правки 2brain/HANDOFF-homelab.md

1. Шапка: «снимок 2, 2026-09-08 вечер» → «снимок 3, 2026-09-10»; строку
   «Предыдущий снимок: коммит 708c72f (ночь 2026-09-08)» заменить на
   «Предыдущий снимок: 2 (2026-09-08 вечер)».
2. Сразу после шапки добавить раздел «## Дельта до снимка 3 (2026-09-10,
   ZCode flash)» с подпунктами по трём изменениям (факты выше, компактно)
   и deploy-состоянием. В конце раздела строка: рекомендации «Порядок
   действий» снимка 2 устарели — оба GPU-задания выполнены 2026-09-08,
   сессии Hermes-хвосты (п.5 снимка 2) не тронуты.
3. Старое содержимое снимка 2 НЕ переписывать и НЕ удалять — это история.

## Критерий приёмки

- `git diff --stat` — ровно 2 изменённых файла, суммарно ≤150 строк диффа.
- Все факты в правках соответствуют разделу «Факты» (коммиты, версии, пути).
- Markdown валиден, стиль/язык — как в окружающих разделах (русский, плотный).

## Ограничения

- Без новых зависимостей, без правок кода, без «улучшений» остальных разделов.
