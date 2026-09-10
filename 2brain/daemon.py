#!/opt/2brain-venv/bin/python
"""Демон 2brain v2 — one-shot: один проход по _Drop и Inbox, выход.

Запуск: daemon.py --once   (cron каждые 5 мин; повтор защищён flock)
AI-вызовов нет: «Суть» пишется подписочным ZCode по понедельникам.

Прогон:
  1. _Drop: URL-списки -> дописать в Inbox.md (append-only), файл -> _processed
  2. _Drop: PDF/DJVU/видео -> стабильность размера -> маршрутизация
     (PDF/DJVU -> PDF -> GPU-очередь (рабочий ПК); видео >5 мин -> GPU-очередь)
  3. Inbox: строки '- [ ]' -> метаданные + транскрипт + заметка-заглушка, [x]
  4. _Drop/_results: вернувшиеся с GPU результаты -> довести заметки до queued
  5. Суточный отчёт в _raw/_daemon-report-ГГГГ-ММ-ДД.md
Конвертация/OCR/STT — ТОЛЬКО в очереди на мощное железо (рабочий ПК, vast.ai);
ночного окна и локальных тяжёлых задач больше нет.
"""
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import config
import gpu_queue
import processors
import router
import vault

STATE = config.STATE
STATS = {"done": 0, "errors": 0}


