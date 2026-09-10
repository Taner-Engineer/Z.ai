# STATUS: 2brain — DJVU без потери текста + docling на GPU рабочего ПК (этапы завершены 2026-09-10)

Сессия, не видевшая прошлой переписки: читай это + `git log --oneline -6`.

## Итоговое состояние

1. **DJVU→PDF остаётся на homelab** (dpsprep 2.8.3, ~2 мин на книгу из 1043 стр.
   на 4 ядрах). Перенос на рабочий ПК отвергнут: нужен WSL (не установлен,
   админ-права + перезагрузка), т.к. dpsprep требует C-биндинги djvulibre-python.
2. **PDF→Markdown через docling — ТОЛЬКО на рабочем ПК** (требование владельца):
   локальный docling:cpu-контейнер удалён из кода homelab (коммит 2cfb8a7),
   все PDF/DJVU идут через GPU-очередь на воркер.
3. **Воркер использует RTX 3050** (требование владельца):
   - torch 2.14.0+cu130 (был +cpu; первый `pip install torch==2.14.0` с cu-индексом
     промахнулся — pip счёл +cpu удовлетворяющим; верный путь:
     `pip install --no-deps --force-reinstall torch==2.14.0+cu130 --index-url
     https://download.pytorch.org/whl/cu130`);
   - onnxruntime заменён на onnxruntime-gpu 1.29.0 — OCR-движок docling
     (RapidOCR, onnx) сам ставит CUDAExecutionProvider первым;
   - `worker.py::_ensure_cuda_dlls()` подкладывает CUDA/cuDNN DLL из torch/lib
     в PATH (без этого ORT тихо падает в CPU: «cublasLt64_13.dll is missing»)
     — коммит f2028ce. Доказано: без хелпера провайдеры = [CPU], с хелпером =
     [CUDA, CPU]; smoke-тест 12 стр. через воркер — код 0, без CPU-фолбэка.

## Сделано ранее этим же днём (коммиты e7d4573, 6427f08)

- Фикс вызова dpsprep (`-q` — это `--quality`, а не quiet): фолбэк на ddjvu
  терял OCR-слой молча; теперь `--quality 85` + stderr при падении в cron.log.
- `router.pdf_analyze` меряет текст в 15 страницах из СЕРЕДИНЫ книги (первые —
  титул — давали ложное «нет слоя»); `daemon._handle_pdf(src_has_text=)` пишет
  ERROR в _daemon.log, если у DJVU был OCR-слой, а в PDF текста нет.
- Валидация на «Уманском»: 1043 стр. за ~2 мин, текст 4666 симв./стр. — такая
  книга теперь идёт как `convert` (docling без OCR, минуты), а не `ocr` (1,5 ч).
- Тесты: `2brain/tests/` — 7 unittest, зелёные на Windows (venv воркера) и на
  homelab (`/opt/2brain-venv`).

## Deploy-состояние

- Homelab `/opt/2brain/`: daemon.py, router.py, processors.py, config.py,
  worker.py — синхронны зеркалу (md5 сверены). Бэкапы: `*.bak-q`,
  `*.bak-txtcheck`, `convert_one.py.bak-docling`. Docker-образ docling:cpu и
  `/opt/2brain/model_cache` на homelab больше не используются кодом — можно
  удалить вручную при чистке диска.
- Рабочий ПК: код воркера — `C:\Users\Us\zcode-sync\2brain\gpu-worker\worker.py`
  (оттуда его запускает run_queue.py), venv `C:\Users\Us\2brain-worker` —
  torch cu130 + onnxruntime-gpu.

## Что дальше (опции)

- Первый настоящий прогон покажет новую скорость OCR (было 0.19 стр/с на CPU);
  телеметрия в манифесте результата (probe-фаза теперь включится: есть CUDA).
- Перегнать «Уманского» новым путём при желании: DJVU из
  `/srv/2brain/_Drop/_processed/` обратно в `_Drop` → уйдёт как `convert`.
- Обновить HANDOFF.md (homelab + github Z.ai) под все три изменения.
- vast.ai-ветка воркера: там свой образ (torch 2.5.1 cu124) — при нужде
  пересобрать под onnxruntime-gpu аналогично.
