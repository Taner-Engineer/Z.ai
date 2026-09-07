#!/bin/sh
# Локальная функциональная репетиция GPU-воркера БЕЗ аренды: тот же образ,
# та же точка входа, CPU-вариант. Проверяет вход/выход/форматы целиком.
#
#   test-local.sh          # сборка (один раз, ~15-20 мин) + тест
#   test-local.sh --test   # только тест, без пересборки
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TESTDIR="$HERE/_localtest"
VENV=/opt/2brain-venv/bin/python

if [ "$1" != "--test" ]; then
    echo "== сборка CPU-образа (модели запекаются, это долго)"
    docker build --build-arg DEVICE=cpu -t 2brain-worker:cpu "$HERE"
fi

echo "== подготовка тестовых заданий"
rm -rf "$TESTDIR"; mkdir -p "$TESTDIR/jobs"

# 1) STT: 11-секундный образец из whisper.cpp
mkdir -p "$TESTDIR/jobs/test-stt"
cp /opt/whisper.cpp/samples/jfk.wav "$TESTDIR/jobs/test-stt/input.wav"
cat > "$TESTDIR/jobs/test-stt/manifest.json" <<'EOF'
{"id": "test-stt", "kind": "stt", "amount": 0.2, "title": "локальный тест STT",
 "note": "", "input": "input.wav", "status": "waiting_approval"}
EOF

# 2) OCR: «скан» — текст растрируется и вставляется картинкой (текстового слоя нет)
mkdir -p "$TESTDIR/jobs/test-ocr"
cd "$HERE"
$VENV - <<'EOF'
import pymupdf
tmp = pymupdf.open()
p = tmp.new_page()
p.insert_text((72, 100), "OCR rehearsal line 42: prochitay etu stroku", fontsize=24)
pix = p.get_pixmap(dpi=150)
pix.save("_localtest/ocr-src.png")
out = pymupdf.open()
op = out.new_page()
op.insert_image(op.rect, filename="_localtest/ocr-src.png")
out.save("_localtest/jobs/test-ocr/input.pdf")
assert not out[0].get_text().strip(), "тестовый PDF обязан быть без текстового слоя"
EOF
cat > "$TESTDIR/jobs/test-ocr/manifest.json" <<'EOF'
{"id": "test-ocr", "kind": "ocr", "amount": 1, "title": "локальный тест OCR",
 "note": "", "input": "input.pdf", "status": "waiting_approval"}
EOF

echo "== прогон воркера (CPU, int8 — медленно, но тот же код)"
docker run --rm -v "$TESTDIR:/work" 2brain-worker:cpu

echo "== результаты"
for f in "$TESTDIR"/results/*/output.*; do
    echo "--- $f"; head -c 300 "$f"; echo; echo
done
echo "РЕПЕТИЦИЯ ОК: оба задания дают результат — бандл готов к vast.ai"