def log(msg: str):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    with open(config.LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ram_available_mb() -> int:
    with open("/proc/meminfo") as f:
        for ln in f:
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    return 0


# ---------- стабильность файлов в _Drop ----------

def stable_files() -> list[Path]:
    """Файлы _Drop (корень + подкаталоги маршрутизации Books/, Projects/<имя>/),
    размер которых не менялся STABLE_SCANS прогонов подряд. Служебные _-папки
    и файлы списков-ссылок вне корня не сканируются."""
    sizes_f = STATE / "sizes.json"
    sizes = json.loads(sizes_f.read_text()) if sizes_f.exists() else {}
    cur: dict[str, list] = {}
    ready: list[Path] = []
    if config.DROP.exists():
        candidates = list(config.DROP.iterdir())
        for d in candidates:
            if d.is_dir() and not d.name.startswith("_") and not d.name.startswith("."):
                candidates.extend(d.iterdir())  # один уровень: Books/, Projects/<имя>/
        for p in sorted(candidates):
            if not p.is_file() or p.name.startswith("."):
                continue
            size = p.stat().st_size
            prev = sizes.get(str(p))
            count = prev[1] + 1 if prev and prev[0] == size else 1
            cur[str(p)] = [size, count]
            if count >= config.STABLE_SCANS:
                ready.append(p)
    sizes_f.parent.mkdir(parents=True, exist_ok=True)
    sizes_f.write_text(json.dumps(cur))
    return ready


def drop_scope(p: Path) -> str:
    """Подкаталог _Drop задаёт маршрут: Books/ -> книги, Projects/<имя>/ -> проект."""
    try:
        rel = p.parent.relative_to(config.DROP)
    except ValueError:
        return "global"
    parts = rel.parts
    if parts[:1] == ("Books",):
        return "books"
    if len(parts) >= 2 and parts[0] == "Projects":
        return f"project/{parts[1]}"
    return "global"


# ---------- попытки (защита от вечных ретраев) ----------

def attempts_key(kind: str, ident: str) -> str:
    return f"{kind}:{ident}"


def bump_attempts(key: str) -> int:
    f = STATE / "attempts.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    data[key] = data.get(key, 0) + 1
    f.write_text(json.dumps(data))
    return data[key]


# ---------- шаг 1: URL-списки ----------

def consume_url_lists(files: list[Path]) -> None:
    inbox = vault.Inbox()
    for f in files:
        if f.suffix.lower() not in router.LIST_EXT:
            continue
        if f.parent != config.DROP:  # списки-ссылки живут только в корне _Drop
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        urls = [ln for ln in lines if router.is_url(ln.lstrip("- "))]
        if lines and len(urls) * 2 >= len(lines):  # большинство строк — ссылки
            items = [ln.lstrip("- ").strip() for ln in lines]
            inbox.append_captures(items)
            log(f"Inbox += {len(items)} строк из {f.name}")
        else:
            # это документ, а не список ссылок: полный текст во вложения
            dest = vault.attach_name(f.stem)
            dest.write_text(text, encoding="utf-8")
            note = vault.create_note(title=f.stem, ntype="doc", scope="global",
                                     source_url="", captured=vault.today(),
                                     raw="", tags=[])
            log(f"документ-заметка: {note.name}")
            STATS["done"] += 1
        _consume(f)


# ---------- шаг 2: файлы _Drop ----------

def handle_drop_file(p: Path) -> None:
    ext = p.suffix.lower()
    scope = drop_scope(p)
    if ext in router.VIDEO_EXT:
        info = router.video_info(p)
        res = processors.Result()
        res.title, res.ntype, res.scope = p.stem, ("reel" if info["vertical"] else "video"), scope
        # локально не расшифровываем: любое STT — в GPU-очередь
        note = vault.create_note(title=res.title, ntype=res.ntype, scope=scope,
                                 source_url="", captured=vault.today(), raw="", tags=[])
        vault.set_status(note, "queued-gpu")
        gpu_queue.enqueue("stt", res.title, info["duration"] / 60, note, src=p)
        log(f"GPU-очередь (STT {info['duration']/60:.0f} мин): {p.name}")
        STATS["done"] += 1
        return
    if ext == ".pdf":
        _handle_pdf(p, title_hint=p.stem, source_url="", scope=scope)
        return
    if ext in (".djvu", ".djv"):
        has_text = router.djvu_has_text(p)
        log(f"DJVU {p.name}: OCR-слой: {has_text}")
        pdf = processors.djvu_to_pdf(p, has_text)
        if pdf is None:
            log(f"ОШИБКА DJVU {p.name}: конвертация не удалась")
            STATS["errors"] += 1
            return
        _consume(p)
        _handle_pdf(pdf, title_hint=p.stem, source_url="", scope=scope,
                    src_has_text=has_text)
        return
    log(f"пропуск неизвестного типа: {p.name}")


def _handle_pdf(p: Path, title_hint: str, source_url: str, scope: str = "global",
                src_has_text: bool = False) -> None:
    """ВСЕ PDF — в очередь на мощное железо (рабочий ПК / vast.ai).
    CPU хоумлаба на конвертации не тратим вовсе."""
    info = router.pdf_analyze(p)
    if src_has_text and not info["text_layer"]:
        log(f"ОШИБКА {p.name}: у DJVU был OCR-слой, но в PDF текста нет — "
            f"потерян при конвертации (dpsprep упал? см. state/cron.log); уходит в OCR")
    log(f"PDF {p.name}: {info['pages']} стр., текст-слой: {info['text_layer']}")
    title = title_hint or p.stem
    note = vault.create_note(title=title, ntype="doc", scope=scope,
                             source_url=source_url, captured=vault.today(),
                             raw="", tags=[])
    vault.set_status(note, "queued-gpu")
    kind = "convert" if info["text_layer"] else "ocr"
    gpu_queue.enqueue(kind, title, info["pages"], note, src=p)
    log(f"GPU-очередь ({kind} {info['pages']} стр.): {p.name}")
    STATS["done"] += 1


def _finish_free_file(res: processors.Result, p: Path) -> None:
    """Файловый вход обработан: заметка + потребление исходника."""
    lead = ""
    if res.attach:
        lead = f"Полный текст: [[{res.attach[:-3]}]]"
    note = vault.create_note(title=res.title or p.stem, ntype=res.ntype or "doc",
                             scope=res.scope or "global", source_url=res.source_url,
                             captured=res.captured, raw=res.raw, tags=res.tags,
                             body_lead=lead)
    if not res.ok:
        vault.set_status(note, "queued")  # сырьё не готово — ZCode пропустит пустые
        log(f"ОШИБКА {p.name}: {res.error}")
        STATS["errors"] += 1
    else:
        STATS["done"] += 1
        log(f"заметка: {note.relative_to(config.VAULT)} [queued]")
    _consume(p)


def _consume(p: Path) -> None:
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    dest = config.PROCESSED / p.name
    n = 2
    while dest.exists():
        dest = config.PROCESSED / f"{p.stem}-{n}{p.suffix}"
        n += 1
    p.rename(dest)


# ---------- шаг 3: строки Inbox ----------

def handle_inbox() -> None:
    inbox = vault.Inbox()
    for no, line in inbox.pending_lines():
        body = re.sub(r"^\s*- \[ \] ", "", line).strip()
        rest, tags = vault.parse_inbox_tags(body)
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(.*)", rest)
        date, payload = (m.group(1), m.group(2).strip()) if m else (vault.today(), rest)
        if router.is_url(payload):
            _process_url_line(inbox, no, payload, tags, date)
        else:
            _process_titled_line(inbox, no, payload, tags, date)


def _process_titled_line(inbox: vault.Inbox, no: int, payload: str,
                         tags: list[str], date: str) -> None:
    """Захват без ссылки: #media или без типа -> Watchlist; с явным типом -> заглушка."""
    title, *tail = payload.split(" — ", 1)
    title = title.strip()
    comment = tail[0].strip() if tail else ""
    forced = vault.type_from_tags(tags)
    if forced in (None, "media"):
        vault.Watchlist().append(title, tags, comment)
        inbox.mark_done(no, "Watchlist")
        log(f"Watchlist += {title}")
        STATS["done"] += 1
        return
    note = vault.create_note(title=title, ntype=forced,
                             scope=_scope(tags), source_url="",
                             captured=date, raw="", tags=_plain_tags(tags))
    inbox.mark_done(no, vault.wiki_ref(note))
    log(f"заметка-заглушка: {note.name}")
    STATS["done"] += 1


def _scope(tags: list[str]) -> str:
    prj = vault.project_from_tags(tags)
    return f"project/{prj}" if prj else "global"


def _plain_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if not t.startswith(("type/", "project/"))]


