# BLOCKERS: TASK-remove-local-docling — приёмка 2/3, блокер не в правках

## Статус правок
FIXLIST выполнен полностью, дифф — чистое удаление: 4 файла, +1/-87 строк.

- `2brain/processors.py`: удалены `_LAST_DOCLING_ERROR` и весь блок
  «PDF через docling (в контейнере)» (`_docling_convert`, `do_pdf`).
  Остальное (djvu_to_pdf и пр.) не тронуто.
- `2brain/config.py`: удалены `DOCLING_IMAGE`, `DOCLING_CACHE`.
  `OCR_SEC_PER_PAGE` не тронут.
- `2brain/convert_one.py`: удалён.
- `2brain/daemon.py`: докстринг, маршрутизация заменена на
  `(PDF/DJVU -> PDF -> GPU-очередь (рабочий ПК); видео >5 мин -> GPU-очередь)`.

## Результат проверок
1. unittest discover: **7/7 OK**.
2. grep `do_pdf|_docling_convert|DOCLING_IMAGE|DOCLING_CACHE|convert_one|_LAST_DOCLING`:
   **пусто** (exit 1).
3. Точная команда `... -c "import sys; sys.path.insert(0, '2brain'); import processors, daemon"`:
   **падает** —
   ```
   File "...\2brain\daemon.py", line 19, in <module>
       import fcntl
   ModuleNotFoundError: No module named 'fcntl'
   ```

## Доказательство: блокер pre-existing, не от моих правок
- `git worktree add <tmp> --detach HEAD` (код ДО правок) + та же команда →
  та же ошибка `ModuleNotFoundError: No module named 'fcntl'` на daemon.py:19.
- `fcntl` — модуль только Unix; на Windows Python его нет ни в каком venv.
- Репозиторий сам это фиксирует: `2brain/tests/test_daemon_handle_pdf.py`
  перед импортом daemon делает `sys.modules.setdefault("fcntl", MagicMock())`
  с комментарием «модуль существует только на Unix».
- Импорт с этой же заглушкой проходит:
  ```
  python -c "import sys; from unittest.mock import MagicMock; \
    sys.modules.setdefault('fcntl', MagicMock()); sys.path.insert(0, '2brain'); \
    import processors, daemon"   # -> IMPORT OK
  ```
  `import processors` без заглушки — тоже OK (правки импортируются чисто).

## Минимальный пример (любая Windows-машина)
```
python -c "import fcntl"
# ModuleNotFoundError: No module named 'fcntl'
```

## Варианты закрытия пункта 3 (на выбор владельца, вне FIXLIST)
1. Принять проверку 3 с заглушкой fcntl (как это уже делает тест-сьют).
2. `daemon.py`: `try: import fcntl / except ImportError: fcntl = None`
   (используется только в `__main__`-блоке с flock) — правка вне разрешённого списка.
3. Гонять приёмку на Linux/homelab.
