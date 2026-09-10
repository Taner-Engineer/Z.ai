# TASK: worker.py — подключить CUDA DLL из torch/lib для onnxruntime-gpu

Цель одной фразой: воркер docling должен сам находить CUDA/cuDNN DLL (лежат в
`venv/Lib/site-packages/torch/lib`) при запуске OCR на GPU, без ручного PATH.

Контекст: на рабочем ПК установлен torch 2.14.0+cu130 и onnxruntime-gpu 1.29.
RapidOCR (OCR-движок docling) автоматически ставит CUDAExecutionProvider первым,
но DLL (cudart64_13, cublas64_13, cudnn64_9...) onnxruntime ищет через PATH.
Проверено вручную: с torch/lib в PATH сессия создаётся с CUDA-провайдером.

## Правка (единственная): `C:\Users\Us\zcode-sync\2brain\gpu-worker\worker.py`

1. Добавить функцию (разместить рядом с `_gpu_stats`, перед `_convert_single`):

```python
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
```

2. Первой строкой тела `_convert_single` (до импортов docling) вызвать
   `_ensure_cuda_dlls()`.

Больше НИЧЕГО не менять (чанкинг, _pick_workers, run_ocr, run_stt — не трогать).

## Приёмка

1. `C:/Users/Us/2brain-worker/venv/Scripts/python.exe -m py_compile C:/Users/Us/zcode-sync/2brain/gpu-worker/worker.py` — без ошибок.
2. `cd C:\Users\Us\zcode-sync && C:/Users/Us/2brain-worker/venv/Scripts/python.exe -m unittest discover -s 2brain/tests` — 7/7 зелёные.
3. `git -C C:\Users\Us\zcode-sync diff --stat` — ровно один файл `2brain/gpu-worker/worker.py`, дифф ≤ 20 строк.

## Ограничения

- Без новых зависимостей; комментарий один, по-русски, как в коде выше.
- Не трогать другие файлы.
