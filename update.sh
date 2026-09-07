#!/usr/bin/env bash
# Обновляет локальную копию из GitHub и переустанавливает скиллы и память.
# Запуск из корня репозитория: ./update.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "[*] git pull..."
git pull --ff-only

./install.sh
