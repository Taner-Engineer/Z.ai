"""Работа с хранилищем 2brain по доктрине CLAUDE.md.

Правила, которые соблюдает этот модуль:
- Inbox.md — append-only: строки дописываются в конец и помечаются [x], не удаляются
- frontmatter — 12 полей (v2: + text, desc), порядок сохранён
- заметки-материалы живут в _llm/notes/; полные тексты — в Books/, Normatives/,
  Knowledge/, Projects/<имя>/ (путь в поле text)
- имена файлов без запрещённых символов, дата только в captured
- _raw/ — ГГГГ-ММ-ДД-<type>-<id>.<ext>
"""
import datetime
import re
from pathlib import Path

import config

FORBIDDEN = re.compile(r'[\\/:*?"<>|]')
NORMATIVE_RE = re.compile(r"^\s*(СП|ГОСТ(\s+Р)?|СНиП|СТО|ТУ|МДК|РД|ВСН|ПУЭ)\b")

FRONTMATTER_FIELDS = [
    "title", "type", "scope", "status", "source_url", "captured",
    "raw", "text", "desc", "template_version", "tags", "related",
]


def today() -> str:
    return datetime.date.today().isoformat()


def sanitize(name: str) -> str:
    """Имя файла заметки: без запрещённых символов, без краевых пробелов и точки."""
    name = FORBIDDEN.sub("", name).strip().rstrip(".")
    return name[:120] or "Без названия"


def parse_inbox_tags(text: str) -> tuple[str, list[str]]:
    """Строка Inbox -> (остаток без тегов, список тегов)."""
    tags = re.findall(r"#([^\s#]+)", text)
    rest = re.sub(r"\s*#[^\s#]+", "", text).strip()
    return rest, tags


def type_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("type/"):
            return t.split("/", 1)[1]
    return None


def project_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("project/"):
            return t.split("/", 1)[1]
    return None


class Inbox:
    """Inbox.md: чтение неразобранных строк, пометка обработанных."""

    def __init__(self):
        self.path = config.INBOX

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def pending_lines(self) -> list[tuple[int, str]]:
        """[(номер строки, содержимое)] для строк '- [ ] ...'.
        Строки внутри ```-блоков (документация формата в шапке Inbox) пропускаются."""
        out, in_fence = [], False
        for i, line in enumerate(self.read().splitlines()):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and re.match(r"\s*- \[ \] ", line):
                out.append((i, line))
        return out

    def append_captures(self, items: list[str]):
        """Дописать новые строки-захваты в конец раздела '## Захваты'."""
        if not items:
            return
        text = self.read()
        anchor = "## Захваты"
        if anchor not in text:
            text = text.rstrip() + "\n\n## Захваты\n"
        lines = [f"- [ ] {today()} {it}" for it in items]
        text = text.rstrip() + "\n" + "\n".join(lines) + "\n"
        self.path.write_text(text, encoding="utf-8")

    def mark_done(self, line_no: int, ref: str):
        """- [ ] ... -> - [x] ... -> [[ссылка]] (строка не удаляется)."""
        lines = self.read().splitlines()
        lines[line_no] = re.sub(
            r"^(\s*)- \[ \] ", r"\1- [x] ", lines[line_no], count=1
        ).rstrip() + f" → {ref}"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Watchlist:
    def __init__(self):
        self.path = config.WATCHLIST

    def append(self, title: str, tags: list[str], comment: str = ""):
        tag_str = " " + " ".join(f"#{t}" for t in tags) if tags else ""
        line = f"- [ ] {today()} {title}{tag_str}"
        if comment:
            line += f" — {comment}"
        text = self.path.read_text(encoding="utf-8").rstrip() + "\n" + line + "\n"
        self.path.write_text(text, encoding="utf-8")


def note_path(title: str, scope: str) -> Path:
    """Путь заметки: все заметки-материалы в _llm/notes/ (scope живёт во frontmatter);
    коллизии — суффикс."""
    config.LLM_NOTES.mkdir(parents=True, exist_ok=True)
    base = sanitize(title)
    p = config.LLM_NOTES / f"{base}.md"
    n = 2
    while p.exists():
        p = config.LLM_NOTES / f"{base} ({n}).md"
        n += 1
    return p


