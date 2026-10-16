"""Structure-aware chunker with citation metadata (ported from poc/chunking/chunker.py).

Markdown (docs pages, release notes, repo *.md, spec tables, FAQs, fact cards, outside pages):
  * blocks = paragraphs/lists, fenced code, tables, headings, "**Tab: X**" labels and the
    invisible tab-group markers from ingest/html2md.py. Code fences and tables are atomic: a block
    larger than the hard max is the only thing ever split, code at line boundaries (the fence is
    re-opened), tables at row boundaries (the header row is repeated in every piece).
  * a heading or a tab label starts a section; small consecutive sections are packed up to the
    target. A chunk never spans two tab panels, and its header carries the full tab-label path.
  * every chunk starts with the context header
        "title | product > breadcrumbs > heading path [tab label path]"
    followed by a blank line and the Markdown body.
YAML / JSON: split at the shallowest key level (comments attached to the key below them),
recursing one level deeper for keys that are still too big. Go: split at top-level declarations.

The packer budgets with the exact header of each piece and a final pass re-splits anything that
still exceeds the hard max, so no chunk is ever over CHUNK_HARD_MAX tokens (o200k_base).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

import tiktoken

from index.config import CHUNK_HARD_MAX, CHUNK_TARGET, TOKENIZER
from ingest.config import TIERS
from ingest.html2md import TABS_END, TABS_START

SEP = " > "
TAB_PREFIX = "Tab: "
FIELDS = ("id", "source_type", "tier", "product", "cite_urls", "doc_url", "url", "title", "section_path", "text",
          "tokens", "ord", "anchor", "repo", "commit", "lines", "lastmod", "hash")


@lru_cache(maxsize=1)
def _enc():
    return tiktoken.get_encoding(TOKENIZER)


def ntok(text: str) -> int:
    return len(_enc().encode(text, disallowed_special=()))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- header
def render_header(title: str, lead: str | None, crumbs: list[str], path: list[str]) -> str:
    """"title | lead > crumbs > headings [tab > tab]". The h1 is dropped when it repeats the title."""
    headings = [p for p in path if not p.startswith(TAB_PREFIX)]
    if headings and headings[0].strip().lower() == title.strip().lower():
        headings = headings[1:]
    tabs = [p[len(TAB_PREFIX):] for p in path if p.startswith(TAB_PREFIX)]
    ctx = SEP.join(x for x in [lead or "", *crumbs, *headings] if x)
    head = f"{title} | {ctx}" if ctx else title
    if tabs:
        head += " [" + SEP.join(tabs) + "]"
    return head


# ----------------------------------------------------------------------------- markdown blocks
HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+\{#([^}]+)\})?\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
TAB = re.compile(r"^\*\*Tab: (.+)\*\*$")


@dataclass
class Block:
    kind: str  # heading | code | table | text | tab | tabstart | tabend
    text: str
    start: int  # 1-based line numbers in the source
    end: int
    level: float = 0
    title: str = ""
    anchor: str | None = None
    tokens: int = 0


def is_fence_close(line: str, fence: str) -> bool:
    s = line.strip()
    return s.startswith(fence) and s.strip(fence[0]) == ""


def parse_markdown(md: str) -> list[Block]:
    lines = md.split("\n")
    n, i, out = len(lines), 0, []
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.strip() in (TABS_START, TABS_END):  # structural tab-group markers from html2md
            out.append(Block("tabstart" if line.strip() == TABS_START else "tabend", "", i + 1, i + 1))
            i += 1
            continue
        if line.lstrip().startswith("<!--"):  # HTML comments (license headers, notes) are dropped
            j = i
            while j < n and "-->" not in lines[j]:
                j += 1
            i = j + 1
            continue
        m = FENCE.match(line)
        if m:
            fence = m.group(1)
            j = i + 1
            while j < n and not is_fence_close(lines[j], fence):
                j += 1
            if j < n:
                out.append(Block("code", "\n".join(lines[i:j + 1]), i + 1, j + 1))
            else:  # unterminated fence: close it so every chunk stays valid Markdown
                out.append(Block("code", "\n".join([*lines[i:n], fence]), i + 1, n))
            i = j + 1
            continue
        h = HEADING.match(line)
        if h:
            title = h.group(2).strip()
            text = f"{h.group(1)} {title}"  # the {#anchor} suffix lives in Block.anchor, not in the text
            out.append(Block("heading", text, i + 1, i + 1, level=len(h.group(1)), title=title, anchor=h.group(3)))
            i += 1
            continue
        if line.lstrip().startswith("|"):
            j = i
            while j + 1 < n and lines[j + 1].lstrip().startswith("|"):
                j += 1
            out.append(Block("table", "\n".join(lines[i:j + 1]), i + 1, j + 1))
            i = j + 1
            continue
        j = i
        while j + 1 < n and lines[j + 1].strip() and not FENCE.match(lines[j + 1]) \
                and not HEADING.match(lines[j + 1]) and not lines[j + 1].lstrip().startswith("|") \
                and lines[j + 1].strip() not in (TABS_START, TABS_END):
            j += 1
        text = "\n".join(lines[i:j + 1])
        t = TAB.match(text.strip())
        if t:
            out.append(Block("tab", text.strip(), i + 1, j + 1, title=TAB_PREFIX + t.group(1)))
        else:
            out.append(Block("text", text, i + 1, j + 1))
        i = j + 1
    for b in out:
        b.tokens = ntok(b.text)
    return out


# ----------------------------------------------------------------------------- oversize splitting
def _windows(text: str, room: int) -> list[str]:
    """Split one over-long line: sentences, then words, then raw token windows."""
    if ntok(text) <= room:
        return [text]
    for pattern in (r"(?<=[.!?;:])\s+", r"\s+"):
        parts = [p for p in re.split(pattern, text) if p]
        if len(parts) > 1:
            out, cur = [], ""
            for p in parts:
                cand = f"{cur} {p}" if cur else p
                if cur and ntok(cand) > room:
                    out.append(cur)
                    cur = p
                else:
                    cur = cand
            if cur:
                out.append(cur)
            if all(ntok(x) <= room for x in out):
                return out
            return [w for x in out for w in _windows(x, room)]
    ids = _enc().encode(text, disallowed_special=())
    return [_enc().decode(ids[k:k + room]) for k in range(0, len(ids), max(1, room))]


def split_oversize(b: Block, budget: int) -> list[Block]:
    """Split one block that alone exceeds `budget` tokens, keeping each piece valid Markdown."""
    lines = b.text.split("\n")
    if b.kind == "code" and len(lines) >= 2:
        head, body, tail = lines[0], lines[1:-1], lines[-1]

        def wrap(ls):
            return "\n".join([head, *ls, tail])
        offset = 1
    elif b.kind == "table" and len(lines) >= 2:
        head2, body = lines[:2], lines[2:]

        def wrap(ls):
            return "\n".join([*head2, *ls])
        offset = 2
    else:
        body = lines

        def wrap(ls):
            return "\n".join(ls)
        offset = 0
    room = max(8, budget - ntok(wrap([])) - 1)
    # (source line index within body, text) with over-long single lines expanded
    items: list[tuple[int, str]] = []
    for k, ln in enumerate(body):
        if ntok(ln) + 1 > room:
            items += [(k, w) for w in _windows(ln, room - 1)]
        else:
            items.append((k, ln))
    pieces: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    acc = 0
    for k, ln in items:
        t = ntok(ln) + 1
        if cur and acc + t > room:
            pieces.append(cur)
            cur, acc = [], 0
        cur.append((k, ln))
        acc += t
    if cur:
        pieces.append(cur)
    out = []
    for piece in pieces:
        txt = wrap([ln for _, ln in piece])
        s = b.start + offset + piece[0][0]
        e = b.start + offset + piece[-1][0]
        out.append(Block(b.kind, txt, s, e, tokens=ntok(txt)))
    return out


# ----------------------------------------------------------------------------- sections and packing
@dataclass
class Section:
    path: list[str]          # heading titles and tab labels from the page root to this section
    anchor: str | None       # nearest heading anchor (docs pages)
    blocks: list[Block] = field(default_factory=list)
    tabctx: tuple[int, ...] = ()  # ids of the tab panels this section sits in (unique per panel)

    @property
    def tokens(self) -> int:
        return sum(b.tokens for b in self.blocks) + 2 * max(0, len(self.blocks) - 1)


def sections_of(blocks: list[Block]) -> list[Section]:
    """Split blocks into sections. The stack holds headings and tab labels; tab-group markers record
    where a group began, so a sibling tab replaces the previous tab and everything under it, a
    heading inside a panel never pops the panel's tab label, and text after a group's end marker
    starts a new section in the parent context (it belongs to no tab of that group). Every panel
    gets its own id, so two panels never share a tab context even when their labels are equal."""
    stack: list[tuple[str, float, str, str | None, int]] = []  # (kind, level, title, anchor, panel id)
    groups: list[int] = []  # stack depth at each open tab group
    panels = 0

    def snapshot(anchor: str | None, blocks: list[Block] | None = None) -> Section:
        return Section([t for _, _, t, _, _ in stack], anchor, list(blocks or []),
                       tuple(pid for kind, _, _, _, pid in stack if kind == "tab"))

    def nearest_anchor() -> str | None:
        return next((a for _, _, _, a, _ in reversed(stack) if a), None)

    secs = [snapshot(None)]
    for b in blocks:
        if b.kind == "tabstart":
            groups.append(len(stack))
            continue
        if b.kind == "tabend":
            if groups:
                del stack[groups.pop():]
            secs.append(snapshot(nearest_anchor()))
            continue
        if b.kind == "tab":
            if groups:
                del stack[groups[-1]:]
            else:  # unmatched label: replace a trailing tab label
                while stack and stack[-1][0] == "tab":
                    stack.pop()
            panels += 1
            anchor = nearest_anchor()
            stack.append(("tab", stack[-1][1] if stack else 0, b.title, anchor, panels))
            secs.append(snapshot(anchor, [b]))
            continue
        if b.kind == "heading":
            floor = groups[-1] + 1 if groups else 0  # never pop the open panel's tab label
            while len(stack) > floor and stack[-1][0] == "heading" and stack[-1][1] >= b.level:
                stack.pop()
            anchor = b.anchor or nearest_anchor()
            stack.append(("heading", b.level, b.title, anchor, 0))
            secs.append(snapshot(anchor, [b]))
            continue
        secs[-1].blocks.append(b)
    return [s for s in secs if s.blocks]


def common_prefix(a: list[str], b: list[str]) -> list[str]:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return out


@dataclass
class Piece:
    path: list[str]                # header path
    section_path: list[str]        # full path of the first section in the piece
    anchor: str | None
    tabctx: tuple[int, ...]
    blocks: list[Block] = field(default_factory=list)
    tokens: int = 0

    @property
    def body(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    def add(self, b: Block) -> None:
        self.tokens += (2 if self.blocks else 0) + b.tokens
        self.blocks.append(b)


HeaderFn = Callable[[list[str]], str]


def pack_markdown(blocks: list[Block], header_of: HeaderFn, target: int = CHUNK_TARGET,
                  hard_max: int = CHUNK_HARD_MAX) -> list[Piece]:
    """Pack sections into pieces whose rendered text (header + body) is <= hard_max, aiming at target."""

    def hdr(path: list[str]) -> int:
        return ntok(header_of(path)) + 2

    out: list[Piece] = []
    cur: Piece | None = None
    for sec in sections_of(blocks):
        # a heading section's header is its parent path (the heading line opens the body); a tab
        # section keeps the tab label in the header: title | ... [Tab label]
        parent = sec.path[:-1] if sec.blocks[0].kind == "heading" else sec.path
        tc = sec.tabctx
        if cur is not None and cur.tabctx == tc and cur.blocks:
            common = common_prefix(cur.path, parent)
            if cur.tokens + 2 + sec.tokens <= target - hdr(common):
                for b in sec.blocks:
                    cur.add(b)
                cur.path = common
                continue
        if cur is not None and cur.blocks:
            out.append(cur)
        cur = Piece(parent, sec.path, sec.anchor, tc)
        limit = target - hdr(sec.path)
        body_max = hard_max - hdr(sec.path)
        for b in sec.blocks:
            parts = split_oversize(b, body_max) if b.tokens > body_max else [b]
            for p in parts:
                if cur.blocks and cur.tokens + 2 + p.tokens > limit:
                    out.append(cur)
                    cur = Piece(sec.path, sec.path, sec.anchor, tc)
                cur.add(p)
    if cur is not None and cur.blocks:
        out.append(cur)

    # fold tiny pieces (< target/5) into a neighbour when the result stays under the hard max
    merged: list[Piece] = []
    for p in out:
        prev = merged[-1] if merged else None
        if prev and (prev.tokens < target / 5 or p.tokens < target / 5) and prev.tabctx == p.tabctx:
            common = common_prefix(prev.path, p.path)
            if prev.tokens + 2 + p.tokens <= hard_max - hdr(common):
                for b in p.blocks:
                    prev.add(b)
                prev.path = common
                continue
        merged.append(p)

    # exact check: re-split anything whose rendered text is still over the hard max
    final: list[Piece] = []
    for p in merged:
        final += enforce_hard_max(p, header_of, hard_max)
    return final


def enforce_hard_max(p: Piece, header_of: HeaderFn, hard_max: int) -> list[Piece]:
    header = header_of(p.path)
    if ntok(render(header, p.body)) <= hard_max:
        return [p]
    if len(p.blocks) > 1:
        half, acc, total = 1, 0, sum(b.tokens for b in p.blocks)
        for k, b in enumerate(p.blocks):
            acc += b.tokens
            if acc >= total / 2:
                half = max(1, min(len(p.blocks) - 1, k + (1 if k == 0 else 0)))
                break
        left = Piece(p.path, p.section_path, p.anchor, p.tabctx)
        right = Piece(p.path, p.section_path, p.anchor, p.tabctx)
        for b in p.blocks[:half]:
            left.add(b)
        for b in p.blocks[half:]:
            right.add(b)
        return enforce_hard_max(left, header_of, hard_max) + enforce_hard_max(right, header_of, hard_max)
    budget = hard_max - ntok(header) - 4
    parts = split_oversize(p.blocks[0], budget)
    if len(parts) <= 1:  # cannot split further (should not happen): shrink the budget
        parts = split_oversize(p.blocks[0], max(16, budget // 2))
    out = []
    for b in parts:
        q = Piece(p.path, p.section_path, p.anchor, p.tabctx)
        q.add(b)
        out += enforce_hard_max(q, header_of, hard_max) if len(parts) > 1 else [q]
    return out


def render(header: str, body: str) -> str:
    return f"{header}\n\n{body}"


@dataclass
class Rendered:
    text: str
    section_path: list[str]
    anchor: str | None
    start: int
    end: int


def chunk_markdown(md: str, *, title: str, lead: str | None = None, crumbs: list[str] | None = None,
                   target: int = CHUNK_TARGET, hard_max: int = CHUNK_HARD_MAX) -> list[Rendered]:
    crumbs = crumbs or []

    def header_of(path: list[str]) -> str:
        return render_header(title, lead, crumbs, path)

    out = []
    for p in pack_markdown(parse_markdown(md), header_of, target, hard_max):
        out.append(Rendered(render(header_of(p.path), p.body), p.section_path, p.anchor,
                            p.blocks[0].start, p.blocks[-1].end))
    return out


# ----------------------------------------------------------------------------- yaml / json / go
YAML_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.\-]+|\"[^\"]+\"|'[^']+')\s*:(\s|$)")
JSON_KEY = re.compile(r"^(\s*)\"([^\"]+)\"\s*:")
GO_DECL = re.compile(r"^(func|type|var|const|import)\b\s*(\([^)]*\)\s*)?(\w+)?")


def key_lines(lines: list[str], kind: str, lo: int, hi: int) -> list[tuple[int, int, str]]:
    """(line index, indent, key) for structural boundaries within [lo, hi)."""
    out = []
    for k in range(lo, hi):
        ln = lines[k]
        if kind == "go":
            m = GO_DECL.match(ln)
            if m:
                out.append((k, 0, (m.group(3) or m.group(1))))
            continue
        m = (YAML_KEY if kind == "yaml" else JSON_KEY).match(ln)
        if m and not ln.lstrip().startswith("- "):
            out.append((k, len(m.group(1).expandtabs(2)), m.group(2).strip("\"'")))
    return out


def attach_comments(lines: list[str], k: int, lo: int, kind: str) -> int:
    """Move a boundary up over the comment lines that document the key below them."""
    prefix = "#" if kind == "yaml" else "//"
    while k - 1 >= lo and (lines[k - 1].strip().startswith(prefix) or (
            kind == "go" and not lines[k - 1].strip() and k - 2 >= lo and lines[k - 2].strip().startswith(prefix))):
        k -= 1
    return k


def line_pack(lines: list[str], lo: int, hi: int, path: list[str], budget: int) -> list[dict]:
    out, a, acc = [], lo, 0
    for k in range(lo, hi):
        t = ntok(lines[k]) + 1
        if acc and acc + t > budget:
            out.append({"path": path, "lo": a, "hi": k})
            a, acc = k, 0
        acc += t
    if a < hi:
        out.append({"path": path, "lo": a, "hi": hi})
    return out


def struct_split(lines: list[str], kind: str, lo: int, hi: int, path: list[str], target: int, hard_max: int,
                 depth: int = 0) -> list[dict]:
    text = "\n".join(lines[lo:hi])
    if ntok(text) <= target or depth > 3:
        if ntok(text) > hard_max:
            return line_pack(lines, lo, hi, path, hard_max)
        return [{"path": path, "lo": lo, "hi": hi}] if text.strip() else []
    keys = key_lines(lines, kind, lo, hi)
    if kind != "go":
        if not keys:
            return line_pack(lines, lo, hi, path, hard_max)
        min_indent = min(ind for _, ind, _ in keys)
        keys = [(k, ind, name) for k, ind, name in keys if ind == min_indent]
        keys = [x for x in keys if x[0] != lo or depth == 0]  # a nested range's own key line is no split point
    if len(keys) < 2:
        if kind != "go" and keys and depth < 3:
            # single big key: descend into its body; the key line (and its comments) is folded into
            # the first sub-chunk so line ranges stay contiguous
            k, name = keys[0][0], keys[0][2]
            sub_path = path if path and path[-1] == name else path + [name]
            sub = struct_split(lines, kind, k + 1, hi, sub_path, target, hard_max, depth + 1)
            if not sub:
                return [{"path": sub_path, "lo": lo, "hi": hi}]
            sub[0]["lo"] = lo
            sub[0].pop("tok", None)
            return sub
        return line_pack(lines, lo, hi, path, hard_max)
    bounds = [lo] + [attach_comments(lines, k, lo, kind) for k, _, _ in keys] + [hi]
    names = ["(preamble)"] + [name for _, _, name in keys]
    segs = []
    for (a, b), name in zip(zip(bounds, bounds[1:]), names):
        if b <= a or not "\n".join(lines[a:b]).strip():
            continue
        seg_tok = ntok("\n".join(lines[a:b]))
        if seg_tok > hard_max:
            if kind == "go":
                segs += line_pack(lines, a, b, path + [name], hard_max)
            else:
                segs += struct_split(lines, kind, a, b, path + [name], target, hard_max, depth + 1)
        else:
            segs.append({"path": path + [name], "lo": a, "hi": b, "tok": seg_tok})
    # pack consecutive small sibling segments up to target
    packed: list[dict] = []
    for s in segs:
        tok = s.get("tok") or ntok("\n".join(lines[s["lo"]:s["hi"]]))
        last = packed[-1] if packed else None
        if last and last.get("mergeable") and s.get("tok") and last["tok"] + tok <= target and last["hi"] == s["lo"]:
            last["hi"] = s["hi"]
            last["tok"] += tok
            last["keys"].append(s["path"][-1])
            continue
        packed.append({**s, "tok": tok, "mergeable": bool(s.get("tok")), "keys": [s["path"][-1]]})
    for p in packed:
        if len(p["keys"]) > 1:
            shown = ", ".join(p["keys"][:3]) + (", …" if len(p["keys"]) > 3 else "")
            p["path"] = p["path"][:-1] + [shown]
    return packed


@dataclass
class CodePiece:
    text: str
    section_path: list[str]
    start: int  # 1-based, inclusive
    end: int


def chunk_code(text: str, kind: str, *, title: str, lead: str | None = None, target: int = CHUNK_TARGET,
               hard_max: int = CHUNK_HARD_MAX) -> list[CodePiece]:
    """YAML/JSON split at keys, Go at top-level declarations, anything else at line boundaries. Each
    piece is a fenced block with exact 1-based source line numbers."""
    lines = text.split("\n")
    fence_lang = {"yaml": "yaml", "json": "json", "go": "go"}.get(kind, "")
    overhead = ntok(render_header(title, lead, [], [])) + 24  # header, fences, a key path
    t_body, h_body = max(64, target - overhead), max(96, hard_max - overhead)
    if kind in ("yaml", "json", "go"):
        segs = struct_split(lines, kind, 0, len(lines), [], t_body, h_body)
    else:
        segs = line_pack(lines, 0, len(lines), [], h_body)
    out: list[CodePiece] = []

    def emit(path: list[str], lo: int, hi: int) -> None:
        body_lines = lines[lo:hi]
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
            lo += 1
        if not "".join(body_lines).strip():
            return
        hi = lo + len(body_lines)
        path = [p for p in path if p != "(preamble)"]
        fence = "````" if any(ln.lstrip().startswith("```") for ln in body_lines) else "```"
        body = f"{fence}{fence_lang}\n" + "\n".join(body_lines) + f"\n{fence}"
        full = render(render_header(title, lead, [], path), body)
        if ntok(full) > hard_max and hi - lo > 1:
            budget = max(32, hard_max - ntok(render_header(title, lead, [], path)) - 12)
            sub = line_pack(lines, lo, hi, path, budget)
            if len(sub) > 1:
                for s in sub:
                    emit(path, s["lo"], s["hi"])
                return
        if ntok(full) > hard_max:  # one enormous line: fall back to token windows
            room = max(16, hard_max - ntok(render_header(title, lead, [], path)) - 16)
            for w in _windows(body_lines[0], room):
                out.append(CodePiece(render(render_header(title, lead, [], path), f"{fence}{fence_lang}\n{w}\n{fence}"),
                                     path, lo + 1, lo + 1))
            return
        out.append(CodePiece(full, path, lo + 1, hi))

    for s in segs:
        if kind == "go" and s["path"] and s["path"][-1] in ("(preamble)", "import"):
            continue  # package clause, license header and imports carry no answerable content
        emit(s["path"], s["lo"], s["hi"])
    return out


# ----------------------------------------------------------------------------- records and checks
def make_chunk(*, id: str, source_type: str, doc_url: str, url: str, title: str, section_path: list[str],
               text: str, ord: int, product: str | None = None, cite_urls: list[str] | None = None,
               anchor: str | None = None, repo: str | None = None, commit: str | None = None,
               lines: list[int] | None = None, lastmod: str | None = None) -> dict:
    """One chunks.jsonl record with exactly the I1 fields."""
    return {
        "id": id, "source_type": source_type, "tier": TIERS[source_type], "product": product,
        "cite_urls": cite_urls, "doc_url": doc_url, "url": url, "title": title, "section_path": section_path,
        "text": text, "tokens": ntok(text), "ord": ord, "anchor": anchor, "repo": repo, "commit": commit,
        "lines": lines, "lastmod": lastmod, "hash": sha256(text),
    }


def fences_balanced(text: str) -> bool:
    """True when every fenced code block that opens in `text` also closes."""
    fence = None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
        elif is_fence_close(line, fence):
            fence = None
    return fence is None


TAB_LINE = re.compile(r"^\*\*Tab: (.+)\*\*$", re.M)


def tab_labels_in(text: str) -> set[str]:
    return set(TAB_LINE.findall(text))
