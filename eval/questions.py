"""The eval question table (contract I3) and the lenient URL normalization (ported from poc/eval/questions.py).

    | ID | Category | Type | Question | Expected sources | Must mention |

* cells split on unescaped `|`, and `\\|` unescapes to `|`;
* Expected sources AND Must mention both split on `<br>` (never on `;`, since facts may contain it);
* `—` (or `-`, `n/a`, `none`, empty) means none;
* a Must-mention item that starts with `BEHAVIOR:` is a behaviour check for the judge, never a fact;
* the table is found by its first three header cells (ID, Category, Type); every later row with 6 cells is a question.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

QUESTIONS_FILE = Path(__file__).resolve().parent / "questions.md"
TYPES = ("answerable", "negative", "false-premise", "adversarial", "out-of-scope", "unanswerable")
NONE_MARKS = {"", "—", "–", "-", "n/a", "none"}


def must_abstain(q: dict) -> bool:
    """Unanswerable and out-of-scope rows, and adversarial rows WITHOUT expected sources, must abstain or decline.
    Answerable, negative, false-premise and adversarial rows that wrap a real question must answer."""
    return q["type"] in ("out-of-scope", "unanswerable") or (q["type"] == "adversarial" and not q["expected_sources"])


def normalize_url(url: str) -> str:
    """Drop the scheme, #fragment, ?query, `www.` and a trailing slash; lowercase the host. GitHub blob, tree, raw and
    edit URLs (and raw.githubusercontent.com URLs) lose their git ref; a bare repo URL maps to its README.md."""
    url = url.strip().strip("<>").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    segs = path.strip("/").split("/")
    if host == "raw.githubusercontent.com" and len(segs) >= 4:  # org/repo/ref/path...
        return "github.com/" + "/".join(segs[:2] + segs[3:])
    if host == "github.com":
        if len(segs) >= 4 and segs[2] in ("blob", "tree", "raw", "edit"):
            return "github.com/" + "/".join(segs[:2] + segs[4:])
        if len(segs) == 2:
            return f"github.com/{segs[0]}/{segs[1]}/README.md"
    return host + path


def split_cells(line: str) -> list[str]:
    """Cells of one Markdown table row: split on unescaped pipes, then unescape `\\|`."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]


def _split_br(cell: str) -> list[str]:
    cell = cell.strip()
    if cell.lower() in NONE_MARKS:
        return []
    parts = [p.strip() for p in re.split(r"<br\s*/?>", cell, flags=re.I)]
    return [p for p in parts if p and p.lower() not in NONE_MARKS]


def _split_sources(cell: str) -> list[str]:
    out = []
    for part in _split_br(cell):
        m = re.search(r"\((https?://[^)\s]+)\)", part)  # tolerate [text](url)
        part = m.group(1) if m else part.strip("`<> ")
        if part and part.lower() not in NONE_MARKS:
            out.append(part)
    return out


def parse_table(text: str) -> list[dict]:
    rows: list[dict] = []
    in_table = False
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if not in_table:
            in_table = [c.lower() for c in cells[:3]] == ["id", "category", "type"]
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        if len(cells) < 6:
            continue
        qid, cat, typ, question, sources, facts = cells[:6]
        items = _split_br(facts)
        rows.append({
            "id": qid.strip(),
            "category": cat.strip(),
            "type": typ.strip().lower(),
            "question": question.strip(),
            "expected_sources": _split_sources(sources),
            "must_mention": [f for f in items if not f.upper().startswith("BEHAVIOR:")],
            "behavior": [f for f in items if f.upper().startswith("BEHAVIOR:")],
        })
    return rows


def load_questions(path: str | Path = QUESTIONS_FILE) -> list[dict]:
    rows = parse_table(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for r in rows:
        if r["type"] not in TYPES:
            raise ValueError(f"{r['id']}: unknown type {r['type']!r}")
        if r["id"] in seen:
            raise ValueError(f"duplicate question id {r['id']}")
        seen.add(r["id"])
        r["expected_norm"] = sorted({normalize_url(u) for u in r["expected_sources"]})
        r["must_abstain"] = must_abstain(r)
    return rows
