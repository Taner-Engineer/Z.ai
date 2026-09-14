#!/bin/sh
# Деплой GPU-воркера на арендованный инстанс vast.ai. Запускать ТОЛЬКО после
# вашего явного «да» по карточке-эстимейту (см. _Drop/_needs-gpu/cards/).
#
#   VAST_SSHPASS='<пароль>' deploy-vast.sh <IP> <ПОРТ> [id-задания]
#
# vast.ai выдаёт нестандартный порт и пароль — их подставляет пользователь.
# Без id — обрабатываются ВСЕ задания в состоянии waiting_approval (пакетная
# аренда: один инстанс на весь накопившийся пакет).
# Сборка образа идёт на самом инстансе (у него быстрый канал), на homelab
# пересылается только контекст (<10 КБ) и входы заданий.
set -e

IP="$1"
PORT="${2:-22}"
JOB="${3:-}"
SSH_OPTS="-p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
if [ -n "$VAST_SSHPASS" ]; then
    SSH="sshpass -e ssh $SSH_OPTS"
    export SSHPASS="$VAST_SSHPASS"
else
    SSH="ssh $SSH_OPTS"
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
JOBS_SRC="/srv/2brain/_Drop/_needs-gpu/jobs"
RESULTS_DST="/srv/2brain/_Drop/_results"

[ -n "$IP" ] || { echo "usage: VAST_SSHPASS='<пароль>' $0 <IP> <ПОРТ> [id-задания]"; exit 1; }
[ -d "$JOBS_SRC" ] || { echo "нет папки заданий $JOBS_SRC"; exit 1; }

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
    count=$((count + 1))
done
[ "$count" -gt 0 ] || { echo "нет заданий, ожидающих прогона"; rm -rf "$TMPJOBS"; exit 1; }
echo "== заданий к прогону: $count"

# --- залить контекст и задания ---
tar -C "$HERE" -cf - Dockerfile requirements.txt worker.py \
    | $SSH "root@$IP" 'mkdir -p /root/gpu-worker && tar -C /root/gpu-worker -xf -'
tar -C "$TMPJOBS" -cf - . | $SSH "root@$IP" 'mkdir -p /root/gpu-worker/jobs && tar -C /root/gpu-worker/jobs -xf -'

# --- образ: три пути, по приоритету ---
# 1) IMAGE_REF (Docker Hub): инстанс тянет за ~1-2 мин с CDN; vast.ai может
#    стартовать инстанс сразу с этим образом — деплой без времени на образ.
#    После локальной сборки: push-image-dockerhub.sh (один раз, аплинк).
# 2) TARBALL_URL (VPS): docker load ~2-3 мин; tarball кладёт push-image-vps.sh.
# 3) Сборка на инстансе (долго/дорого) — только как последний фолбэк.
IMAGE_REF="${IMAGE_REF:-}"
TARBALL_URL="${TARBALL_URL:-}"
GOT_IMAGE=0
if [ -n "$IMAGE_REF" ]; then
    if [ -n "$DOCKERHUB_TOKEN" ]; then
        echo "$DOCKERHUB_TOKEN" | $SSH "root@$IP" "docker login -u ${IMAGE_REF%%/*} --password-stdin" || true
    fi
    if $SSH "root@$IP" "docker pull $IMAGE_REF"; then
        $SSH "root@$IP" "docker tag $IMAGE_REF 2brain-worker"
        echo "== образ из Docker Hub: $IMAGE_REF"
        GOT_IMAGE=1
    fi
fi
if [ "$GOT_IMAGE" = "0" ] && [ -n "$TARBALL_URL" ]; then
    echo "== образ: docker load из $TARBALL_URL"
    if $SSH "root@$IP" "curl -fsSL '$TARBALL_URL' | gzip -d | docker load"; then
        LOADED=$(docker images --format '{{.Repository}}:{{.Tag}}' | head -1)
        # имя образа после load определяется сохранённым тегом
        $SSH "root@$IP" "docker images --format '{{.Repository}}:{{.Tag}}' | grep 2brain-worker | head -1 | xargs -I{} docker tag {} 2brain-worker" \
            && GOT_IMAGE=1 && echo "== образ загружен из tarball"
    fi
fi
if [ "$GOT_IMAGE" = "0" ]; then
    echo "!! образ не получен (нет IMAGE_REF/TARBALL_URL) — сборка на инстансе (дольше, дороже)"
    $SSH "root@$IP" "cd /root/gpu-worker && docker build --build-arg DEVICE=cuda -t 2brain-worker ."
fi
$SSH "root@$IP" 'docker run --rm --gpus all -v /root/gpu-worker:/work 2brain-worker'

# --- забрать результаты ---
mkdir -p "$RESULTS_DST"
$SSH "root@$IP" 'mkdir -p /root/gpu-worker/results && cd /root/gpu-worker/results && tar -cf - .' \
    | tar -C "$RESULTS_DST" -xf -
echo "== результаты: $RESULTS_DST (демон подхватит следующим сканом)"

# --- пометить исходные манифесты выполненными ---
for d in "$TMPJOBS"/*/; do
    id="$(basename "$d")"
    mf="$JOBS_SRC/$id/manifest.json"
    [ -e "$mf" ] && sed -i 's/"status": *"waiting_approval"/"status": "sent"/' "$mf"
done
rm -rf "$TMPJOBS"

echo
echo "ГОТОВО. Инстанс больше не нужен — удалите его в панели vast.ai,"
echo "чтобы аренда не тикала: Destroy instance."
