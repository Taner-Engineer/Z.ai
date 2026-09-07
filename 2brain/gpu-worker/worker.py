"""Воркер очереди: обрабатывает <WORK>/jobs/<id>/manifest.json -> <WORK>/results/<id>/.

WORK задаётся переменной окружения WORK_DIR (по умолчанию /work — для docker на
vast.ai; на рабочем ПК под Windows — локальный путь).

Виды заданий:
  stt — input-файл аудио/видео ЛИБО input_url (YouTube): yt-dlp -> wav -> large-v3
  ocr / convert — input PDF: docling с OCR (скан) или без (текст-слой), флаг ocr в манифесте

Устройство определяется автоматически: cuda при наличии, иначе cpu/int8.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

WORK = Path(os.environ.get("WORK_DIR", "/work"))
JOBS = WORK / "jobs"
RESULTS = WORK / "results"


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


def _cuda_count() -> int:
    try:
        import torch
        return torch.cuda.device_count() if torch.cuda.is_available() else 0
    except Exception:
        return 0


def _convert_single(src: str, dst: str, ocr: bool) -> None:
    """Конвертация одного PDF целиком в текущем процессе (устройство задаёт
    CUDA_VISIBLE_DEVICES снаружи)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = ocr
    opts.do_table_structure = True
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    result = conv.convert(src)
    Path(dst).write_text(result.document.export_to_markdown(), encoding="utf-8")


def run_ocr(job_dir: Path, m: dict) -> str:
    """OCR/конвертация PDF. Длинные документы режутся на части по SHARD_PAGES
    страниц, части конвертируются параллельно — по процессу на GPU; на CPU
    части гоняются последовательно (torch и так съедает все ядра)."""
    src = job_dir / m["input"]
    out = RESULTS / m["id"] / "output.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    ocr = m.get("ocr", True)

    import pymupdf
    doc = pymupdf.open(src)
    n = doc.page_count
    doc.close()

    shard = int(os.environ.get("SHARD_PAGES", "60"))
    n_gpu = _cuda_count()
    force = int(os.environ.get("SHARD_FORCE", "0"))  # тест fan-out без GPU
    k = min((n + shard - 1) // shard, max(n_gpu, force)) if (n_gpu or force) else 1

    if k <= 1:
        _convert_single(str(src), str(out), ocr)
        return out.name

    print(f"[{m['id']}] {n} стр. -> {k} шардов по ~{shard}", flush=True)
    parts = []
    for i in range(k):
        d = pymupdf.open(src)
        d.select(range(i * n // k, (i + 1) * n // k))
        part_pdf = job_dir / f"part{i}.pdf"
        d.save(part_pdf)
        d.close()
        parts.append(part_pdf)

    procs = []
    for i, part_pdf in enumerate(parts):
        part_md = out.with_suffix(f".part{i}.md")
        env = {**os.environ}
        if n_gpu:
            env["CUDA_VISIBLE_DEVICES"] = str(i % n_gpu)
        procs.append((i, part_md, subprocess.Popen(
            [sys.executable, __file__, "--part", str(part_pdf), str(part_md),
             "1" if ocr else "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)))
    ok = True
    for i, part_md, p in procs:
        _, err = p.communicate()
        if p.returncode != 0 or not part_md.exists():
            ok = False
            print(f"[{m['id']}] шард {i} FAILED: {(err or '')[-300:]}", flush=True)
    if not ok:
        raise RuntimeError("один из шардов не завершился")

    text = "\n\n".join(
        out.with_suffix(f".part{i}.md").read_text(encoding="utf-8") for i in range(k))
    out.write_text(text, encoding="utf-8")
    for i in range(k):
        out.with_suffix(f".part{i}.md").unlink(missing_ok=True)
        parts[i].unlink(missing_ok=True)
    return out.name


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--part":
        _convert_single(sys.argv[2], sys.argv[3], sys.argv[4] == "1")
        return 0
    if not JOBS.exists():
        print("нет папки заданий /work/jobs", flush=True)
        return 1
    ok = 0
    for mf in sorted(JOBS.glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        try:
            print(f"[{m['id']}] start: {m['kind']} «{m.get('title', '')}»", flush=True)
            if m["kind"] == "stt":
                output = run_stt(mf.parent, m)
            else:  # ocr | convert
                output = run_ocr(mf.parent, m)
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
