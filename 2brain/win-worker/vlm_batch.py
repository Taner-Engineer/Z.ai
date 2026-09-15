# -*- coding: utf-8 -*-
"""VLM-транскрипция PDF -> Markdown через GLM (z.ai API), параллельно.

Портирован с /root/vlm_transcribe.py (homelab) под ПК: рендер через pymupdf
(без poppler), ключ C:\\Users\\Us\\2brain-worker\\.zai_key, устойчивость
(resume по страницам), лимиты для пилота.

Режимы:
  python vlm_batch.py --dir "<папка раздела с PDF>" [--limit N] [--dry N]
    --limit N  обработать не более N файлов
    --dry N    пилот: N страниц на файл, результат в vlm/preview/, в базу НЕ писать
Выход (обычный режим): Normatives/<имя>.md + заметка _llm/notes/<имя>.md
(status queued — Карту допишет утренний батч), реестр перегенерируется.
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

WORKER = Path(r"C:\Users\Us\2brain-worker")
VAULT = Path(r"C:\Users\Us\Vaults\2brain")
KEY_FILE = WORKER / ".zai_key"
API = "https://api.z.ai/api/coding/paas/v4/chat/completions"
MODELS = ["glm-5.3-flash", "glm-4.6v-flash"]  # второй — фолбэк, если первый не примет картинку
TEMPERATURE = 0.1
MAX_TOKENS = 8192
TIMEOUT = 180
CONCURRENCY = 3
DPI = 150
JPEG_QUALITY = 87

PROMPT = """Перепиши отсканированную страницу русскоязычного нормативного или
технического документа в Markdown. Правила: 1) Весь русский текст дословно,
с абзацами; ничего не исправляй, не переводи, не сокращай. 2) Формулы — LaTeX:
выключные в $$…$$, строчные в $…$; греческие буквы командами LaTeX.
3) Таблицы — Markdown-таблицы. 4) Рисунки не описывай; ссылки вида «Рис. 1»
оставь текстом. 5) Нечитаемое помечай [нечитаемо]. 6) Выведи ТОЛЬКО документ
Markdown, без комментариев."""

T0 = time.time()
STATS = {"ok": 0, "skip": 0, "err": 0, "ptok": 0, "ctok": 0}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_key():
    return KEY_FILE.read_text(encoding="utf-8").strip()


def vlm_call(model, b64, key):
    body = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ],
        }],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ans = json.loads(r.read())
    content = ans["choices"][0]["message"]["content"]
    usage = ans.get("usage", {})
    return content, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def render_b64(pdf_path, page_no):
    """Страница (1-based) -> JPEG base64, кэш на диске."""
    import pymupdf
    cache = pdf_state_dir(pdf_path) / f"p{page_no:04d}.jpg"
    if cache.exists():
        return base64.b64encode(cache.read_bytes()).decode()
    doc = pymupdf.open(pdf_path)
    pix = doc[page_no - 1].get_pixmap(dpi=DPI)
    doc.close()
    data = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    cache.write_bytes(data)
    return base64.b64encode(data).decode()


def pdf_state_dir(pdf_path):
    import hashlib
    h = hashlib.md5(str(pdf_path).encode()).hexdigest()[:10]
    d = WORKER / "vlm" / f"{Path(pdf_path).stem[:50]}_{h}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process_page(pdf_path, page_no, key, model_holder):
    state = pdf_state_dir(pdf_path) / f"p{page_no:04d}.json"
    if state.exists():
        d = json.loads(state.read_text(encoding="utf-8"))
        STATS["ok"] += 1
        STATS["ptok"] += d.get("ptok", 0)
        STATS["ctok"] += d.get("ctok", 0)
        return page_no, d.get("md", "")
    b64 = render_b64(pdf_path, page_no)
    if len(b64) < 2000:  # пустая страница
        STATS["skip"] += 1
        state.write_text(json.dumps({"md": ""}), encoding="utf-8")
        return page_no, ""
    for delay in (15, 45, 120, 300):
        try:
            model = model_holder[0]
            md, pt, ct = vlm_call(model, b64, key)
            state.write_text(json.dumps({"md": md, "ptok": pt, "ctok": ct, "model": model}),
                             encoding="utf-8")
            STATS["ok"] += 1
            STATS["ptok"] += pt
            STATS["ctok"] += ct
            return page_no, md
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")[:300]
            if ("image" in err.lower() or e.code in (400, 415)) and model_holder[0] != MODELS[1]:
                model_holder[0] = MODELS[1]  # модель не ест картинки -> фолбэк
                log(f"модель не приняла картинку, фолбэк на {MODELS[1]}")
                continue
            log(f"стр {page_no}: HTTP {e.code}, пауза {delay}с")
        except Exception as e:
            log(f"стр {page_no}: {type(e).__name__} {e}, пауза {delay}с")
        time.sleep(delay)
    STATS["err"] += 1
    return page_no, None


def transcribe_pdf(pdf_path, key, dry_pages=0):
    import pymupdf
    doc = pymupdf.open(pdf_path)
    n = doc.page_count
    doc.close()
    pages = range(1, min(n, dry_pages) + 1) if dry_pages else range(1, n + 1)
    model_holder = [MODELS[0]]
    results = {}
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(process_page, pdf_path, p, key, model_holder): p for p in pages}
        for i, f in enumerate(as_completed(futs), 1):
            p, md = f.result()
            results[p] = md
            if i % 25 == 0:
                log(f"  {Path(pdf_path).name[:40]}: {i}/{len(pages)} стр., "
                    f"токены {STATS['ptok']:,}+{STATS['ctok']:,}")
    # спасательный проход: упавшие страницы по одной, с длинными паузами
    if any(results.get(p) is None for p in pages):
        log("  спасательный проход по упавшим страницам")
        key2 = read_key()
        for p in pages:
            if results.get(p) is None:
                time.sleep(20)
                pp, md = process_page(pdf_path, p, key2, model_holder)
                results[p] = md
    return [results.get(p) for p in pages], n


def file_already_in_base(stem):
    target = VAULT / "Normatives" / f"{stem}.md"
    return target.exists()


def desig(stem):
    m = re.search(r"(СП|ГОСТ Р ИСО|ГОСТ Р|ГОСТ EN|ГОСТ|СТО|СНиП|РД|ТУ)\s*[\d.]+[-\d.]*", stem)
    return m.group(0).replace(" ", "").upper() if m else stem[:40]


def write_to_vault(pdf_path, pages_md, section):
    stem = Path(pdf_path).stem
    n = len(pages_md)
    passport = (
        f"# {stem}\n\n## Паспорт документа\n\n"
        f"- **Обозначение:** {desig(stem)}\n"
        f"- **Название:** {stem}\n"
        f"- **Раздел библиотеки:** {section}\n"
        f"- **Статус:** транскрибация VLM (GLM) по страницам, не заменяет официальный текст\n"
        f"- **Источник:** `{section}/{Path(pdf_path).name}`\n\n---\n\n"
    )
    body = "\n\n".join(
        (f"# Страница {i+1}\n\n{md}" if md else f"# Страница {i+1}\n\n[пустая]")
        for i, md in enumerate(pages_md))
    (VAULT / "Normatives" / f"{stem}.md").write_text(passport + body + "\n",
                                                     encoding="utf-8", newline="\n")
    note = (
        "---\n"
        f'title: "{stem}"\n'
        'type: "doc"\n'
        'scope: "global"\n'
        'status: "queued"\n'
        'source_url: ""\n'
        f'captured: "{time.strftime("%Y-%m-%d")}"\n'
        'raw: ""\n'
        f'text: "Normatives/{stem}.md"\n'
        f'desc: "{desig(stem)} — транскрибация VLM, {n} стр., раздел «{section}»."\n'
        "template_version: 2\n"
        "tags: [type/doc]\n"
        "related: []\n"
        "---\n\n## Заметки\n"
    )
    (VAULT / "_llm" / "notes" / f"{stem}.md").write_text(note, encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="папка раздела с PDF")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", type=int, default=0, help="пилот: N страниц/файл, в базу не писать")
    ap.add_argument("--sections", default="", help="через запятую — только эти подразделы")
    args = ap.parse_args()

    key = read_key()
    log(f"модель: {MODELS[0]} (фолбэк {MODELS[1]} — только если отвергнет картинку)")
    src = Path(args.dir)
    only = {s.strip() for s in args.sections.split(",") if s.strip()}
    pdfs = []
    for root, dirs, files in os.walk(src):
        rel = str(Path(root).relative_to(src))
        if only and not any(rel == o or rel.startswith(o + os.sep) for o in only):
            continue
        for f in sorted(files):
            if f.lower().endswith(".pdf") and not file_already_in_base(Path(f).stem):
                pdfs.append((Path(root) / f, rel))
    if args.limit:
        pdfs = pdfs[:args.limit]
    log(f"файлов к обработке: {len(pdfs)}" + (" (пилот)" if args.dry else ""))
    done = 0
    for pdf, section in pdfs:
        log(f"== {pdf.name[:60]} [{section}]")
        pages, n = transcribe_pdf(pdf, key, dry_pages=args.dry)
        if args.dry:
            prev = WORKER / "vlm" / "preview"
            prev.mkdir(parents=True, exist_ok=True)
            (prev / f"{pdf.stem}.md").write_text(
                "\n\n".join(md or "[ошибка]" for md in pages), encoding="utf-8")
            log(f"   пилот: {len(pages)}/{n} стр. -> vlm/preview/{pdf.stem[:40]}.md")
        else:
            if any(md is None for md in pages):
                log(f"   !! {pdf.name}: есть упавшие страницы, в базу не пишу")
                continue
            write_to_vault(pdf, pages, f"{src.name}/{section}" if section != "." else src.name)
            done += 1
            log(f"   -> Normatives/{pdf.stem[:50]}.md")
    log(f"ИТОГ: файлов в базу: {done}; страниц ok/skip/err: "
        f"{STATS['ok']}/{STATS['skip']}/{STATS['err']}; "
        f"токены prompt+completion: {STATS['ptok']:,}+{STATS['ctok']:,}; "
        f"время {(time.time()-T0)/60:.0f} мин")
    if done and not args.dry:
        os.system(f'cd /d "{VAULT}" && python _llm\\gen_index.py')


if __name__ == "__main__":
    main()
