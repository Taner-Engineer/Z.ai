# HANDOFF — 2brain v2 → Zcode (снимок 3, 2026-09-10)

> **Правило обслуживания**: снимок на момент передачи. Дельта между передачами — `git log`.
> Предыдущий снимок: 2 (2026-09-08 вечер).

## Дельта до снимка 3 (2026-09-10, ZCode flash)

### 1. Фикс dpsprep (e7d4573, processors.py)
- `-q` у dpsprep — это `--quality`, а НЕ quiet: старый вызов падал, фолбэк на
  ddjvu молча терял OCR-слой. Теперь `--quality 85`; при падении dpsprep stderr
  пишется в cron.log.
- DJVU→PDF остаётся на homelab НАВСЕГДА: dpsprep требует C-биндинги
  djvulibre-python, на Windows нужен WSL (не установлен, админ-права +
  перезагрузка) — перенос на рабочий ПК отвергнут. dpsprep 2.8.3, ~2 мин на
  книгу 1043 стр. на 4 ядрах homelab.

### 2. Проверка текст-слоя (6427f08, router.py + daemon.py)
- `router.pdf_analyze` меряет текст в 15 страницах из СЕРЕДИНЫ книги (титульные
  давали ложное «нет слоя»); `daemon._handle_pdf(src_has_text=)` пишет ERROR в
  _daemon.log, если у DJVU был OCR-слой, а в PDF текста нет.
- Валидация на «Уманском»: 1043 стр. за ~2 мин, 4666 симв./стр. — такая книга
  идёт как `convert` (docling без OCR, минуты), а не `ocr` (1,5 ч). Тесты:
  `2brain/tests/` — 7 unittest, зелёные на Windows (venv воркера) и на homelab
  (/opt/2brain-venv).

### 3. Docling только на GPU-воркере (2cfb8a7, f2028ce) — требование владельца
- Локальный docling:cpu-контейнер удалён из кода homelab (−87 строк:
  do_pdf/_docling_convert/convert_one). ВСЕ PDF/DJVU идут через GPU-очередь на
  рабочий ПК. Воркер на RTX 3050 6 ГБ:
  - torch 2.14.0+cu130 (обычный `pip install torch==2.14.0` с cu-индексом
    промахивается — pip считает установленную +cpu удовлетворяющей);
  - onnxruntime-gpu 1.29.0 вместо onnxruntime — OCR-движок docling (RapidOCR,
    onnx) сам ставит CUDAExecutionProvider первым;
  - `worker.py::_ensure_cuda_dlls()` подкладывает CUDA/cuDNN DLL из torch/lib в
    PATH — без него ORT тихо падает в CPU («cublasLt64_13.dll is missing»);
    провайдеры [CPU]→[CUDA, CPU], smoke-тест 12 стр. — код 0.
  - Прочие версии venv воркера: docling 2.123.0, rapidocr 3.9.2, pymupdf 1.28.2,
    faster-whisper 1.2.1.

### 4. Deploy-состояние
- Homelab /opt/2brain: daemon.py, router.py, processors.py, config.py, worker.py
  — синхронны зеркалу (md5 сверены). Бэкапы на месте: `*.bak-q`,
  `*.bak-txtcheck`, `convert_one.py.bak-docling`.
- Docker-образ docling:cpu и `/opt/2brain/model_cache` больше не используются
  кодом — можно удалить вручную при чистке диска.
- Рабочий ПК: код воркера `C:\Users\Us\zcode-sync\2brain\gpu-worker\worker.py`,
  venv `C:\Users\Us\2brain-worker\venv` (torch cu130 + onnxruntime-gpu).

Рекомендации «Порядок действий» снимка 2 устарели: оба GPU-задания выполнены
2026-09-08; Hermes-хвосты (п.5 снимка 2) не тронуты.

## Статус репозиториев
- `/srv/2brain` (vault): последний коммит `c1177d4`
- `/opt/2brain` (infra): см. новый коммит этого снимка; после 39f19c3/708c72f добавлены
  deploy-direct.sh, push-image.sh, push-image-vps.sh, Dockerfile-фикс (torch cu124)

## Дельта сессии Hermes №2 (2026-09-08, день)

### 1. Vision-фикс (Hermes)
- Живым тестом: glm-5.3 на coding-endpoint ОТВЕРГАЕТ картинки (code 1210,
  allowed: text), glm-5.3-flash ПРИНИМАЕТ.
- aux-слот vision переключён на zai/glm-5.3-flash в config.yaml Hermes.
- `agent.image_input_mode: text` прописан, но ТРЕБУЕТ рестарта gateway (не сделан).

### 2. Инфраструктура деплоя
- **deploy-direct.sh** — для топологии «SSH попадает прямо в контейнер нашего образа»
  (Launch mode: Docker ENTRYPOINT): scp worker.py + jobs, запуск python3 worker.py,
  забор results, отметка sent. НЕ испытан на живом инстансе.