def _process_url_line(inbox: vault.Inbox, no: int, url: str,
                      tags: list[str], date: str) -> None:
    kind = router.url_kind(url)
    scope = _scope(tags)
    plain = _plain_tags(tags)

    if kind == "yt":
        js = router.yt_metadata(url)
        if js is None:
            _fail_or_retry(inbox, no, "yt", url, f"yt-dlp: метаданные не получены ({url})")
            return
        title = js.get("title") or url
        vid = js.get("id") or url  # чистая ссылка без &list=: иначе yt-dlp тянет плейлист
        clean_url = f"https://www.youtube.com/watch?v={vid}" if vid != url else url
        if router.yt_has_subtitles(js):
            res = processors.do_yt_subs(clean_url, js)
            res.title, res.scope, res.captured, res.tags = title, scope, date, plain
            if res.ok:
                note = vault.create_note(title=res.title, ntype="video", scope=scope,
                                         source_url=url, captured=date,
                                         raw=res.raw, tags=plain)
                inbox.mark_done(no, vault.wiki_ref(note))
                log(f"заметка: {note.name} [queued]")
                STATS["done"] += 1
            else:
                _fail_or_retry(inbox, no, "yt", url, f"субтитры: {res.error}")
            return
        dur = (js.get("duration") or 300) / 60
        note = vault.create_note(title=title, ntype="video", scope=scope,
                                 source_url=url, captured=date, raw="", tags=plain)
        vault.set_status(note, "queued-gpu")
        gpu_queue.enqueue("stt", title, dur, note, url=url)
        inbox.mark_done(no, vault.wiki_ref(note))
        log(f"GPU-очередь (STT YT {dur:.0f} мин): {title}")
        STATS["done"] += 1
        return

    if kind == "instagram":
        res = _do_instagram(url)
        res.captured, res.scope, res.tags = date, scope, plain
        if getattr(res, "gpu_jid", None):
            inbox.mark_done(no, vault.wiki_ref(res.gpu_note))
            log(f"GPU-очередь (IG reel): {url}")
            STATS["done"] += 1
            return
        if res.ok:
            note = vault.create_note(title=res.title or url, ntype=res.ntype or "reel",
                                     scope=scope, source_url=url, captured=date,
                                     raw=res.raw, tags=plain)
            inbox.mark_done(no, vault.wiki_ref(note))
            STATS["done"] += 1
            log(f"заметка: {note.name} [queued]")
        else:
            _fail_or_retry(inbox, no, "ig", url, f"gallery-dl: {res.error}")
        return

    res = processors.do_article(url)
    res.captured, res.scope, res.tags = date, scope, plain
    if res.ok:
        note = vault.create_note(title=res.title, ntype="article", scope=scope,
                                 source_url=url, captured=date, raw=res.raw, tags=plain)
        inbox.mark_done(no, vault.wiki_ref(note))
        log(f"заметка: {note.name} [queued]")
        STATS["done"] += 1
    else:
        _fail_or_retry(inbox, no, "article", url, f"статья: {res.error}")


def _do_instagram(url: str) -> processors.Result:
    res = processors.Result()
    res.source_url, res.ntype, res.title = url, "reel", url
    import tempfile
    tmpd = Path(tempfile.mkdtemp(prefix="ig-", dir=config.STATE / "tmp"))
    subprocess.run(["/opt/2brain-venv/bin/gallery-dl", "-q", "-D", str(tmpd), url],
                   capture_output=True, text=True, timeout=300)
    media = [f for f in tmpd.rglob("*") if f.is_file()
             and f.suffix.lower() in router.VIDEO_EXT | {".jpg", ".png", ".webp"}]
    if not media:
        res.ok = False
        res.error = "ничего не скачалось (ссылка умерла / нужна авторизация)"
        return res
    m0 = max(media, key=lambda f: f.stat().st_size)
    res.title = (m0.stem[:80] or url)
    if m0.suffix.lower() in router.VIDEO_EXT:
        info = router.video_info(m0)
        # локально не расшифровываем: рилсы тоже уходят в GPU-очередь
        note = vault.create_note(title=res.title, ntype="reel", scope=res.scope,
                                 source_url=url, captured=vault.today(),
                                 raw="", tags=[])
        vault.set_status(note, "queued-gpu")
        jid = gpu_queue.enqueue("stt", res.title, info["duration"] / 60,
                                note, src=m0, url=url)
        res.gpu_jid, res.gpu_note = jid, note
        return res
    dest = vault.attach_name(res.title, m0.suffix.lstrip("."))
    dest.write_bytes(m0.read_bytes())
    res.attach = str(dest.relative_to(config.VAULT))
    return res


