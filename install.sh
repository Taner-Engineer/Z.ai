#!/usr/bin/env bash
# Разворачивает скиллы и глобальную память ZCode на этой машине.
# Запуск из корня репозитория: ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZCODE_SKILLS="$HOME/.zcode/skills"
AGENTS_SKILLS="$HOME/.agents/skills"
AGENTS_MD="$HOME/.zcode/AGENTS.md"

mkdir -p "$ZCODE_SKILLS" "$AGENTS_SKILLS"

# --- Скиллы ---
installed=0
for skill_dir in "$REPO_DIR"/skills/*/; do
    name="$(basename "$skill_dir")"
    cp -r "$skill_dir" "$ZCODE_SKILLS/$name"
    cp -r "$skill_dir" "$AGENTS_SKILLS/$name"
    echo "[+] скилл: $name"
    installed=$((installed + 1))
done

# --- Глобальная память AGENTS.md ---
if [ -f "$AGENTS_MD" ] && ! diff -q "$REPO_DIR/AGENTS.md" "$AGENTS_MD" >/dev/null 2>&1; then
    backup="$AGENTS_MD.bak.$(date +%Y%m%d-%H%M%S)"
    cp "$AGENTS_MD" "$backup"
    echo "[!] Существующий AGENTS.md отличался — сохранена копия: $backup"
fi
cp "$REPO_DIR/AGENTS.md" "$AGENTS_MD"
echo "[+] глобальная память: $AGENTS_MD"

echo
echo "Готово: $installed скилл(ов) + AGENTS.md установлены."
echo "Если ZCode запущен — перезапустите его, чтобы новые скиллы подхватились."
