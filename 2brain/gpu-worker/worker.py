"""Воркер GPU-инстанса: обрабатывает /work/jobs/<id>/manifest.json -> /work/results/<id>/.

Умеет два вида заданий:
  stt — input-файл аудио/видео ЛИБО input_url (YouTube): yt-dlp -> wav -> large-v3
  ocr — input PDF-скан: docling с full-page OCR -> markdown

Устройство определяется автоматически: cuda при наличии, иначе cpu/int8
(на CPU-сборке образ работает медленно, но функционально идентично).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

JOBS = Path("/work/jobs")
RESULTS = Path("/work/results")


def has_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def run_stt(job_dir: Path, m: dict) -> str:
    src = job_dir / m.get("input", "")
    if not src.exists() and m.get("input_url"):
        subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "wav", "-o",
             str(job_dir / "audio.%(ext)s"), m["input_url"]],
            check=True, capture_output=True, timeout=7200)
        src = next(job_dir.glob("audio.*"))
    wav = job_dir / "in16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True, timeout=3600)

    import faster_whisper
    device = "cuda" if has_cuda() else "cpu"
    compute = "int8"
    if device == "cuda":
        compute = "float16"
        try:  # ноутбучные карты с малым VRAM (RTX 3050 = 4 ГБ): large-v3 влезает только в int8
            import torch
            if torch.cuda.get_device_properties(0).total_memory < 7_000_000_000:
                compute = "int8"
        except Exception:
            pass
    print(f"[{m['id']}] STT large-v3 device={device} compute={compute}", flush=True)
    model = faster_whisper.WhisperModel("large-v3", device=device, compute_type=compute)
    segments, _info = model.transcribe(str(wav), language=None, vad_filter=True)
    text = "\n".join(s.text.strip() for s in segments if s.text.strip())
    out = RESULTS / m["id"] / "output.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    wav.unlink(missing_ok=True)
    return out.name


def run_ocr(job_dir: Path, m: dict) -> str:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    result = conv.convert(str(job_dir / m["input"]))
    out = RESULTS / m["id"] / "output.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.document.export_to_markdown(), encoding="utf-8")
    return out.name


def main() -> int:
    if not JOBS.exists():
        print("нет папки заданий /work/jobs", flush=True)
        return 1
    ok = 0
    for mf in sorted(JOBS.glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        try:
            print(f"[{m['id']}] start: {m['kind']} «{m.get('title', '')}»", flush=True)
            output = run_stt(mf.parent, m) if m["kind"] == "stt" else run_ocr(mf.parent, m)
            m["status"] = "done"
            m["output"] = output
            (RESULTS / m["id"] / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
            (RESULTS / m["id"] / "manifest.json").write_text(
                json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
            ok += 1
            print(f"[{m['id']}] done -> results/{m['id']}/{output}", flush=True)
        except Exception as e:  # одно задание не роняет батч
            m["status"] = "failed"
            m["error"] = str(e)[:500]
            (RESULTS / m["id"]).mkdir(parents=True, exist_ok=True)
            (RESULTS / m["id"] / "manifest.json").write_text(
                json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{m['id']}] FAILED: {e}", flush=True)
    print(f"готово: {ok} успешно", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
