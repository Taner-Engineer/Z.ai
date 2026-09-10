# claude-drawings — How to Get Claude to Actually Read Construction Drawings (Drawing Set → Database) (video)

Сырьё: `C:\Users\Us\Vaults\2brain\_raw\2026-08-30-youtube-a8T_3H0lL_E.json` (yt-dlp json: title, duration 1203 с, description).

## Карта

* **Бенчмарк чтения строительных чертежей ИИ (Drawing Set → Database)** — охватывает: почему комплекты чертежей ломают модели (126 вопросов на 5 реальных комплектах), и настройку «подключённая папка + предзагруженный контекст + SQLite-база вместо повторного чтения PDF», поднявшую точность Claude с ~75% на сырых PDF до >90%, включая оставшиеся сбои (подсчёт одинаковых условных обозначений).

## Сверка

* Охват подтверждён `python`-чтением ключа `description` сырья (1899 симв.): перечислены бенчмарк (126 вопросов / 5 комплектов, 75% → 90%+), векторные данные PDF, «front loading» контекстной папки, запросы к структурированной базе, предел подхода — symbol counting; ключ `chapters`/`duration` = 1203 с.
* Ручные субтитры в JSON отсутствуют (`subtitles: []`, только automatic_captions); содержательная сверка покрытия — с существующей выжимкой «Суть» заметки `C:\Users\Us\Vaults\2brain\Knowledge\How to Get Claude to Actually Read Construction Drawings (Drawing Set → Database).md` (Drawing Analyzer, контекстная папка Markdown, SQLite vs Excel/CSV, экономия токенов) — расхождений с description нет.
* Одна строка, без пересказа тезисов — только тема и охват.
