#!/usr/bin/env python
"""Раннер очереди 2brain на рабочем ПК (Windows, i7-14700KF + RTX 3050).

Забирает по SSH с homelab все задания из _Drop/_needs-gpu/jobs, исполняет
воркером worker.py локально, результаты возвращает в _Drop/_results/.
Homelab-демон подхватывает их следующим проходом.

Запуск:  C:\\Users\\Us\\2brain-worker\\venv\\Scripts\\python run_queue.py
"""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SSH = ["ssh", "-o", "ConnectTimeout=10", "root@192.168.2.9"]
REMOTE_JOBS = "/srv/2brain/_Drop/_needs-gpu/jobs"
REMOTE_RESULTS = "/srv/2brain/_Drop/_results"
HERE = Path(__file__).parent
WORKER = HERE.parent / "gpu-worker" / "worker.py"
VENV_PY = Path(r"C:\Users\Us\2brain-worker\venv\Scripts\python.exe")


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print((r.stderr or r.stdout)[-400:], file=sys.stderr)
    return r


def main():
    if not VENV_PY.exists():
        sys.exit("нет venv: C:\\Users\\Us\\2brain-worker\\venv — см. README win-worker")
    tmp = Path(tempfile.mkdtemp(prefix="2brain-queue-"))
    jobs, results = tmp / "jobs", tmp / "results"
    jobs.mkdir(parents=True)

    # 1) забрать задания
    p = subprocess.run(SSH + [f"tar -C {REMOTE_JOBS} -cf - ."],
                       capture_output=True, timeout=120)
    if p.returncode != 0 or not p.stdout:
        print("очередь пуста или homelab недоступен")
        return 0
    with open(tmp / "jobs.tar", "wb") as f:
        f.write(p.stdout)
    with tarfile.open(tmp / "jobs.tar") as tf:
        tf.extractall(jobs)

    manifests = sorted(jobs.glob("*/manifest.json"))
    if not manifests:
        print("очередь пуста")
        return 0
    for mf in manifests:
        m = json.loads(mf.read_text(encoding="utf-8"))
        print(f"  - {m['id']}: {m['kind']} «{m['title']}»")

    # 2) исполнить воркером локально
    env = {**os.environ, "WORK_DIR": str(tmp)}
    r = subprocess.run([str(VENV_PY), str(WORKER)], env=env)
    if r.returncode != 0:
        sys.exit("воркер завершился с ошибкой")

    # 3) вернуть результаты на homelab
    if any(results.iterdir()):
        with tarfile.open(tmp / "results.tar", "w") as tf:
            for child in results.iterdir():
                tf.add(child, arcname=child.name)
        with open(tmp / "results.tar", "rb") as f:
            pr = subprocess.run(SSH + [f"mkdir -p {REMOTE_RESULTS} && tar -C {REMOTE_RESULTS} -xf -"],
                                stdin=f, capture_output=True, timeout=300)
            if pr.returncode != 0:
                print(pr.stderr.decode()[-300:], file=sys.stderr)
                sys.exit("не удалось вернуть результаты")
        # пометить исходные манифесты отправленными
        for mf in manifests:
            jid = mf.parent.name
            subprocess.run(SSH + [
                f"sed -i 's/\"status\": \"waiting_approval\"/\"status\": \"sent\"/' "
                f"{REMOTE_JOBS}/{jid}/manifest.json"], capture_output=True, timeout=30)
        print(f"готово: {len(manifests)} заданий, результаты у демона на хоумлабе")
    else:
        print("воркер не дал результатов — смотрите вывод выше")
    return 0


if __name__ == "__main__":
    sys.exit(main())
