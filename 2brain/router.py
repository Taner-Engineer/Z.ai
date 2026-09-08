"""Детект типа входа: URL против файла, анализ PDF/DJVU/видео."""
import json
import subprocess
from pathlib import Path

import config

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"}
LIST_EXT = {".txt", ".md"}
YT_HOSTS = ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com")


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def url_kind(url: str) -> str:
    """yt | instagram | article"""
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if any(h in host for h in YT_HOSTS):
        return "yt"
    if "instagram.com" in host:
        return "instagram"
    return "article"


def yt_metadata(url: str) -> dict | None:
    """yt-dlp -J --skip-download; None при сбое (сеть/геоблок). --no-playlist:
    URL с &list=... отдаёт метаданные только самого видео."""
    try:
        r = subprocess.run(
            ["/usr/local/bin/yt-dlp", "-J", "--no-warnings", "--no-playlist",
             "--skip-download", url],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return None
        js = json.loads(r.stdout)
        if "_type" in js and js.get("_type") == "playlist":
            js = js["entries"][0]
        return js
    except Exception:
        return None


def yt_has_subtitles(js: dict) -> bool:
    subs = js.get("subtitles") or {}
    auto = js.get("automatic_captions") or {}
    for lang in ("ru", "en"):
        if subs.get(lang) or auto.get(lang):
            return True
    return False


def video_info(path: Path) -> dict:
    """Длительность и вертикальность через ffprobe."""
    def probe(arg: str) -> str:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", arg,
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return r.stdout.strip()

    dur = probe("format=duration")
    try:
        duration = float(dur)
    except ValueError:
        duration = 0.0
    w, h = probe("stream=width"), probe("stream=height")
    try:
        vertical = int(h or 0) > int(w or 0)
    except ValueError:
        vertical = False
    return {"duration": duration, "vertical": vertical}


def pdf_analyze(path: Path) -> dict:
    """Преданализ PDF: есть ли текстовый слой, сколько страниц (pymupdf)."""
    import pymupdf
    doc = pymupdf.open(path)
    n = doc.page_count
    sample = min(n, 15)
    chars = sum(len(page.get_text().strip()) for page in doc.pages(0, sample, 1))
    doc.close()
    avg = chars / sample if sample else 0
    return {"pages": n, "text_layer": avg >= config.PDF_CHARS_PER_PAGE,
            "chars_per_page": round(avg)}


def djvu_has_text(path: Path) -> bool:
    """Есть ли в DJVU встроенный OCR-слой (djvutext извлекает скрытый текст)."""
    try:
        r = subprocess.run(["djvutxt", str(path)], capture_output=True, timeout=300)
        return len(r.stdout.strip()) > 500
    except Exception:
        return False