def fulltext_dir(scope: str, ntype: str, title: str) -> Path:
    """Каталог полного текста: books -> Books/, проект -> Projects/<имя>/,
    doc-норматив (СП/ГОСТ/СНиП/...) -> Normatives/, остальное -> Knowledge/."""
    if scope.startswith("project/"):
        d = config.PROJECTS / scope.split("/", 1)[1]
    elif scope == "books":
        d = config.BOOKS
    elif ntype == "doc" and NORMATIVE_RE.match(title):
        d = config.NORMS
    else:
        d = config.KNOWLEDGE
    d.mkdir(parents=True, exist_ok=True)
    return d


def fulltext_path(title: str, scope: str = "global", ntype: str = "doc") -> Path:
    """Файл полного текста в тематической папке; коллизии — суффикс."""
    d = fulltext_dir(scope, ntype, title)
    base = sanitize(title)
    p = d / f"{base}.md"
    n = 2
    while p.exists():
        p = d / f"{base} ({n}).md"
        n += 1
    return p


def render_stub(title: str, ntype: str, scope: str, source_url: str,
                captured: str, raw: str, tags: list[str]) -> str:
    """Заметка-заглушка из полей доктрины (шаблон Заметка.md, версия 2)."""
    tags = list(dict.fromkeys([f"type/{ntype}"] + tags))  # type-тег первым, без дублей
    fm = [
        "---",
        f"title: \"{title}\"",
        f"type: \"{ntype}\"",
        f"scope: \"{scope}\"",
        "status: \"queued\"",
        f"source_url: \"{source_url}\"",
        f"captured: \"{captured}\"",
        f"raw: \"{raw}\"",
        "text: \"\"",
        "desc: \"\"",
        "template_version: 2",
        f"tags: [{', '.join(t for t in tags)}]",
        "related: []",
        "---",
        "",
        "## Карта",
        "",
    ]
    return "\n".join(fm)


def create_note(title: str, ntype: str, scope: str, source_url: str,
                captured: str, raw: str, tags: list[str]) -> Path:
    p = note_path(title, scope)
    p.write_text(render_stub(title, ntype, scope, source_url, captured, raw, tags),
                 encoding="utf-8")
    return p


def fm_get(note: Path, key: str) -> str:
    """Значение строкового поля frontmatter (пусто, если нет)."""
    m = re.search(rf'^{key}: "([^"]*)"', note.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else ""


def set_field(note: Path, key: str, value: str):
    """Поменять одно поле frontmatter; отсутствующее — вставить перед template_version."""
    text = note.read_text(encoding="utf-8")
    if re.search(rf"^{key}: ", text, flags=re.M):
        text = re.sub(rf"^{key}: .*", f'{key}: "{value}"', text, count=1, flags=re.M)
    else:
        text = re.sub(r"^template_version:", f'{key}: "{value}"\ntemplate_version:',
                      text, count=1, flags=re.M)
    note.write_text(text, encoding="utf-8")


def set_status(note: Path, status: str):
    """Поменять только поле status в frontmatter, остальное не трогать."""
    set_field(note, "status", status)


def wiki_ref(note: Path) -> str:
    rel = note.relative_to(config.VAULT)
    return f"[[{str(rel)[:-3]}]]"


def raw_name(kind: str, ident: str, ext: str = "json") -> Path:
    p = config.RAW / f"{today()}-{kind}-{sanitize(ident)}.{ext}"
    n = 2
    while p.exists():
        p = config.RAW / f"{today()}-{kind}-{sanitize(ident)}-{n}.{ext}"
        n += 1
    return p


def attach_name(title: str, ext: str = "md") -> Path:
    config.ATTACH.mkdir(exist_ok=True)
    p = config.ATTACH / f"{today()}-{sanitize(title)}.{ext}"
    n = 2
    stem = f"{today()}-{sanitize(title)}"
    while p.exists():
        p = config.ATTACH / f"{stem}-{n}.{ext}"
        n += 1
    return p
