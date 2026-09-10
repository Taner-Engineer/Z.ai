# TASK: владение-фиксы GPU-конвейера — chown в run_queue + фильтр статуса в worker

Цель одной фразой: повторный запуск run_queue безопасен (sent-задания не
перегоняются), а результаты на homelab сразу получают владельца twobrain.

## Файлы

- ИЗМЕНИТЬ: `2brain/win-worker/run_queue.py`
- ИЗМЕНИТЬ: `2brain/gpu-worker/worker.py`
- СОЗДАТЬ: `2brain/tests/test_worker_filter.py`
- НЕ ТРОГАТЬ: остальное (daemon.py, router.py, processors.py, config.py, тесты других модулей).

## Контекст (факты)

- run_queue.py (рабочий ПК) ходит по SSH `root@192.168.2.9`, распаковывает
  результаты в `/srv/2brain/_Drop/_results` ТАРОМ ОТ ROOT. Демон работает от
  `twobrain` и падает на чужих владельцах (инцидент 2026-09-08). На homelab
  будет cron-хук chown каждые 5 мин; здесь добавляем мгновенный chown в момент
  возврата, чтобы окно в 5 минут не существовало.
- worker.py исполняет ВСЕ манифесты из jobs/ без фильтра статуса. После
  успешного возврата run_queue помечает манифесты `sed 's/waiting_approval/sent/'`.
  Повторный запуск раннера перегоняет sent-задания заново (часы лишней работы).
- SSH-константа уже есть в run_queue.py: `SSH = ["ssh", "-o", "ConnectTimeout=10",
  "root@192.168.2.9"]`. Константа `REMOTE_RESULTS = "/srv/2brain/_Drop/_results"`.

## Правка 1 — run_queue.py

В `main()`, в блоке «3) вернуть результаты на homelab»: сразу ПОСЛЕ успешной
распаковки результатов (после `pr` с `mkdir -p ... && tar -C ... -xf -`,
проверки returncode) и ДО sed-цикла добавить:

```python
        # раннер пишет в _results от root — возвращаем владение twobrain сразу,
        # не дожидаясь cron-хука на homelab (демон работает от twobrain)
        subprocess.run(SSH + [f"chown -R twobrain:twobrain {REMOTE_RESULTS}"],
                       capture_output=True, timeout=60)
```

Больше в файле ничего не менять.

## Правка 2 — worker.py

2а. Добавить чистую функцию (рядом с main, до неё):

```python
def should_run(m: dict) -> bool:
    """Гоняем только задания, ждущие запуска. sent/done/failed уже исполнены
    (run_queue помечает sent после возврата) — повторный запуск раннера
    не должен перегонять их заново."""
    return m.get("status") in (None, "", "waiting_approval")
```

2б. В `main()` в цикле по манифестам, сразу после `m = json.loads(...)`:

```python
        if not should_run(m):
            print(f"[{m['id']}] skip: status={m.get('status')}", flush=True)
            continue
```

## Правка 3 — тест test_worker_filter.py

unittest в стиле соседних тестов (посмотри `2brain/tests/test_daemon_handle_pdf.py`).
Импорт: worker.py лежит в `2brain/gpu-worker/` (дефис в имени папки!) — соседние
тесты решают это по-своему, посмотри как; если никто не импортирует worker —
используй importlib.util.spec_from_file_location по абсолютному пути от
`Path(__file__).parents[2] / "gpu-worker" / "worker.py"`. ВАЖНО: импорт
worker.py не должен тянуть torch/docling на уровне модуля — проверь его
импорты; если тянет, а тесты падают по этому поводу — фикси через
заглушку sys.modules ПЕРЕД импортом (mock), а не правкой worker.py.

Кейсы:
- `{"status": "waiting_approval"}` → True
- `{"status": "sent"}` → False
- `{"status": "done"}` → False
- `{"status": "failed"}` → False
- `{}` (нет поля) → True
- `{"status": None}` → True

## Критерий приёмки

Команда (из корня репо, Git Bash):
`/c/Users/Us/2brain-worker/venv/Scripts/python.exe -m unittest discover -s 2brain/tests -t . -v`
— все тесты зелёные (старые 7 + новые).

## Ограничения

- Дифф ≤80 строк, без новых зависимостей, без правок вне перечисленных файлов.
- Стиль — как в окружающем коде (русские комментарии только где без них не понять).

## Лимит

3 попытки. Не смог — создай `flash-pilot/BLOCKERS-ownerfix.md`: что пробовал,
точный текст ошибок, минимальный воспроизводимый пример.
