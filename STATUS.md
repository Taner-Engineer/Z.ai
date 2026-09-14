# STATUS — 2brain-конвейер (репо zcode-sync)

Обновлено: 2026-09-14 вечер. Живое состояние машины — STATE.md в репо
`C:\Users\Us\.zcode\workspace\default`; этот файл — про этот репозиторий.

## Последний этап (завершён)

Инцидент: два оркестратора worker.py одновременно делили RTX 3050 (раннер
умер, воркер-сирота остался; лок раннера освободился, второй раннер прошёл)
→ VRAM 92%, трэшинг, 0 вывода за 30 мин. Очередь остановлена, 15 готовых
результатов спасено в `C:\Users\Us\2brain-worker\resume\2026-09-14\`.

Фиксы — коммит **05aa5e2**:
- `2brain/gpu_lock.py` (новый): межпроцессный лок (msvcrt/fcntl), stdlib;
- `worker.py`: gpu-lock только в ветке оркестратора (`--part` не берёт),
  файл `%TEMP%/2brain-gpu.lock`; в docker (нет gpu_lock рядом) — как раньше;
  skip-if-done через `is_done()` + `should_run()` (оживил 6 старых тестов);
- `run_queue.py`: `--seed-results DIR` (можно повторять, дедуп по id) +
  смерть раннера = смерть воркера (SIGINT/SIGTERM/SIGBREAK → finally kill);
- `run_local.py`: пустой results при коде 0 = «GPU занят, прогон отложен»;
- тесты: `2brain/tests/test_gpu_lock_resume.py`, всего 19/19 зелёных:
  `C:\Users\Us\2brain-worker\venv\Scripts\python.exe -m unittest discover -s 2brain/tests`

## Что дальше (следующий этап)

1. Дождаться конца прогона 129 задач (лог `%TEMP%/sber_worker3.log`,
   запуск ~19:10 2026-09-14, resume по 15 спасённым) — homelab-демон заберёт
   results сам.
2. Желаемое улучшение: постоянный каталог результатов у run_queue вместо
   tmp на прогон (сделать resume без ручного seed и повторной закачки
   1,1 ГБ tar). Оценка: ~30 строк в run_queue.py + тест.
3. Новые PDF — в `_Drop` локального ваулта → `run_local.py` (результат на
   homelab, без кругового перегона). DJVU/видео — пока старым путём.
