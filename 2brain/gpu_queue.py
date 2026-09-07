"""GPU-очередь: задание в _needs-gpu/jobs + карточка-эстимейт в _needs-gpu/cards.

Ничего не арендуется. Карточка показывает рекомендации по железу vast.ai
(GPU/CPU/RAM/диск), оценку времени и $, альтернативу на CPU и команду деплоя.
Согласование — днём, вами; запуск — deploy-vast.sh после вашего «да».

Задание бывает двух видов:
  - файловое: src (PDF/аудио) переносится в jobs/<id>/input.<ext>
  - URL: аудио скачает воркер прямо на инстансе (jobs/<id>/manifest.json -> input_url)
Манифест хранит путь заметки, чтобы после прогона демон смог довести её до queued.
"""
import datetime
import json
import shutil
import uuid
from pathlib import Path

import config


def _hardware(kind: str) -> str:
    if kind == "stt":
        return (
            "- **GPU**: >= 12 ГБ VRAM (RTX 3090 / 4090 / A5000). large-v3 fp16 ~6 ГБ "
            "+ буфер декодирования\n"
            "- **CPU**: >= 8 ядер (декод и подача аудио не должны стать узким местом)\n"
            "- **RAM**: >= 16 ГБ\n"
            "- **Диск**: >= 20 ГБ (модели ~4 ГБ + батч аудио + результат)"
        )
    return (
        "- **GPU**: >= 8 ГБ VRAM (RTX 3090 / 4090). Модели layout/OCR лёгкие, "
        "скорость дают тензорные ядра\n"
        "- **CPU**: >= 8 ядер (препроцессинг страниц идёт на CPU)\n"
        "- **RAM**: >= 16 ГБ (модели docling + буфер страниц)\n"
        "- **Диск**: >= 20 ГБ + объём батча PDF"
    )


def _estimate(kind: str, amount: float) -> tuple[float, float, float]:
    """-> (gpu_минуты, $ класс 4090, $ класс 3090)."""
    if kind == "stt":
        gpu_min = max(2.0, amount / config.STT_SPEED + 3)  # +3 мин: загрузка модели
    else:
        gpu_min = max(2.0, amount * config.OCR_SEC_PER_PAGE / 60 + 4)
    return gpu_min, gpu_min / 60 * config.VAST_RATE_4090, gpu_min / 60 * config.VAST_RATE_3090 * 1.4


def _alt_cpu(kind: str, amount: float) -> str:
    if kind == "stt":
        return f"CPU homelab (whisper.cpp small, ~1.5x реального времени): ~{amount / 1.5:.0f} мин, $0"
    return f"CPU homelab (docling OCR, ~10 с/стр): ~{amount * 10 / 60:.0f} мин, $0 — ноут будет занят"


def enqueue(kind: str, title: str, amount: float, note: Path | None = None,
            src: Path | None = None, url: str = "") -> str:
    """Поставить задание в очередь. Возвращает id. note — заметка (уже создана со
    статусом queued-gpu); src ИЛИ url задают вход."""
    job_id = datetime.date.today().isoformat() + "-" + uuid.uuid4().hex[:8]
    jdir = config.GPU_JOBS / job_id
    jdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": job_id,
        "kind": kind,          # stt | ocr
        "amount": round(amount, 1),
        "title": title,
        "note": str(note.relative_to(config.VAULT)) if note else "",
        "input_url": url,
        "status": "waiting_approval",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if src is not None:
        dest = jdir / ("input" + src.suffix.lower())
        shutil.move(str(src), str(dest))
        manifest["input"] = dest.name
    (jdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    gpu_min, c49, c39 = _estimate(kind, amount)
    amount_str = f"{amount:.0f} мин аудио" if kind == "stt" else f"{amount:.0f} страниц"
    card = (
        f"# GPU-задание {job_id}\n\n"
        f"**Что**: {'STT (faster-whisper large-v3)' if kind == 'stt' else 'OCR сканов (docling GPU)'} — "
        f"«{title}», {amount_str}\n\n"
        f"## Рекомендации по железу vast.ai\n{_hardware(kind)}\n\n"
        f"## Оценка\n"
        f"- GPU-время: ~{gpu_min:.0f} мин\n"
        f"- Стоимость: ~${c49:.2f} (класс RTX 4090) / ~${c39:.2f} (класс RTX 3090)\n"
        f"- Минимальная аренда может дать $0.10–0.20 сверх\n\n"
        f"## Альтернатива без аренды\n{_alt_cpu(kind, amount)}\n\n"
        f"## Запуск (после вашего «да»)\n"
        f"На homelab: `/opt/2brain/gpu-worker/deploy-vast.sh <IP-инстанса> {job_id}`\n"
        f"(без id — обработает ВСЮ папку _needs-gpu/jobs)\n\n"
        f"**ЖДУ ПОДТВЕРЖДЕНИЯ. Автоматически не запускается.**\n"
    )
    (config.GPU_CARDS / f"{job_id}.md").write_text(card, encoding="utf-8")
    return job_id


def pending_jobs() -> list[dict]:
    """Манифесты заданий, ожидающих прогона."""
    out = []
    if not config.GPU_JOBS.exists():
        return out
    for mf in sorted(config.GPU_JOBS.glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        m["_dir"] = mf.parent
        out.append(m)
    return out