- **push-image.sh / push-image-vps.sh** — публикация образа (Docker Hub + Drive-бэкап /
  tarball на VPS). Образ: `tanerakajinn/2brain-worker:cuda` в Docker Hub (10.8 ГБ,
  digest sha256:573bde1d), бэкап в gdrive:2brain/images/. Креды docker.io на homelab
  (/root/.docker/config.json, login выполнен).
- **Dockerfile-фикс**: torch 2.5.1 + torchvision 0.20.1, cu124 (2.13.0 не существует
  для cu121 — сборка падала). Образ собран и запушен.

### 3. VPS bootstrap-сервер (ГОТОВ, РАБОТАЕТ)
- `/root/deploy2brain/` на VPS 5.181.202.112, python3-server на порту **8899**
  (GET раздаёт файлы, PUT принимает results.tgz). Порт 8080 занят qr-dashboard!
- Раздаёт: `bootstrap.sh`, `gpu-jobs.tgz` (104 МБ, оба задания), `worker.py`
- Сценарий: инстанс выполняет `curl -sL http://5.181.202.112:8899/bootstrap.sh | sh`
  → качает задания → worker.py → результаты PUT обратно на VPS → забрать с homelab.
- После успешного прогона сервер можно погасить (pkill -f deploy2brain).

### 4. vast.ai — ДВЕ попытки, обе упёрлись в SSH (ГЛАВНЫЙ ОТКРЫТЫЙ ВОПРОС)
- SSH-ключ: пара `/root/.ssh/id_ed25519` (homelab, комментарий 2brain-vast),
  pubkey добавлен в аккаунт vast.ai; приватная половина скопирована на VPS.
- **Попытка 1** (121.167.252.172, RTX 4090 16vCPU/64GB, $0.008/ч): режим Interactive
  SSH + наш образ БЕЗ sshd → оба маршрута (direct/proxy) Connection refused.
- **Попытка 2** (71.17.164.141, Docker ENTRYPOINT + `sleep infinity`): порты
  51060/18570 — тоже Connection refused. Инстанс удалён пользователем до диагностики.
- **Урок**: наш кастомный образ не содержит sshd; vast Interactive-SSH рассчитан на
  свои базовые образы. Варианты: (a) добавить openssh-server в Dockerfile образа
  (пересборка ~25 мин + repush), (b) разобраться с On-start Script обвязкой vast,
  (c) веб-терминал Instance Portal (требует SSH-ключ в профиле — уже добавлен),
  (d) vast CLI (vastai) с API-ключом вместо ручной панели.
- Критерии машины (проверены на попытке 1 — идеальны): 4090, 16 vCPU, 64GB RAM,
  NVMe, ≥400 Мбит, internet $/GB низкий (на скрине было ~$0.002/GB).

### 5. Квота-инцидент z.ai (ВАЖНО — незакрытые баги)
- 2026-09-08 11:11 — z.ai 429 code **1308** «Usage limit reached for 5 hour»
  (сброс 20:36). Пользователь обновил подписку/лимит сам.
- **Баг 1**: fallback-цепь Hermes НЕ включилась — 6 ретраев только на zai
  (attempt 1/3), ни одной попытки TokenRouter/openrouter. 429-1308 не триггерит
  провал на следующий провайдер. Не починено.
- **Баг 2**: в 09:06 aux-слот ушёл на ПЛАТНУЮ OpenRouter-модель
  (google/gemini-3.6-flash) во время фолбэка — нарушение $0-доктрины aux-слотов.
  Не починено.
- **Не сделано** (пользователь одобрил «да делай», но прервано передачей):
  watchdog-крон 15 мин: проба z.ai мини-запросом; при 429/1308 — сообщение
  пользователю «лимит исчерпан, сброс HH:MM» + проверка куда идёт трафик.

### 6. GPU-задания — НЕ ВЫПОЛНЕНЫ (статус waiting_approval, не менялся)
- СП 56.13330.2021 (49 стр., convert) — jobs/2026-09-07-1cea5cb1
- Уманский 1960 (1043 стр., OCR) — jobs/2026-09-07-ca30d54b
- Оба в `gpu-jobs.tgz` на VPS:8899 И в `/srv/2brain/_Drop/_needs-gpu/jobs/`
- Воркер с динамическим чанкингом НЕ прогнан на GPU ни разу — телеметрии нет.

## Порядок действий для Zcode (рекомендация)
1. Починить SSH-путь на vast (п.4) — вероятнее всего (a): sshd в образ.
2. Прогнать оба задания (deploy-direct.sh или bootstrap), забрать телеметрию.
3. Починить баги п.5 (fallback 1308 + платный aux-фолбэк) — в исходниках Hermes
   /usr/local/lib/hermes-agent (на homelab-контейнере hermes-agent).
4. Watchdog квоты z.ai.

## Догмы (не менять без /vault-calibrate)
- Inbox.md append-only; 10 полей frontmatter; статусы queued/extracted/reviewed + queued-gpu
- GPU — только карточка-эстимейт + явное «да» пользователя
- «Суть» — только подписочный ZCode, не API демона
- Хоумлаб слабый: никаких тяжёлых задач локально (сборка образа ок, инференс нет)
