#!/usr/bin/env python
"""Локальный быстрый путь очереди 2brain (архитектура 2026-09-14).

Если файлы уже лежат в _Drop рабочей копии ваулта на этом ПК — обрабатывать
сразу локально (worker.py, RTX 3050) и отправлять на homelab только результат:
манифесты заданий + готовые output.md в _Drop/_results/. Демон доводит их
до заметок своим обычным collect_gpu_results().

Поток:
  1. скан _Drop (корень + Books/ + Projects/<имя>/), PDF только;
  2. параллельный pdf_analyze (pymupdf): страницы, текст-слой -> convert/ocr;
  3. заметка-заглушка (status queued-gpu) в _llm/notes локального ваулта;
  4. задания в <work>/jobs/<id>/ (манифест + input.pdf), исходник — в
     локальный архив C:\\Users\\Us\\2brain-worker\\drop-archive\\<дата>\\
     (вне ваулта, чтобы Syncthing разнёс удаление и демон homelab не ставил
     дубль в очередь; оригиналы остаются на исходном носителе);
  5. worker.py (та же схема, что run_queue.py);
  6. результаты tar-ом на homelab в _Drop/_results/ + chown twobrain;
  7. подчистка на homelab копий, успевших просочиться через Syncthing.

DJVU и видео здесь не поддерживаются — они идут старым путём через homelab.

Запуск:  venv\\Scripts\\python run_local.py [--dry-run]
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

SSH = ["ssh", "-o", "ConnectTimeout=10", "root@192.168.2.9"]
REMOTE_RESULTS = "/srv/2brain/_Drop/_results"
VAULT = Path(r"C:\Users\Us\Vaults\2brain")
DROP = VAULT / "_Drop"
ARCHIVE = Path(r"C:\Users\Us\2brain-worker\drop-archive")
HERE = Path(__file__).parent
WORKER = HERE.parent / "gpu-worker" / "worker.py"
VENV_PY = Path(r"C:\Users\Us\2brain-worker\venv\Scripts\python.exe")

PDF_CHARS_PER_PAGE = 150   # порог из /opt/2brain/config.py
FORBIDDEN = re.compile(r'[\\/:*?"<>|]')

STUB = """---
title: "{title}"
type: "doc"
scope: "{scope}"
status: "queued-gpu"
source_url: ""
captured: "{captured}"
raw: ""
text: ""
desc: ""
template_version: 2
tags: [type/doc]
related: []
---

## Карта

