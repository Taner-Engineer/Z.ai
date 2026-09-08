#!/bin/sh
# Деплой на ПРЯМОЙ инстанс vast.ai, запущенный на образе 2brain-worker:cuda
# (Launch mode: Interactive SSH — контейнер уже работает, мы внутри него).
#
#   deploy-direct.sh <IP> <SSH-ПОРТ> [id-задания]
#
# Требует VAST_SSHPASS (пароль инстанса). Что делает:
#   1. scp свежего worker.py + заданий (jobs/*, ~200 МБ макс)
#   2. python worker.py на инстансе (GPU, динамический чанкинг)
#   3. Забирает results -> /srv/2brain/_Drop/_results/ (демон подхватит)
#   4. Помечает манифесты sent
set -e
IP="$1"; PORT="${2:-22}"; JOB="${3:-}"
[ -n "$VAST_SSHPASS" ] || { echo "нужен VAST_SSHPASS='<пароль>'"; exit 1; }
[ -n "$IP" ] || { echo "usage: VAST_SSHPASS='<пароль>' $0 <IP> <порт> [job-id]"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
JOBS_SRC="/srv/2brain/_Drop/_needs-gpu/jobs"
RESULTS_DST="/srv/2brain/_Drop/_results"
WORK="/root/2brain"

SSH_OPTS="-p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH="sshpass -e ssh $SSH_OPTS root@$IP"
SCP="sshpass -e scp -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
export SSHPASS="$VAST_SSHPASS"

# --- выбрать задания ---
TMPJOBS="$(mktemp -d)"
count=0
for mf in "$JOBS_SRC"/*/manifest.json; do
    [ -e "$mf" ] || continue
    id="$(basename "$(dirname "$mf")")"
    status="$(sed -n 's/.*"status": *"\([^"]*\)".*/\1/p' "$mf")"
    [ "$status" = "waiting_approval" ] || continue
    if [ -n "$JOB" ] && [ "$id" != "$JOB" ]; then continue; fi
    cp -r "$(dirname "$mf")" "$TMPJOBS/"
    count=$((count+1))
done
[ "$count" -gt 0 ] || { echo "нет заданий waiting_approval"; rm -rf "$TMPJOBS"; exit 0; }
echo "== заданий: $count"

# --- залить worker.py + задания ---
$SSH "mkdir -p $WORK/jobs $WORK/results"
$SCP "$HERE/worker.py" "root@$IP:$WORK/worker.py"
tar -C "$TMPJOBS" -cf - . | $SSH "tar -C $WORK/jobs -xf -"
echo "== залито, запуск"

# --- прогон (nvidia драйвер проброшен в контейнер vast автоматически) ---
WORK_DIR="$WORK" $SSH "cd $WORK && python3 worker.py" || true

# --- забрать результаты ---
mkdir -p "$RESULTS_DST"
$SSH "cd $WORK/results && tar -cf - ." | tar -C "$RESULTS_DST" -xf -
echo "== результаты: $RESULTS_DST"

# --- пометить sent ---
for d in "$TMPJOBS"/*/; do
    id="$(basename "$d")"
    mf="$JOBS_SRC/$id/manifest.json"
    [ -e "$mf" ] && sed -i 's/"status": *"waiting_approval"/"status": "sent"/' "$mf"
done
rm -rf "$TMPJOBS"
echo "ГОТОВО. Destroy инстанс в панели vast.ai — аренда остановится."
