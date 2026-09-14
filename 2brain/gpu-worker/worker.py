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


def _nvidia_smi(*args: str) -> str:
    try:
        r = subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


def _gpu_stats() -> dict:
    """Мгновенные метрики GPU: util %, память занятая/свободная (МБ)."""
    out = _nvidia_smi("--query-gpu=utilization.gpu,memory.used,memory.total",
                      "--format=csv,noheader,nounits")
    if not out:
        return {}
    try:
        util, used, total = [float(x) for x in out.splitlines()[0].split(", ")]
        return {"util": util, "vram_used_mb": used, "vram_total_mb": total,
                "vram_free_mb": total - used}
    except Exception:
        return {}


def _ensure_cuda_dlls() -> None:
    """RapidOCR (onnxruntime-gpu) в docling ищет CUDA/cuDNN DLL через PATH —
    они лежат в torch/lib установки torch с CUDA."""
    try:
        import torch
        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
            os.add_dll_directory(str(lib))
    except Exception:
        pass  # torch без CUDA или его нет — работаем как раньше (CPU)


def _cpu_cores() -> int:
    return os.cpu_count() or 4


def _pick_workers(ocr: bool, probe_vram_mb: float | None) -> tuple[int, str]:
    """Сколько параллельных воркеров запускать и почему (человеческая строка)."""
    n_gpu = _cuda_count()
    if not n_gpu:
        return 1, "CPU: 1 воркер (docling сам занимает все ядра)"
    cores = _cpu_cores()
    stats = _gpu_stats()
    vram_free = stats.get("vram_free_mb", 0)
    # резервируем 1.5 ГБ на систему/пайплайн вне docling-процессов
    per_proc = probe_vram_mb if probe_vram_mb else (2800.0 if ocr else 1500.0)
    by_vram = max(1, int((vram_free - 1500) // per_proc)) if vram_free else 4
    by_cpu = max(1, (cores - 2) // 4)   # ~4 ядра на docling-процесс
    w = max(1, min(by_vram, by_cpu, 6))
    why = (f"GPU {n_gpu} шт., VRAM free {vram_free:.0f} МБ, {cores} ядер CPU: "
           f"по VRAM {by_vram}, по CPU {by_cpu} -> {w} воркеров"
           + (f" (probe: {probe_vram_mb:.0f} МБ/процесс)" if probe_vram_mb else " (оценка)"))
    return w, why


def _convert_single(src: str, dst: str, ocr: bool) -> None:
    """Конвертация одного PDF в текущем процессе (модель грузится один раз
    на процесс — держим воркер живым, он берёт чанки из очереди)."""
    _ensure_cuda_dlls()
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
    """OCR/конвертация PDF с динамическим чанкингом.

    Фаза 0 (probe): 20 страниц одним процессом -> страниц/сек, VRAM/процесс.
    Фаза 1: подбор числа воркеров W по VRAM/CPU (см. _pick_workers).
    Фаза 2: чанки по CHUNK страниц в разделяемой очереди; W воркеров
    (по процессу на GPU-слот), каждый атомарно клэймит чанк через mkdir
    и конвертирует; долгоживущие процессы — модель грузится 1 раз.
    Фаза 3: склейка по порядку страниц, телеметрия в manifest.
    """
    src = job_dir / m["input"]
    out = RESULTS / m["id"] / "output.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    ocr = m.get("ocr", True)
    import time as _time

    import pymupdf
    doc = pymupdf.open(src)
    n = doc.page_count
    doc.close()
    if n == 0:
        raise RuntimeError("PDF без страниц")

    chunk = int(os.environ.get("CHUNK_PAGES", "50"))
    n_gpu = _cuda_count()

    # ---- Фаза 0: probe на 20 страницах (только если страниц > chunk) ----
    probe_vram = None
    pages_per_sec = None
    if n > chunk and (n_gpu or int(os.environ.get("SHARD_FORCE", "0"))):
        t0 = _time.monotonic()
        v0 = _gpu_stats().get("vram_used_mb", 0)
        pd = job_dir / "probe.pdf"
        d = pymupdf.open(src); d.select(range(min(20, n))); d.save(pd); d.close()
        _convert_single(str(pd), str(job_dir / "probe.md"), ocr)
        pd.unlink(missing_ok=True); (job_dir / "probe.md").unlink(missing_ok=True)
        dt = _time.monotonic() - t0
        pages_per_sec = min(20, n) / dt if dt > 0 else None
        v1 = _gpu_stats().get("vram_used_mb", 0)
        probe_vram = max(0.0, v1 - v0) if v1 >= v0 else None
        print(f"[{m['id']}] probe: {min(20,n)} стр. за {dt:.1f}с "
              f"({pages_per_sec:.2f} стр/с), VRAM/процесс {probe_vram or '?'} МБ", flush=True)

    # ---- Фаза 1: сколько воркеров ----
    force = int(os.environ.get("SHARD_FORCE", "0"))
    if force:
        W, why = force, f"SHARD_FORCE={force} (тест)"
    else:
        W, why = _pick_workers(ocr, probe_vram)
    total_chunks = (n + chunk - 1) // chunk
    W = min(W, total_chunks)
    print(f"[{m['id']}] {n} стр. -> {total_chunks} чанков по ~{chunk}, {W} воркеров: {why}", flush=True)

    # ---- Фаза 2: разделяемая очередь чанков + W долгоживущих воркеров ----
    qdir = job_dir / "chunks"
    qdir.mkdir(exist_ok=True)
    parts_md = []
    n_err = 0
    t0 = _time.monotonic()
    if W <= 1:
        # одиночный проход без шардирования (мелкие документы)
        _convert_single(str(src), str(out), ocr)
    else:
        import threading
        errors: list[str] = []
        lock = threading.Lock()
        next_chunk = [0]
        n_gpu_eff = n_gpu or 1

        def worker_main(wid: int):
            global n_err
            env_gpu = (wid // max(1, W // n_gpu_eff)) % n_gpu_eff if n_gpu else 0
            while True:
                with lock:
                    ci = next_chunk[0]
                    if ci >= total_chunks:
                        return
                    next_chunk[0] += 1
                lo, hi = ci * chunk, min((ci + 1) * chunk, n)
                claim = qdir / f"c{ci:04d}"
                try:
                    claim.mkdir(exist_ok=False)  # атомарный клэйм
                except FileExistsError:
                    continue
                cp = job_dir / f"chunk{ci:04d}.pdf"
                d = pymupdf.open(src); d.select(range(lo, hi)); d.save(cp); d.close()
                cmd = [sys.executable, __file__, "--part", str(cp),
                       str(claim / "out.md"), "1" if ocr else "0"]
                env = {**os.environ}
                if n_gpu:
                    env["CUDA_VISIBLE_DEVICES"] = str(env_gpu)
                r = subprocess.run(cmd, capture_output=True, text=True, env=env)
                if r.returncode != 0 or not (claim / "out.md").exists():
                    with lock:
                        errors.append(f"chunk{ci}: {(r.stderr or '')[-200:]}")
                        n_err += 1
                cp.unlink(missing_ok=True)

        threads = [threading.Thread(target=worker_main, args=(i,)) for i in range(W)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            for e in errors[:5]:
                print(f"[{m['id']}] FAILED chunk: {e}", flush=True)
            raise RuntimeError(f"{len(errors)} чанков упало")
        parts_md = [qdir / f"c{i:04d}" / "out.md" for i in range(total_chunks)]
        text = "\n\n".join(p.read_text(encoding="utf-8") for p in parts_md)
        out.write_text(text, encoding="utf-8")

    dt = _time.monotonic() - t0
    rate = n / dt if dt > 0 else 0
    g = _gpu_stats()
    m["telemetry"] = {
        "pages": n, "chunks": (n + chunk - 1) // chunk, "workers": W,
        "seconds": round(dt, 1), "pages_per_sec": round(rate, 2),
        "gpu_util_pct": g.get("util"), "vram_peak_mb": g.get("vram_used_mb"),
        "probe_vram_per_proc_mb": probe_vram,
    }
    print(f"[{m['id']}] done: {n} стр. за {dt:.0f}с ({rate:.1f} стр/с, "
          f"GPU util {g.get('util', '?')}%) -> {out.name}", flush=True)
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