"""


def sanitize(name: str) -> str:
    name = FORBIDDEN.sub("", name).strip().rstrip(".")
    return name[:120] or "Без названия"


def drop_scope(p: Path) -> str:
    try:
        rel = p.parent.relative_to(DROP)
    except ValueError:
        return "global"
    parts = rel.parts
    if parts[:1] == ("Books",):
        return "books"
    if len(parts) >= 2 and parts[0] == "Projects":
        return f"project/{parts[1]}"
    return "global"


def pdf_analyze(path: str) -> dict:
    import pymupdf
    doc = pymupdf.open(path)
    n = doc.page_count
    if n == 0:
        doc.close()
        return {"pages": 0, "text_layer": False}
    start = max(0, n // 2 - 7)
    stop = min(start + 15, n)
    chars = sum(len(pg.get_text().strip()) for pg in doc.pages(start, stop, 1))
    doc.close()
    return {"pages": n, "text_layer": chars / (stop - start) >= PDF_CHARS_PER_PAGE}


def make_stub(note: Path, title: str, scope: str) -> None:
    if note.exists():
        return
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(STUB.format(title=title, scope=scope,
                                captured=datetime.date.today().isoformat()),
                    encoding="utf-8")


def note_path(title: str) -> Path:
    notes = VAULT / "_llm" / "notes"
    base = sanitize(title)
    p = notes / f"{base}.md"
    n = 2
    while p.exists():
        p = notes / f"{base} ({n}).md"
        n += 1
    return p


def sh(cmd, timeout=None, stdin_file=None):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                       stdin=stdin_file)
    if r.returncode != 0:
        print((r.stderr or r.stdout)[-400:], file=sys.stderr)
    return r


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not VENV_PY.exists():
        sys.exit("нет venv: C:\\Users\\Us\\2brain-worker\\venv")

    # 1) кандидаты: файлы в _Drop (корень + один уровень Books/, Projects/<имя>/)
    all_files = []
    for d in [DROP, *(x for x in DROP.iterdir()
                     if x.is_dir() and not x.name.startswith(("_", ".")))]:
        all_files.extend(p for p in d.iterdir() if p.is_file())
    all_files = sorted(set(all_files))
    for p in all_files:
        if p.suffix.lower() != ".pdf":
            print(f"остаю старому пути (не PDF): {p.name}")
    cands = [p for p in all_files if p.suffix.lower() == ".pdf"]

    # 2) преданализ (параллельно)
    infos = {}
    if cands:
        with ProcessPoolExecutor(max_workers=12) as ex:
            for p, info in zip(cands, ex.map(pdf_analyze, [str(p) for p in cands])):
                infos[p] = info
    pdfs = [p for p in cands if infos[p]["pages"] > 0]
    for p in cands:
        if infos[p]["pages"] == 0:
            print(f"пропуск пустого/битого PDF: {p.name}")
    if not pdfs:
        print("локальная очередь пуста")
        return 0
    for p in pdfs:
        kind = "convert" if infos[p]["text_layer"] else "ocr"
        print(f"  - {kind} {infos[p]['pages']:4d} стр.: {p.name}")

    # 3-4) заметки + задания + архивирование исходников
    work = Path(tempfile.mkdtemp(prefix="2brain-local-"))
    (work / "jobs").mkdir()
    (work / "results").mkdir()
    today = datetime.date.today().isoformat()
    archived = []
    for p in pdfs:
        title = p.stem
        scope = drop_scope(p)
        note = note_path(title)
        nparts = note.stem  # учёт суффикса коллизии (2), (3)...
        if not dry:
            make_stub(note, nparts, scope)
        jid = f"{today}-{uuid.uuid4().hex[:8]}"
        jdir = work / "jobs" / jid
        jdir.mkdir()
        shutil.copy2(p, jdir / "input.pdf")
        manifest = {
            "id": jid,
            "kind": "convert" if infos[p]["text_layer"] else "ocr",
            "ocr": not infos[p]["text_layer"],
            "amount": infos[p]["pages"],
            "title": nparts,
            "note": str(note.relative_to(VAULT)),
            "input_url": "",
            "status": "waiting_approval",
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "input": "input.pdf",
        }
        (jdir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        if not dry:
            dest = ARCHIVE / today / p.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dest)
            archived.append(dest)
    print(f"заданий: {len(pdfs)} -> {work}")
    if dry:
        print("dry-run: обработка и отправка не выполнялись")
        return 0

    # 5) воркер
    env = {**os.environ, "WORK_DIR": str(work)}
    r = subprocess.run([str(VENV_PY), str(WORKER)], env=env)
    if r.returncode != 0:
        sys.exit("воркер завершился с ошибкой; исходники в " + str(ARCHIVE / today))
    # воркер выходит с кодом 0 и без результатов, если GPU держит другой worker.py
    if not any((work / "results").iterdir()):
        print("GPU занят другим воркером — прогон отложен")
        return 0

    # 6) результаты на homelab
    if any((work / "results").iterdir()):
        with open(work / "results.tar", "wb") as out:
            with tarfile.open(fileobj=out, mode="w") as tf:
                for child in sorted((work / "results").iterdir()):
                    tf.add(child, arcname=child.name)
        with open(work / "results.tar", "rb") as f:
            pr = sh(SSH + [f"mkdir -p {REMOTE_RESULTS} && tar -C {REMOTE_RESULTS} -xf -"],
                    timeout=900, stdin_file=f)
            if pr.returncode != 0:
                sys.exit("не удалось отправить результаты на homelab")
        sh(SSH + [f"chown -R twobrain:twobrain {REMOTE_RESULTS}"], timeout=120)
        print(f"отправлено: {len(list((work / 'results').iterdir()))} заданий")

    # 7) подчистка копий, успевших уйти на homelab до удаления в Syncthing
    for dest in archived:
        q = str(dest.name).replace('"', '\\"')
        r2 = sh(SSH + [f'find /srv/2brain/_Drop -name "{q}" -not -path "*/_results/*"'],
                timeout=30)
        for line in r2.stdout.decode(errors="replace").splitlines():
            if line.strip():
                sh(SSH + [f'rm -f "{line.strip()}"'], timeout=30)
                print(f"снят с homelab дублирующий вход: {line.strip()}")
    print("готово: демон homelab доведёт заметки следующим проходом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
