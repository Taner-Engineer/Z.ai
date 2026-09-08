#!/bin/sh
# Сборка CUDA-образа на homelab (вне аренды) и публикация tarball на VPS
# для быстрой загрузки на инстанс vast.ai через docker load.
#
#   push-image-vps.sh            # собрать (если нет) + залить на VPS + напечатать URL
#   push-image-vps.sh --url      # только напечатать готовый URL (без пересборки)
#
# Требует: docker на homelab, ssh-доступ root@VPS (ключ или sshpass),
# на VPS запускает одноразовый python3 -m http.server с токеном.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VPS="${VPS:-5.181.202.112}"
PORT="${PORT:-8080}"
IMAGE="2brain-worker:cuda"
TARBALL="/tmp/2brain-worker-cuda.tar.gz"
TOKEN="$(head -c 16 /dev/urandom | od -An -tx4 | tr -d ' \\n')"
DATE_TAG="$(date +%Y%m%d)"
REMOTE="/root/images/2brain-worker-cuda-$DATE_TAG.tar.gz"
URL="http://$VPS:$PORT/$(basename "$REMOTE")?t=$TOKEN"

SSH_VPS="ssh -o StrictHostKeyChecking=accept-new root@$VPS"

if [ "$1" != "--url" ]; then
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^$IMAGE$"; then
        echo "== сборка $IMAGE на homelab (pip + модели, ~15-25 мин, без инференса)"
        docker build --build-arg DEVICE=cuda -t "$IMAGE" "$HERE"
    fi
    echo "== docker save | gzip -> $TARBALL (~5-6 ГБ)"
    docker save "$IMAGE" | gzip -1 > "$TARBALL"
    echo "== заливка на VPS (домашний аплинк, ~10-30 мин)"
    $SSH_VPS "mkdir -p /root/images"
    cat "$TARBALL" | $SSH_VPS "cat > $REMOTE"
    rm -f "$TARBALL"
    # cleanup: хранить только 2 свежих tarball
    $SSH_VPS "cd /root/images && ls -t 2brain-worker-cuda-*.tar.gz | tail -n +3 | xargs -r rm --"
fi

# одноразовый HTTP: python http.server с проверкой токена через CGI-подобный shim
echo "== запуск одноразового HTTP на VPS:$PORT (токен в URL)"
$SSH_VPS "pkill -f 'http.server.*$PORT' 2>/dev/null; nohup python3 - > /dev/null 2>&1 << 'PYEOF' &
import http.server, socketserver, urllib.parse, sys, os
PORT = $PORT
TOKEN = '$TOKEN'
DIR = '/root/images'
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIR, **kw)
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get('t', [''])[0] != TOKEN:
            self.send_response(403); self.end_headers(); return
        self.path = urllib.parse.urlparse(self.path).path
        super().do_GET()
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('', PORT), H) as httpd:
    httpd.serve_forever()
PYEOF
echo STARTED"
echo
echo "TARBALL_URL='$URL'"
echo "Действует до перезапуска; передай в deploy-vast.sh: TARBALL_URL='$URL' $0 ..."
