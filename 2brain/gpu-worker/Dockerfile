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
# torch и torchvision ставятся ПАРОЙ из одного индекса — иначе pip подбирает
# несовместимые версии и docling падает на torchvision::nms. Версии = как в
# рабочем контейнере docling:cpu на homelab (проверены на реальных документах).
RUN if [ "$DEVICE" = "cuda" ]; then \
        pip install --no-cache-dir torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cu121 \
        && pip install --no-cache-dir nvidia-cublas-cu12 nvidia-cudnn-cu12 ; \
    else \
        pip install --no-cache-dir torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu ; \
    fi \
    && pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# Предзагрузка моделей в образ (сборка дольше, старт мгновенный):
# faster-whisper large-v3 + живая конвертация мини-PDF (тянет модели docling
# в HF-кэш ровно в том виде, в котором их ищет пайплайн)
ENV HF_HOME=/models/hf \
    LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib
RUN python - <<'EOF'
import faster_whisper
faster_whisper.WhisperModel("large-v3", device="cpu", compute_type="int8")

from pathlib import Path
pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj
trailer<</Root 1 0 R>>"""
Path("/tmp/preload.pdf").write_bytes(pdf)

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
opts = PdfPipelineOptions()
opts.do_ocr = True
conv = DocumentConverter(format_options={
    InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
conv.convert("/tmp/preload.pdf")
EOF

ENTRYPOINT ["python3", "worker.py"]
