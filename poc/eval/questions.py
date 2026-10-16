"""Eval question loading and URL normalisation shared by every harness.

Two input formats:
  * JSONL (poc/eval/seed.jsonl): id, category, type, question,
    expected_sources [list], must_mention [list]
  * the canonical Markdown table in docs/eval-questions.md:
    | ID | Category | Type | Question | Expected sources | Must mention |
    expected sources and must-mention items both separated by <br> (a fact may
    contain ';'), '—' (or '-' / empty) meaning none. Must-mention items that
    start with "BEHAVIOR:" are behaviour checks for the judge, not facts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

TYPES = {"answerable", "negative", "out-of-scope", "unanswerable", "false-premise", "adversarial"}
ABSTAIN_TYPES = {"out-of-scope", "unanswerable", "adversarial"}  # abstain/decline (adversarial only without sources)


def must_abstain(q: dict) -> bool:
    """Unanswerable and out-of-scope rows, and adversarial rows WITHOUT expected sources, must abstain.
    Answerable, negative, false-premise and adversarial rows that wrap a real question must answer."""
    return q["type"] in ("out-of-scope", "unanswerable") or (q["type"] == "adversarial" and not q["expected_sources"])
NONE_MARKS = {"", "—", "–", "-", "n/a", "none"}


def normalize_url(url: str) -> str:
    """Drop scheme, #fragment, ?query and trailing slash; lower-case host.
    GitHub blob/tree/raw URLs lose their ref: github.com/<org>/<repo>/<path>.
    A bare repo URL maps to its README.md."""
    url = url.strip().strip("<>").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host == "raw.githubusercontent.com":
        segs = path.strip("/").split("/")
        if len(segs) >= 4:  # org/repo/ref/path...
            return "github.com/" + "/".join(segs[:2] + segs[3:])
    if host == "github.com":
        segs = path.strip("/").split("/")
        if len(segs) >= 4 and segs[2] in ("blob", "tree", "raw", "edit"):
            return "github.com/" + "/".join(segs[:2] + segs[4:])
        if len(segs) == 2:
            return f"github.com/{segs[0]}/{segs[1]}/README.md"
    return host + path


def _split_sources(cell: str) -> list[str]:
    cell = cell.strip()
    if cell.lower() in NONE_MARKS:
        return []
    out = []
    for part in re.split(r"<br\s*/?>", cell, flags=re.I):
        part = part.strip()
        m = re.search(r"\((https?://[^)\s]+)\)", part)  # tolerate [text](url)
        part = m.group(1) if m else part.strip("`<> ")
        if part and part.lower() not in NONE_MARKS:
            out.append(part)
    return out


def _split_items(cell: str) -> list[str]:
    cell = cell.strip()
    if cell.lower() in NONE_MARKS:
        return []
    parts = re.split(r"<br\s*/?>", cell, flags=re.I)
    return [f.strip() for f in parts if f.strip() and f.strip().lower() not in NONE_MARKS]


def parse_markdown_table(text: str) -> list[dict]:
    rows = []
    header = None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        # split on unescaped pipes
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if header is None:
            if [c.lower() for c in cells[:3]] == ["id", "category", "type"]:
                header = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        if len(cells) < 6:
            continue
        qid, cat, typ, question, sources, facts = cells[:6]
        typ = typ.lower().strip()
        items = _split_items(facts)
        rows.append({
            "id": qid,
            "category": cat,
            "type": typ,
            "question": question,
            "expected_sources": _split_sources(sources),
            "must_mention": [f for f in items if not f.upper().startswith("BEHAVIOR:")],
            "behavior": [f for f in items if f.upper().startswith("BEHAVIOR:")],
        })
    return rows


def load_questions(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    else:
        rows = parse_markdown_table(path.read_text())
    for r in rows:
        r.setdefault("behavior", [])
        if r["type"] not in TYPES:
            raise ValueError(f"{r['id']}: unknown type {r['type']!r}")
        r["expected_norm"] = sorted({normalize_url(u) for u in r["expected_sources"]})
    return rows


if __name__ == "__main__":
    import sys

    qs = load_questions(sys.argv[1])
    from collections import Counter

    print(len(qs), Counter(q["type"] for q in qs))
    for q in qs[:3]:
        print(q)
