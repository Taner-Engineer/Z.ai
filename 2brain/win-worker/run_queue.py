#!/usr/bin/env python
"""Раннер очереди 2brain на рабочем ПК (Windows, i7-14700KF + RTX 3050).

Забирает по SSH с homelab все задания из _Drop/_needs-gpu/jobs, исполняет
воркером worker.py локально, результаты возвращает в _Drop/_results/.
Homelab-демон подхватывает их следующим проходом.

Запуск:  C:\\Users\\Us\\2brain-worker\\venv\\Scripts\\python run_queue.py
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
from pathlib import Path

SSH = ["ssh", "-o", "ConnectTimeout=10", "root@192.168.2.9"]
REMOTE_JOBS = "/srv/2brain/_Drop/_needs-gpu/jobs"
REMOTE_RESULTS = "/srv/2brain/_Drop/_results"
HERE = Path(__file__).parent
WORK = HERE / "work"  # постоянный каталог между прогонами: resume без ручного seed
WORKER = HERE.parent / "gpu-worker" / "worker.py"
VENV_PY = Path(r"C:\Users\Us\2brain-worker\venv\Scripts\python.exe")


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print((r.stderr or r.stdout)[-400:], file=sys.stderr)
    return r


def seed_results(src_dirs, results_dir) -> int:
    """Подсадить готовые результаты (каталоги с manifest.json) в tmp results/.

    Дедупликация по имени каталога (id задания): уже существующее не замещаем.
    Возвращает, сколько подсажено.
    """
    n = 0
    for src in src_dirs:
        src = Path(src)
        if not src.is_dir():
            continue
        for child in sorted(src.iterdir()):
            if not child.is_dir() or not (child / "manifest.json").is_file():
                continue
            dst = results_dir / child.name
            if dst.exists():
                continue
            shutil.copytree(child, dst)
            n += 1
    return n


def drop_sent_jobs(jobs_dir) -> int:
    """Удалить из jobs задания со статусом sent (уже доставлены). Возвращает сколько."""
    n = 0
    for mf in sorted(Path(jobs_dir).glob("*/manifest.json")):
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # битый json — считаем не-sent, не трогаем
        if isinstance(m, dict) and m.get("status") == "sent":
            shutil.rmtree(mf.parent, ignore_errors=True)
            n += 1
    return n


def cleanup_after_delivery(results_dir, delivered_ids) -> int:
    """Удалить доставленные каталоги результатов. Возвращает сколько удалено."""
    n = 0
    for jid in delivered_ids:
        d = Path(results_dir) / jid
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser(description="Раннер очереди 2brain")
    parser.add_argument("--seed-results", action="append", default=[], metavar="DIR",
                        help="каталог готовых результатов для подсадки (можно повторять)")
    opts = parser.parse_args()
    # защита от наложения запусков (планировщик + вручную)
    lock = open(HERE / "queue.lock", "w")
    try:
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("другой экземпляр раннера уже работает — выход")
        return 0
    if not VENV_PY.exists():
        sys.exit("нет venv: C:\\Users\\Us\\2brain-worker\\venv — см. README win-worker")
    WORK.mkdir(parents=True, exist_ok=True)
    jobs, results = WORK / "jobs", WORK / "results"
    jobs.mkdir(exist_ok=True)
    results.mkdir(exist_ok=True)

    # 1) забрать задания
    p = subprocess.run(SSH + [f"tar -C {REMOTE_JOBS} -cf - ."],
                       capture_output=True, timeout=900)
    if p.returncode != 0 or not p.stdout:
        print("очередь пуста или homelab недоступен")
        return 0
    with open(WORK / "jobs.tar", "wb") as f:
        f.write(p.stdout)
    with tarfile.open(WORK / "jobs.tar") as tf:
        tf.extractall(jobs)

    # 1.2) уже доставленные прошлым прогоном задания не запускаем повторно
    dropped = drop_sent_jobs(jobs)
    if dropped:
        print(f"пропущено доставленных ранее: {dropped}")

    manifests = sorted(jobs.glob("*/manifest.json"))
    if not manifests:
        print("очередь пуста")
        return 0
    for mf in manifests:
        m = json.loads(mf.read_text(encoding="utf-8"))
        print(f"  - {m['id']}: {m['kind']} «{m['title']}»")

    # 1.5) подсадить готовые результаты: воркер не переделает их (skip-if-done)
    if opts.seed_results:
        n = seed_results(opts.seed_results, results)
        print(f"подсажено готовых результатов: {n}")

    # 2) исполнить воркером локально; смерть раннера = смерть воркера,
    # иначе остаётся GPU-процесс-сирота (инцидент 2026-09-14)
    def _bail(sig, frame):
        raise SystemExit(128 + sig)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        s = getattr(signal, name, None)
        if s is not None:
            signal.signal(s, _bail)

    env = {**os.environ, "WORK_DIR": str(WORK)}
    proc = subprocess.Popen([str(VENV_PY), str(WORKER)], env=env)
    try:
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if rc != 0:
        sys.exit("воркер завершился с ошибкой")

    # 3) вернуть результаты на homelab
    if any(results.iterdir()):
        delivered = [child.name for child in results.iterdir() if child.is_dir()]
        with tarfile.open(WORK / "results.tar", "w") as tf:
            for child in results.iterdir():
                tf.add(child, arcname=child.name)
        with open(WORK / "results.tar", "rb") as f:
            pr = subprocess.run(SSH + [f"mkdir -p {REMOTE_RESULTS} && tar -C {REMOTE_RESULTS} -xf -"],
                                stdin=f, capture_output=True, timeout=900)
            if pr.returncode != 0:
                print(pr.stderr.decode()[-300:], file=sys.stderr)
                sys.exit("не удалось вернуть результаты")
        # раннер пишет в _results от root — возвращаем владение twobrain сразу,
        # не дожидаясь cron-хука на homelab (демон работает от twobrain)
        subprocess.run(SSH + [f"chown -R twobrain:twobrain {REMOTE_RESULTS}"],
                       capture_output=True, timeout=60)
        # пометить исходные манифесты отправленными
        for mf in manifests:
            jid = mf.parent.name
            subprocess.run(SSH + [
                f"sed -i 's/\"status\": \"waiting_approval\"/\"status\": \"sent\"/' "
                f"{REMOTE_JOBS}/{jid}/manifest.json"], capture_output=True, timeout=30)
        # доставленное чистим, недоставленное (при сбоях) остаётся до следующего прогона
        cleanup_after_delivery(results, delivered)
        shutil.rmtree(jobs, ignore_errors=True)
        print(f"готово: {len(delivered)} заданий, результаты у демона на хоумлабе")
    else:
        print("воркер не дал результатов — смотрите вывод выше")
    return 0


if __name__ == "__main__":
    sys.exit(main())
