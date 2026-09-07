# GPU-воркер 2brain: STT (faster-whisper large-v3) + OCR (docling).
# Собирается одинакого на homelab (DEVICE=cpu — функциональный тест без GPU)
# и на vast.ai (DEVICE=cuda — рабочий прогон). Модели запекаются в образ,
# чтобы на инстансе не тратить время аренды на скачивание.
FROM python:3.11-slim

ARG DEVICE=cpu

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ "$DEVICE" = "cuda" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121 \
        && pip install --no-cache-dir nvidia-cublas-cu12 nvidia-cudnn-cu12 ; \
    else \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu ; \
    fi \
    && pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# Предзагрузка моделей в образ (сборка дольше, старт мгновенный)
ENV HF_HOME=/models/hf \
    DOCLING_ARTIFACTS_PATH=/models/docling \
    LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib
RUN python - <<'EOF'
import faster_whisper, subprocess, sys
faster_whisper.WhisperModel("large-v3", device="cpu", compute_type="int8")
subprocess.run([sys.executable, "-m", "docling.utils.model_downloader", "download_models"],
               check=True)
EOF

ENTRYPOINT ["python3", "worker.py"]
