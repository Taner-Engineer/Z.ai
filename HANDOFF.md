# HANDOFF — состояние системы 2brain (обновлено: 2026-09-07 поздний вечер)

Этот файл — точка входа для ZCode на ЛЮБОЙ машине: прочитай его и продолжай работу.
Обновляй после каждого значимого изменения и делай push.

## Железо-роли (правило пользователя: хоумлаб НЕ тратит CPU на тяжёлое)

- **Homelab** — только оркестрация: демон (cron 5 мин), маршрутизация, очередь,
  SSH-координация. Никаких docling/OCR/STT/docker-build на нём.
- **Рабочий ПК** (i7-14700KF, RTX 3050 6 ГБ, 32 ГБ) — исполнитель очереди:
  venv `C:\Users\Us\2brain-worker`, раннер `2brain/win-worker/run_queue.py`
  (SSH забирает jobs с homelab, исполняет worker.py, возвращает в `_Drop/_results/`).
- **vast.ai** — для больших батчей или когда ПК выключен. **SSH в кастомный образ
  НЕ РАБОТАЕТ** (наш образ без sshd; 2 попытки Hermes 2026-09-08 — Connection
  refused). Рабочий путь — **VPS bootstrap**: инстанс запускает
  `curl -sL http://5.181.202.112:8899/bootstrap.sh | sh` (веб-консоль vast или
  on-start script) → качает задания с VPS:8899 → гоняет worker → PUT результатов
  обратно. Образ уже собран и запушен: `tanerakajinn/2brain-worker:cuda`
  (torch 2.5.1 cu124, проверен Hermes). Инфра-состояние — в git на homelab
  `/opt/2brain` (дельта через `git log`); снимки Hermes: `2brain/HANDOFF-homelab.md`.

## Что построено

Second brain 2brain v2: Obsidian-хранилище + конвейер без NotebookLM и без внешних API.

- **Хранилище**: мастер на homelab `/srv/2brain` (git там же), Syncthing раздаёт на
  Windows-ПК (`C:\Users\Us\Vaults\2brain`) и Android. Зеркало в Google Drive —
  rclone каждый час (`/etc/periodic/hourly/2brain-mirror` на homelab), работает.
- **Демон**: `/opt/2brain/` на homelab, cron каждые 5 мин от пользователя `twobrain`
  (flock от наложений). ВСЕ файлы (PDF/DJVU/видео) → очередь `_Drop/_needs-gpu/`,
  статусы waiting_approval → карточки в `cards/` → согласование пользователем.
- **Шардирование**: worker.py режет PDF по SHARD_PAGES (по умолч. 60) страниц на
  части, часть — процесс на GPU (CUDA_VISIBLE_DEVICES), склейка по порядку.
  Протестировано на ПК: convert и OCR пути, склейка без потерь.
- **«Суть»**: подписочный ZCode, скилл `2brain-sutya` (этот репозиторий),
  ежедневно пн–пт 10:00. Внешних API нет.
- **Доктрина**: `/srv/2brain/CLAUDE.md` — правится только через /vault-calibrate
  с явным «да» пользователя. 10 полей frontmatter, статус queued-gpu.

## Доступы

- Homelab: `ssh root@192.168.2.9` (LAN) или `root@100.108.62.152` (NetBird).
  Сервисы Syncthing/демон работают под `twobrain` (файлы хранилища — её владение!).
- Репозиторий: https://github.com/Taner-Engineer/Z.ai.git (этот).
- Syncthing: мастер lenovoz500server + windows-renat-2 (рабочий ПК, сопряжён
  2026-09-07 после гибели старого identity), android, windows-21-00x1.

## Открытые хвосты

- Очередь: Уманский (1043 стр. OCR, job 2026-09-07-ca30d54b) и СП 56 (49 стр.
  convert, job 2026-09-07-1cea5cb1) ждут согласования. Исполнитель — ПК
  (`run_queue.py`) ИЛИ vast через VPS-bootstrap (см. выше). СП 155, СП 252,
  YT-курс Hermes — в базе, `queued`.
- Баги Hermes (в контейнере hermes-agent, исходники /usr/local/lib/hermes-agent):
  (1) z.ai 429-1308 не триггерит fallback-цепь; (2) aux-слот при фолбэке ушёл на
  ПЛАТНУЮ OpenRouter-модель. Одобренный, но несделанный: watchdog-крон квоты z.ai.
- Опция (не срочно): добавить openssh-server в образ воркера — вернёт SSH-деплой.
- ffmpeg на рабочем ПК не установлен — нужен только для STT
  (`winget install Gyan.FFmpeg`).
- DJVU→PDF (ddjvu/dpsprep) пока выполняется на homelab при enqueue — редкая
  лёгкая операция (~минуты на книгу); если пользователь захочет строго ноль —
  перенести в worker (нужен djvulibre на Windows).
- Автоматизация «Суть 10:00» живёт в workspace ZCode РАБОЧЕГО ПК — на другой
  машине создать заново (CronCreate, cron `0 10 * * 1-5`).

## Как продолжить на новой машине

1. `git clone https://github.com/Taner-Engineer/Z.ai.git && ./install.sh`
2. Прочитать этот HANDOFF.md и `/srv/2brain/CLAUDE.md` (доктрина).
3. Раннер очереди: venv + `pip install docling==2.123.0 faster-whisper yt-dlp pymupdf`,
   затем `win-worker/run_queue.py`.
