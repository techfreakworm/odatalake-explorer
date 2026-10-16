"""[n] citations: parse, validate, renumber by first use, map to source URLs (contract I2).

The model cites passage numbers. The /ask contract returns deduplicated `sources`, so markers are renumbered to
positions in `sources` ([1] = sources[0]). Code (fenced blocks and inline spans) is never rewritten: configs must be
copied exactly, and `[8000]` in a YAML block is not a citation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.models import Passage

MAX_SOURCES = 5

# one item: n or n-m (1-99, so "[2026]" or "[100]" in prose is left alone)
_ITEM = r"\d{1,2}(?:\s*[-–]\s*\d{1,2})?"
# a citation group: [1], [1, 3], [2-4], [^1]; not a Markdown link "[1](...)"
_GROUP = rf"\[\^?\s*{_ITEM}(?:\s*,\s*{_ITEM})*\s*\](?!\()"
GROUP_RE = re.compile(_GROUP)
# a run of groups separated by horizontal whitespace at most: "[1][3]", "[2] [3]"
RUN_RE = re.compile(rf"([ \t]*)({_GROUP}(?:[ \t]*{_GROUP})*)")
_INLINE_CODE_RE = re.compile(r"``[^`]+(?:`[^`]+)*``|`[^`\n]+`")
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
_AFTER_REMOVED = set(".,;:!?)]}\n")

_SOURCES_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?[*_]*\s*(?:sources|references|citations)\s*:?\s*[*_]*\s*:?\s*"
    rf"(?:(?:{_GROUP})[\s,;]*)*$",
    re.I,
)
_REF_LINE_RE = re.compile(rf"^\s*(?:$|[-*+]\s|\d+[.)]\s|{_GROUP}|https?://)")


@dataclass(frozen=True)
class CitedSource:
    n: int  # the renumbered marker: sources[n - 1] == url
    url: str
    passage: Passage  # the first passage cited for this source


@dataclass(frozen=True)
class CitationResult:
    answer: str
    sources: list[str]
    cited: list[CitedSource]


def segments(text: str) -> list[tuple[bool, str]]:
    """Split Markdown into (is_code, text) pieces: fenced blocks (an unclosed fence runs to the end) and inline code
    spans are code, everything else is prose. Joining the pieces gives the text back unchanged."""
    out: list[tuple[bool, str]] = []
    prose: list[str] = []
    code: list[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        if not fence:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                if prose:
                    out.extend(_split_inline("".join(prose)))
                    prose = []
                fence, code = m.group(1), [line]
            else:
                prose.append(line)
        else:
            code.append(line)
            s = line.strip()
            if s.startswith(fence[0] * len(fence)) and not s.strip(fence[0]):
                out.append((True, "".join(code)))
                fence, code = "", []
    if fence:
        out.append((True, "".join(code)))
    if prose:
        out.extend(_split_inline("".join(prose)))
    return out


def _split_inline(text: str) -> list[tuple[bool, str]]:
    out, pos = [], 0
    for m in _INLINE_CODE_RE.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def _group_numbers(group: str) -> list[int]:
    nums: list[int] = []
    for item in re.findall(_ITEM, group):
        if "-" in item or "–" in item:
            a, b = (int(x) for x in re.split(r"\s*[-–]\s*", item))
            if a <= b and b - a <= 10:
                nums.extend(range(a, b + 1))
            else:
                nums.extend([a, b])
        else:
            nums.append(int(item))
    return nums


def parse_citation_numbers(text: str) -> list[int]:
    """Every cited number in prose, in order of appearance (duplicates kept)."""
    nums: list[int] = []
    for is_code, seg in segments(text):
        if not is_code:
            for m in GROUP_RE.finditer(seg):
                nums.extend(_group_numbers(m.group(0)))
    return nums


def resolve_citations(answer: str, passages: Sequence[Passage], max_sources: int = MAX_SOURCES) -> CitationResult:
    """Keep only valid [n], renumber by first use so [1] = sources[0], merge passages that share a source URL,
    cap sources at max_sources and strip every marker that does not map to a source."""
    by_n = {p.n: p for p in passages}
    sources: list[str] = []
    cited: list[CitedSource] = []
    new_n: dict[int, list[int]] = {}  # passage number -> its source numbers (a fact card can have two)
    segs = segments(answer)
    for is_code, seg in segs:
        if is_code:
            continue
        for m in GROUP_RE.finditer(seg):
            for n in _group_numbers(m.group(0)):
                p = by_n.get(n)
                if p is None or n in new_n:
                    continue
                nums: list[int] = []
                for url in p.urls:
                    if url in sources:
                        nums.append(sources.index(url) + 1)
                    elif len(sources) < max_sources:
                        sources.append(url)
                        cited.append(CitedSource(len(sources), url, p))
                        nums.append(len(sources))
                if nums:
                    new_n[n] = nums

    def rewrite_run(m: re.Match) -> str:
        lead, run = m.group(1), m.group(2)
        mapped: list[int] = []
        for g in GROUP_RE.finditer(run):
            for n in _group_numbers(g.group(0)):
                for k in new_n.get(n, ()):
                    if k not in mapped:
                        mapped.append(k)
        if mapped:
            return lead + "".join(f"[{k}]" for k in mapped)
        nxt = m.string[m.end():m.end() + 1]
        if lead and (nxt == "" or nxt in _AFTER_REMOVED or nxt.isspace()):
            return ""
        return lead

    text = "".join(seg if is_code else RUN_RE.sub(rewrite_run, seg) for is_code, seg in segs)
    return CitationResult(answer=text, sources=sources, cited=cited)


def strip_sources_section(text: str) -> str:
    """Drop a trailing "Sources:" / "References:" list the model may add (the UI renders sources itself, and such a
    list would cite every passage). Kept when nothing precedes it."""
    lines = text.rstrip().split("\n")
    for i in range(len(lines) - 1, 0, -1):
        if _SOURCES_HEADER_RE.match(lines[i]):
            if all(_REF_LINE_RE.match(line) for line in lines[i + 1:]):
                head = "\n".join(lines[:i]).rstrip()
                return head if head else text
            break
    return text


def salvage_truncated(text: str, max_n: int) -> str:
    """Keep a truncated answer up to and including its last valid citation (and the punctuation right after it).
    Returns "" when no valid citation is left. Cuts only in prose, so no code fence is left open."""
    cut = -1
    pos = 0
    for is_code, seg in segments(text):
        if not is_code:
            for m in GROUP_RE.finditer(seg):
                if any(1 <= n <= max_n for n in _group_numbers(m.group(0))):
                    end = m.end()
                    while end < len(seg) and seg[end] in ".!?)":
                        end += 1
                    cut = pos + end
        pos += len(seg)
    return text[:cut].rstrip() if cut >= 0 else ""


def source_url(chunk: Mapping[str, Any], style: str = "branch") -> str:
    """The URL a cited chunk contributes to `sources` (fact cards: see choose_cite_urls in retrieval)."""
    if chunk.get("source_type") == "repo" and style == "sha" and chunk.get("url"):
        return str(chunk["url"])
    return str(chunk["doc_url"])


def citation_details(cited: Sequence[CitedSource]) -> list[dict]:
    """The SSE done.citations entries: {n, url, label, title, source_type, snippet} per source."""
    out = []
    for c in cited:
        ch = c.passage.chunk
        st = str(ch.get("source_type") or "docs")
        url = c.url if st == "factcard" else str(ch.get("url") or c.url)
        out.append({
            "n": c.n,
            "url": url,
            "label": _label(ch, st),
            "title": str(ch.get("title") or ""),
            "source_type": st,
            "snippet": _snippet(str(ch.get("text") or "")),
        })
    return out


def _label(ch: Mapping[str, Any], st: str) -> str:
    doc_url = str(ch.get("doc_url") or "")
    if st == "repo":
        m = re.search(r"/blob/[^/]+/(.+)$", doc_url)
        path = m.group(1) if m else str(ch.get("title") or "")
        repo = ch.get("repo") or ""
        sha7 = str(ch.get("commit") or "")[:7]
        lines = ch.get("lines")
        label = f"{repo}@{sha7} · {path}" if repo and sha7 else path
        if lines and len(lines) == 2:
            label += f" L{lines[0]}-L{lines[1]}"
        return label
    if st == "release-gh":
        m = re.search(r"/releases/tag/([^/?#]+)", doc_url)
        return m.group(1) if m else str(ch.get("title") or "")
    if st == "issue":
        m = re.search(r"/issues/(\d+)", doc_url)
        return f"issue #{m.group(1)}" if m else "issue"
    if st == "outside":
        if "amoro.apache.org" in doc_url:
            return "upstream Amoro; Fusion may differ"
        return "outside OLake docs"
    if st == "factcard":
        return "fact card"
    if st == "blog":
        return "blog"
    path = [str(x) for x in (ch.get("section_path") or []) if x]
    return " › ".join(path) if path else str(ch.get("title") or "")


def _snippet(text: str, limit: int = 240) -> str:
    body = text.split("\n", 1)[1] if "\n" in text else text
    body = re.sub(r"\s+", " ", body).strip()
    return body if len(body) <= limit else body[:limit].rstrip() + "…"