def _fail_or_retry(inbox: vault.Inbox, no: int, kind: str, ident: str, msg: str) -> None:
    n = bump_attempts(attempts_key(kind, ident))
    if n >= config.MAX_ATTEMPTS:
        inbox.mark_done(no, "⚠️ failed (см. _daemon.log)")
        log(f"FAILED после {n} попыток — {msg}")
        STATS["errors"] += 1
    else:
        log(f"попытка {n}/{config.MAX_ATTEMPTS} не удалась, остаёмся в очереди — {msg}")


# ---------- шаг 4: результаты с GPU ----------

def collect_gpu_results() -> None:
    """deploy-vast.sh кладёт результат в _Drop/_results/<job>/output.* + manifest.
    Доводим заметку до queued: raw/attach заполняются, статус меняется."""
    resdir = config.DROP / "_results"
    if not resdir.exists():
        return
    for jdir in sorted(resdir.iterdir()):
        if not jdir.is_dir():
            continue
        mf = jdir / "manifest.json"
        if not mf.exists():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if m.get("status") != "done":
            continue
        out = jdir / m.get("output", "")
        if not out.exists():
            continue
        note_rel = m.get("note")
        note = config.VAULT / note_rel if note_rel else None
        if m["kind"] == "ocr":
            dest = vault.attach_name(m.get("title") or out.stem)
            dest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
            raw = ""
        else:
            dest = vault.raw_name("transcript", m["id"], "txt")
            shutil_text = out.read_text(encoding="utf-8", errors="replace")
            dest.write_text(shutil_text, encoding="utf-8")
            raw = str(dest.relative_to(config.VAULT))
        if note and note.exists():
            text = note.read_text(encoding="utf-8")
            if raw:
                text = re.sub(r'(^raw: )"([^"]*)"', rf'\1"{raw}"', text, count=1, flags=re.M)
            note.write_text(text, encoding="utf-8")
            vault.set_status(note, "queued")
            log(f"GPU-результат {m['id']}: заметка {note.name} -> queued")
        jdir.rename(config.PROCESSED / jdir.name)
        STATS["done"] += 1


# ---------- шаг 6: суточный отчёт ----------

def daily_report() -> None:
    f = config.RAW / f"_daemon-report-{vault.today()}.md"
    if f.exists():
        return
    jobs = gpu_queue.pending_jobs()
    waiting = [m for m in jobs if m.get("status") == "waiting_approval"]
    lines = [
        f"# Отчёт демона {vault.today()}",
        "",
        f"- обработано: {STATS['done']}",
        f"- ошибок: {STATS['errors']}",
        f"- в GPU-очереди: {len(waiting)} заданий — карточки в _Drop/_needs-gpu/cards/, согласовать днём",
        f"- свободно RAM: {ram_available_mb()} МБ",
        "",
    ]
    for m in waiting:
        lines.append(f"- {m['id']}: {m['kind']} «{m['title']}» ({m['amount']})")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"суточный отчёт: {f.name}")


# ---------- прогон ----------

def once() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "tmp").mkdir(parents=True, exist_ok=True)
    config.DROP.mkdir(parents=True, exist_ok=True)
    config.GPU_CARDS.mkdir(parents=True, exist_ok=True)
    # DNS роутера блокирует YouTube: внешние запросы через socks-прокси sing-box
    os.environ.setdefault("HTTP_PROXY", config.PROXY_URL)
    os.environ.setdefault("HTTPS_PROXY", config.PROXY_URL)
    os.environ.setdefault("NO_PROXY", config.NO_PROXY)

    files = stable_files()
    consume_url_lists(files)
    for p in files:
        if p.suffix.lower() in router.LIST_EXT or not p.exists():
            continue
        handle_drop_file(p)
    handle_inbox()
    collect_gpu_results()
    daily_report()


if __name__ == "__main__":
    if "--once" not in sys.argv:
        print("только режим --once (cron); резидентного процесса нет")
        sys.exit(1)
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / "daemon.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # предыдущий прогон ещё работает — не мешаем
    once()
