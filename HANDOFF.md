# HANDOFF — состояние системы 2brain (обновлено: 2026-09-07 вечер)

Этот файл — точка входа для ZCode на ЛЮБОЙ машине: прочитай его и продолжай работу.
Обновляй после каждого значимого изменения и делай push.

## Что построено

Second brain 2brain v2: Obsidian-хранилище + конвейер без NotebookLM и без внешних API.

- **Хранилище**: мастер на homelab `/srv/2brain` (git там же), Syncthing раздаёт на
  Windows-ПК (`C:\Users\Us\Vaults\2brain`) и Android. Зеркало в Google Drive —
  rclone каждый час (`/etc/periodic/hourly/2brain-mirror` на homelab), работает.
- **Демон**: `/opt/2brain/` на homelab, cron каждые 5 мин от пользователя `twobrain`
  (flock от наложений). Исходники — в этом репозитории (`2brain/`), деплой scp.
  Маршрутизация: ссылки/статьи/YT-субтитры локально (дёшево), ВЕСЬ docling
  (convert/OCR) и STT — в очередь `_Drop/_needs-gpu/` на мощное железо.
  CPU homelab на конвертации НЕ тратим (решение пользователя).
- **Исполнение очереди — рабочий ПК** (i7-14700KF, RTX 3050, 32 ГБ):
  venv `C:\Users\Us\2brain-worker`, раннер `2brain/win-worker/run_queue.py`
  (SSH к homelab забирает jobs, исполняет, возвращает results в `_Drop/_results/`,
  демон доводит заметки до queued). vast.ai — запасной вариант
  (`2brain/gpu-worker/deploy-vast.sh <IP>`).
- **«Суть»**: подписочный ZCode, скилл `2brain-sutya` (этот репозиторий),
  ежедневно пн–пт 10:00. Внешних API нет.
- **Доктрина**: `/srv/2brain/CLAUDE.md` — правится только через /vault-calibrate
  с явным «да» пользователя. 10 полей frontmatter, статус queued-gpu и т.д.

## Доступы

- Homelab: `ssh root@192.168.2.9` (LAN) или `root@100.108.62.152` (NetBird).
  Сервисы Syncthing/демон работают под `twobrain` (файлы хранилища — её владение!).
- Репозиторий: https://github.com/Taner-Engineer/Z.ai.git (этот).
- Syncthing устройства: lenovoz500server (мастер), windows-renat-2 (рабочий ПК,
  ID B3WCOWC-IR5GFEB-…, пере сопряжен 2026-09-07 после гибели старого identity),
  android, windows-21-00x1.

## Открытые хвосты

- GPU-бандл для vast.ai: сборка v3 на homelab (`tail /opt/2brain/state/gpu-test3.log`);
  цель — `[test-ocr] done` + `[test-stt] done`. Не критично: рабочий ПК закрывает всё.
- YT-субтитры иногда не скачиваются с первой попытки (ретраи до 3 в демоне).
- ffmpeg на рабочем ПК не установлен — нужен только для STT-заданий
  (`winget install Gyan.FFmpeg`).
- torch на рабочем ПК — CPU-вариант; для GPU-ускорения docling можно доустановить
  cu121 (~2.5 ГБ), сейчас не требуется.
- Автоматизация «Суть 10:00» живёт в workspace ZCode РАБОЧЕГО ПК — на другой машине
  создать заново (CronCreate, cron `0 10 * * 1-5`, текст в skills/2brain-sutya).

## Как продолжить на новой машине

1. `git clone https://github.com/Taner-Engineer/Z.ai.git && ./install.sh` (скиллы + память)
2. Прочитать этот HANDOFF.md и `/srv/2brain/CLAUDE.md` (доктрина).
3. Раннер очереди: venv + `pip install docling==2.123.0 faster-whisper yt-dlp`,
   затем `win-worker/run_queue.py`.
