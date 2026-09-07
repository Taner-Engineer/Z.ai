"""Работа с хранилищем 2brain по доктрине CLAUDE.md.

Правила, которые соблюдает этот модуль:
- Inbox.md — append-only: строки дописываются в конец и помечаются [x], не удаляются
- frontmatter — 10 полей (v2: notebook_id выпилен), порядок сохранён
- имена файлов без запрещённых символов, дата только в captured
- _raw/ — ГГГГ-ММ-ДД-<type>-<id>.<ext>, _Attachments/ — ГГГГ-ММ-ДД-<описание>.<ext>
"""
import datetime
import re
from pathlib import Path

import config

FORBIDDEN = re.compile(r'[\\/:*?"<>|]')

FRONTMATTER_FIELDS = [
    "title", "type", "scope", "status", "source_url", "captured",
    "raw", "template_version", "tags", "related",
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
    """Путь заметки по доктрине: Knowledge/ или Projects/<имя>/; коллизии — суффикс."""
    if scope.startswith("project/"):
        d = config.PROJECTS / scope.split("/", 1)[1]
    else:
        d = config.KNOWLEDGE
        scope = "global"
    d.mkdir(parents=True, exist_ok=True)
    base = sanitize(title)
    p = d / f"{base}.md"
    n = 2
    while p.exists():
        p = d / f"{base} ({n}).md"
        n += 1
    return p


def render_stub(title: str, ntype: str, scope: str, source_url: str,
                captured: str, raw: str, tags: list[str]) -> str:
    """Заметка-заглушка из полей доктрины (шаблон Заметка.md, поле notebook_id выпилено)."""
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
        "template_version: 1",
        f"tags: [{', '.join(t for t in tags)}]",
        "related: []",
        "---",
        "",
        "## Суть",
        "",
        "## Заметки",
        "",
    ]
    return "\n".join(fm)


def create_note(title: str, ntype: str, scope: str, source_url: str,
                captured: str, raw: str, tags: list[str]) -> Path:
    p = note_path(title, scope)
    p.write_text(render_stub(title, ntype, scope, source_url, captured, raw, tags),
                 encoding="utf-8")
    return p


def set_status(note: Path, status: str):
    """Поменять только поле status в frontmatter, остальное не трогать."""
    text = note.read_text(encoding="utf-8")
    text = re.sub(r'(^status: )"([^"]*)"', rf'\1"{status}"', text, count=1, flags=re.M)
    note.write_text(text, encoding="utf-8")


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
