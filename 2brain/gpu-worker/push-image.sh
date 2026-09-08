#!/bin/sh
# Сборка (если нет) + публикация CUDA-образа 2brain-worker:
#   1) Docker Hub (деплойный путь, IMAGE_REF) — если передан DOCKERHUB_USER
#   2) Google Drive (вечный бэкап, rclone gdrive:) — всегда
#
#   push-image.sh                    # собрать при необходимости + Drive-бэкап
#   DOCKERHUB_USER=x DOCKERHUB_TOKEN=y push-image.sh   # + push в Docker Hub
#
# Drive-бэкап: gdrive:2brain/images/2brain-worker-cuda-<date>.tar.gz
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="2brain-worker:cuda"
DATE_TAG="$(date +%Y%m%d)"
TARBALL="/root/2brain-worker-cuda-$DATE_TAG.tar.gz"  # НЕ /tmp: там tmpfs 5.8G, не влезает

if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^$IMAGE$"; then
    echo "== сборка $IMAGE (~15-25 мин)"
    docker build --build-arg DEVICE=cuda -t "$IMAGE" "$HERE"
fi

echo "== docker save | gzip -1 -> $TARBALL (нужно ~11 ГБ в /root)"
docker save "$IMAGE" | gzip -1 > "$TARBALL"
ls -lh "$TARBALL"

# --- Docker Hub (деплой) ---
if [ -n "$DOCKERHUB_USER" ] && [ -n "$DOCKERHUB_TOKEN" ]; then
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USER" --password-stdin
    docker tag "$IMAGE" "$DOCKERHUB_USER/2brain-worker:cuda"
    docker push "$DOCKERHUB_USER/2brain-worker:cuda"
    echo "== Docker Hub: $DOCKERHUB_USER/2brain-worker:cuda"
fi

# --- Google Drive (вечный бэкап) ---
echo "== rclone -> gdrive:2brain/images/ (аплинк ~10-30 мин)"
rclone mkdir -p gdrive:2brain/images 2>/dev/null || true
rclone copy "$TARBALL" gdrive:2brain/images/ --progress
# хранить 2 свежих бэкапа
rclone delete gdrive:2brain/images --min-age 60d 2>/dev/null || true
echo "== Drive: gdrive:2brain/images/$DATE_TAG.tar.gz"

rm -f "$TARBALL"
echo
echo "ГОТОВО. IMAGE_REF='$DOCKERHUB_USER/2brain-worker:cuda' (если пушен),"
echo "Drive-бэкап: gdrive:2brain/images/2brain-worker-cuda-$DATE_TAG.tar.gz"
