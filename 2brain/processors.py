"""Обработчики: скачивание и извлечение текста. AI-вызовов здесь нет — только $0."""
import json
import sys
import time
import re
import shutil
import subprocess
from pathlib import Path

import config
import router
import vault


class Result:
    """Итог обработки одного элемента."""
    def __init__(self):
        self.title = ""
        self.ntype = "article"
        self.scope = "global"
        self.source_url = ""
        self.captured = vault.today()
        self.raw = ""            # путь в _raw/
        self.attach = ""         # путь в _Attachments/ для полных MD
        self.tags: list[str] = []
        self.watchlist = False   # media — только строка в Watchlist
        self.gpu: dict | None = None  # карточка GPU-задания, если элемент ушёл в очередь
        self.ok = True
        self.error = ""


def _venv_run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# --- YouTube ---

def do_yt_subs(url: str, js: dict) -> Result:
    """Скачать субтитры (ru/en, manual или auto) и превратить в чистый текст."""
    res = Result()
    res.source_url = url
    res.ntype = "video"
    res.title = js.get("title") or url
    ident = js.get("id") or "yt"
    meta = vault.raw_name("youtube", ident)
    meta.write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    res.raw = str(meta.relative_to(config.VAULT))

    tmp = config.STATE / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    # Выходной IP прокси ловит HTTP 429 на CDN субтитров — качаем с повторами,
    # паузами и фолбэком: manual ru+en -> auto ru+en -> auto en
    attempts = [
        ["--write-subs", "--sub-langs", "ru,en"],
        ["--write-auto-subs", "--sub-langs", "ru,en"],
        ["--write-auto-subs", "--sub-langs", "en"],
    ]
    files = []
    for i, extra in enumerate(attempts):
        subprocess.run(
            ["/usr/local/bin/yt-dlp", *extra, "--no-playlist", "--retries", "4",
             "--sleep-requests", "2", "--skip-download", "--convert-subs", "vtt",
             "-o", str(tmp / f"{ident}"), url],
            capture_output=True, text=True, timeout=300)
        files = sorted(tmp.glob(f"{ident}*.vtt"))
        if files:
            break
        if i < len(attempts) - 1:
            time.sleep(25)
    files = sorted(tmp.glob(f"{ident}*.vtt"))
    if not files:
        res.ok = False
        res.error = "субтитры не скачались, хотя метаданные говорили обратное"
        return res

    text = _vtt_to_text(files[0].read_text(encoding="utf-8", errors="replace"))
    for f in files:
        f.unlink()
    tr = vault.raw_name("transcript", ident, "txt")
    tr.write_text(text, encoding="utf-8")
    res.raw = str(tr.relative_to(config.VAULT))
    return res


def _vtt_to_text(vtt: str) -> str:
    lines, seen = [], set()
    for ln in vtt.splitlines():
        ln = ln.strip()
        if (not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:",
                "NOTE")) or ln.isdigit()):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        if ln in seen:
            continue
        seen.add(ln)
        lines.append(ln)
    return "\n".join(lines) + "\n"


# --- Статья ---

def do_article(url: str) -> Result:
    res = Result()
    res.source_url = url
    import trafilatura
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        res.ok = False
        res.error = "страница не скачалась"
        return res
    text = trafilatura.extract(downloaded, include_comments=False) or ""
    if len(text.strip()) < 100:
        res.ok = False
        res.error = "текст не извлёкся (страница пустая или JS-only)"
        return res
    meta = trafilatura.extract_metadata(downloaded)
    res.title = (meta.title if meta and meta.title else url.split("//")[-1][:80])
    ident = re.sub(r"[^\w-]", "", url.split("//")[-1])[:60] or "article"
    raw = vault.raw_name("article", ident, "txt")
    raw.write_text(text, encoding="utf-8")
    res.raw = str(raw.relative_to(config.VAULT))
    return res


# --- Видео/рилс локально (whisper.cpp) ---

def do_video_local(path: Path, info: dict) -> Result:
    """Короткое видео: ffmpeg -> wav 16k mono -> whisper-cli. Тяжёлое, nice."""
    res = Result()
    res.ntype = "reel" if info.get("vertical") else "video"
    res.title = path.stem
    tmp = config.STATE / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    wav = tmp / (path.stem + ".wav")
    r = subprocess.run(
        ["nice", "-n", "10", "ffmpeg", "-y", "-i", str(path), "-vn",
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not wav.exists():
        res.ok = False
        res.error = f"ffmpeg: {r.stderr[-300:]}"
        return res
    txt = tmp / (path.stem + ".txt")
    r = subprocess.run(
        ["nice", "-n", "10", config.WHISPER_BIN, "-m", config.WHISPER_MODEL,
         "-l", "auto", "-otxt", "-of", str(txt.with_suffix("")), "-f", str(wav)],
        capture_output=True, text=True, timeout=7200)
    wav.unlink(missing_ok=True)
    out = txt if txt.exists() else txt.with_suffix(".txt")
    if r.returncode != 0 or not out.exists():
        res.ok = False
        res.error = f"whisper: {r.stderr[-300:]}"
        return res
    text = out.read_text(encoding="utf-8", errors="replace")
    out.unlink()
    raw = vault.raw_name("transcript", path.stem, "txt")
    raw.write_text(text, encoding="utf-8")
    res.raw = str(raw.relative_to(config.VAULT))
    if not text.strip():
        res.ok = False
        res.error = "транскрипт пуст (в видео нет речи?)"
    return res


# --- DJVU -> PDF ---

def djvu_to_pdf(path: Path, has_text: bool) -> Path | None:
    """Есть OCR-слой -> dpsprep (сохраняет текст); нет -> ddjvu (картинка).
    Результат кладётся в _Drop: демон подхватит его как обычный PDF-вход
    (скан уйдёт в ночное окно или GPU-очередь как положено)."""
    config.DROP.mkdir(parents=True, exist_ok=True)
    out = config.DROP / (path.stem + ".pdf")
    if out.exists():
        out = config.DROP / f"{path.stem}-{int(path.stat().st_size) % 10000}.pdf"
    if has_text:
        # у dpsprep нет «quiet»: -q это --quality (int), флаг без значения
        # ронял конвертер и молча уходили на ddjvu без текста
        r = _venv_run(["/opt/2brain-venv/bin/dpsprep", "--quality", "85",
                       str(path), str(out)], timeout=3600)
        if r.returncode == 0 and out.exists():
            return out
        # фолбэк ниже потеряет OCR-слой — оставляем след в cron.log
        print(f"dpsprep rc={r.returncode}, OCR-слой теряется: "
              f"{(r.stderr or r.stdout or '')[-300:].strip()}",
              file=sys.stderr, flush=True)
    r = subprocess.run(["ddjvu", "-format=pdf", "-quality=85",
                        str(path), str(out)], capture_output=True, timeout=3600)
    return out if (r.returncode == 0 and out.exists()) else None
