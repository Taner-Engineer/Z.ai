"""Конфигурация конвейера 2brain v2. Все пути и пороги — здесь."""
from pathlib import Path

# --- Хранилище ---
VAULT = Path("/srv/2brain")
INBOX = VAULT / "Inbox.md"
WATCHLIST = VAULT / "_Dashboards" / "Watchlist.md"
TEMPLATE = VAULT / "_Templates" / "Заметка.md"
RAW = VAULT / "_raw"
ATTACH = VAULT / "_Attachments"
KNOWLEDGE = VAULT / "Knowledge"
PROJECTS = VAULT / "Projects"

# --- Точка приёма ---
DROP = VAULT / "_Drop"
NEEDS_GPU = DROP / "_needs-gpu"
GPU_JOBS = NEEDS_GPU / "jobs"      # тяжёлые файлы, не синхронизируются (.stignore)
GPU_CARDS = NEEDS_GPU / "cards"    # карточки-эстимейты, синхронизируются — их видите вы
PROCESSED = DROP / "_processed"    # обработанные входы, не синхронизируются

# --- Состояние демона (вне хранилища) ---
STATE = Path("/opt/2brain/state")
LOG = RAW / "_daemon.log"

# --- Инструменты ---
WHISPER_BIN = "/opt/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "/opt/whisper.cpp/models/ggml-small.bin"
DOCLING_IMAGE = "docling:cpu"
DOCLING_CACHE = Path("/opt/2brain/model_cache")

# Сеть: DNS роутера блокирует YouTube (NXDOMAIN), поэтому внешние запросы
# yt-dlp/trafilatura идут через socks-прокси sing-box — он резолвит имена на выезде
PROXY_URL = "http://192.168.2.9:1080"
NO_PROXY = "localhost,127.0.0.1,192.168.0.0/16"

# --- Режимы ---
NIGHT_START = 1   # ночное окно тяжёлых локальных задач: [01:00, 06:00)
NIGHT_END = 6
HEAVY_MIN_RAM_MB = 3000   # свободно меньше — тяжёлое откладывается

# --- Пороги маршрутизации ---
PDF_CHARS_PER_PAGE = 150   # меньше в среднем — считается сканом
PDF_GPU_PAGES = 50         # скан длиннее — в GPU-очередь
VIDEO_LOCAL_MAX_SEC = 300  # видеофайл длиннее — в GPU-очередь
STABLE_SCANS = 2           # размер файла неизменен N сканов подряд — файл готов
MAX_ATTEMPTS = 3           # попыток на элемент, дальше — failed в отчёт

# --- Эстимейты GPU (для карточек) ---
VAST_RATE_4090 = 0.35   # $/час, класс RTX 4090
VAST_RATE_3090 = 0.20   # $/час, класс RTX 3090
STT_SPEED = 15          # faster-whisper large-v3: ~15x реального времени
OCR_SEC_PER_PAGE = 0.35 # docling GPU: ~0.2-0.5 сек/страница
