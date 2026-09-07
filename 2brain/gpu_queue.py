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
    home = ("- **Рабочий ПК** (i7-14700KF, RTX 3050): свой, $0 — рекомендуемое место по умолчанию\n"
            "- **vast.ai**: когда ПК занят/выключен или батч огромный\n")
    if kind == "stt":
        return home + (
            "- GPU: >= 12 ГБ VRAM для large-v3 fp16 (RTX 3090/4090); 3050 6 ГБ — int8, медленнее, но работает\n"
            "- CPU: >= 8 ядер (декод и подача аудио)\n"
            "- RAM: >= 16 ГБ; диск >= 20 ГБ (модели ~4 ГБ)\n"
        )
    if kind == "convert":
        return home + (
            "- Почти не зависит от GPU: упор в CPU (docling без OCR парсит текст)\n"
            "- Рабочий ПК: ~0.5-1 с/страница; vast.ai GPU: ~0.15 с/страница — брать дешёвый инстанс\n"
            "- RAM: >= 16 ГБ; диск >= 20 ГБ\n"
        )
    return home + (
        "- GPU: >= 8 ГБ VRAM (RTX 3090 / 4090); модели layout/OCR лёгкие, скорость дают тензорные ядра\n"
        "- CPU: >= 8 ядер (препроцессинг страниц); RAM >= 16 ГБ; диск >= 20 ГБ + объём батча\n"
    )


def _estimate(kind: str, amount: float) -> tuple[float, float, float]:
    """-> (gpu_минуты, $ класс 4090, $ класс 3090)."""
    if kind == "stt":
        gpu_min = max(2.0, amount / config.STT_SPEED + 3)  # +3 мин: загрузка модели
    elif kind == "convert":
        gpu_min = max(1.0, amount * 0.15 / 60 + 2)
    else:
        gpu_min = max(2.0, amount * config.OCR_SEC_PER_PAGE / 60 + 4)
    return gpu_min, gpu_min / 60 * config.VAST_RATE_4090, gpu_min / 60 * config.VAST_RATE_3090 * 1.4


def _alt_cpu(kind: str, amount: float) -> str:
    return f"Рабочий ПК (i7-14700KF): свой, $0 — запуск run_queue.py (см. карточку)"


def enqueue(kind: str, title: str, amount: float, note: Path | None = None,
            src: Path | None = None, url: str = "", ocr: bool | None = None) -> str:
    """Поставить задание в очередь. kind: stt | ocr | convert.
    Для pdf-заданий ocr=True/False управляет режимом docling (скан/текст-слой)."""
    job_id = datetime.date.today().isoformat() + "-" + uuid.uuid4().hex[:8]
    jdir = config.GPU_JOBS / job_id
    jdir.mkdir(parents=True, exist_ok=True)
    if ocr is None:
        ocr = kind != "convert"
    manifest = {
        "id": job_id,
        "kind": kind,          # stt | ocr | convert
        "ocr": ocr,
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
    kind_name = {"stt": "STT (faster-whisper large-v3)",
                 "ocr": "OCR сканов (docling GPU)",
                 "convert": "Конвертация PDF с текст-слоем (docling без OCR)"}[kind]
    card = (
        f"# GPU-задание {job_id}\n\n"
        f"**Что**: {kind_name} — «{title}», {amount_str}\n\n"
        f"## Рекомендации по железу\n{_hardware(kind)}\n\n"
        f"## Оценка (vast.ai)\n"
        f"- GPU-время: ~{gpu_min:.0f} мин\n"
        f"- Стоимость: ~${c49:.2f} (класс RTX 4090) / ~${c39:.2f} (класс RTX 3090)\n"
        f"- Минимальная аренда может дать $0.10–0.20 сверх\n\n"
        f"## Без аренды\n{_alt_cpu(kind, amount)}\n\n"
        f"## Запуск (после вашего «да»)\n"
        f"- Рабочий ПК: `run_queue.py` в C:\\Users\\Us\\2brain-worker (заберёт все карточки)\n"
        f"- vast.ai: арендовать инстанс по рекомендациям выше, затем на homelab "
        f"`/opt/2brain/gpu-worker/deploy-vast.sh <IP-инстанса> {job_id}`\n\n"
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
