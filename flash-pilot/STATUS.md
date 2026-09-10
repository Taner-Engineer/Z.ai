# STATUS: 2brain — HANDOFF обновлён, владельцы починены навсегда, Уманский перегнан convert-путём (2026-09-10)

Сессия, не видевшая прошлой переписки: читай это + `git log --oneline -8`.

## Итоговое состояние

1. **HANDOFF.md (github Z.ai) и 2brain/HANDOFF-homelab.md (снимок 3)** обновлены под
   три изменения прошлого этапа: dpsprep-фикс, проверка текст-слоя, docling на
   GPU воркере (коммит a955b04).
2. **Проблема владельцев root/twobrain закрыта НАСОВСЕГДА** (коммит 77e03f5):
   - пусков было две: ручные прогоны от root (захватили /var/tmp/dpsprep —
     dpsprep упал с PermissionError, ddjvu-фолбэк потерял текст; НОВАЯ проверка
     текст-слоя это поймала: ERROR в _daemon.log, задание ушло бы как ocr) и
     run_queue, возвращающий tar от root в _results;
   - фикс: ОДНА cron-строка в /etc/crontabs/root — chown _results и
     /var/tmp/dpsprep, затем su -s /bin/sh twobrain демона, лог в cron.log
     (бэкап /etc/crontabs/root.bak-2brain-20260910; crontab twobrain пуст);
   - run_queue.py делает chown сразу после возврата результатов (окно в 5 мин
     не существует); worker.py::should_run() пропускает sent/done/failed —
     повторный запуск раннера больше ничего не перегоняет;
   - правило в HANDOFF «Доступы»: ручное на homelab — su -s /bin/sh twobrain,
     ssh root — только админ-действия.
   - Тесты: 13 unittest (7 старых + 6 should_run) — зелёные.
3. **«Уманский» перегнан новым путём** (2026-09-10-97d6a91c, convert):
   - 13:43 enqueue: текст-слой True (dpsprep сохранил OCR-слой после chown);
   - раннер: 1043 стр. за 657 с = **1.59 стр/с** (старый ocr-путь на CPU был
     0.19 стр/с — в 8 раз быстрее); 21 чанк, 1 воркер (лимит VRAM 3050),
     GPU util 7% — convert упирается в CPU; probe-телеметрия в манифесте
     (_processed/2026-09-10-97d6a91c/manifest.json);
   - демон довёл заметку «...Уманск (2).md» до queued сам, raw
     _raw/2026-09-10-transcript-2026-09-10-97d6a91c.txt (UTF-8, 4,4 млн симв.)
     — ни одного ручного chown за весь цикл.

## Deploy-состояние

- Homelab: /opt/2brain синхронен зеркалу (правки этапа касались только
  win-worker/run_queue.py и gpu-worker/worker.py — исполняются на рабочем ПК
  из C:\Users\Us\zcode-sync, деплой на homelab не требовался). Крон — см. п.2.
- Рабочий ПК: venv C:\Users\Us\2brain-worker\venv (torch cu130,
  onnxruntime-gpu 1.29.0), раннер запускался из зеркала репо.

## Известные мелочи

- Старая ocr-заметка Уманского (2026-09-08) и её вложение удалены по решению
  владельца 2026-09-10 (vault-коммит 1377fdc); осталась заметка «(2)» с
  convert-сырьём.
- В jobs/ лежат 3 старых sent-задания (2026-09-07-*) — теперь безвредны
  (worker их скипает), при чистке можно архивировать.

## Что дальше (опции)

- «Суть» по Уманскому — сырьё готово (заметка (2), queued).
- Чистка homelab: docling:cpu-образ, /opt/2brain/model_cache, старые jobs.
- vast.ai-образ (torch 2.5.1 cu124) — пересобрать под onnxruntime-gpu по
  рецепту f2028ce при нужде.
- Хвосты из HANDOFF.md: RDP-перезагрузка ПК, ffmpeg для STT, баги Hermes.
