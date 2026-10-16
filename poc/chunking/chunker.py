"""Structure-aware chunker with citation metadata.

    uv run python -I -m chunking.chunker --target 300 --target 600 [--blog]

Markdown (docs pages, repo *.md):
  * blocks = paragraphs/lists, fenced code, tables, headings; fenced code and
    tables are atomic. A block larger than the hard max is the only thing ever
    split: code at line boundaries (fences re-opened), tables at row boundaries
    (header row repeated), so every chunk still holds valid Markdown.
  * a heading or a "**Tab: X**" marker starts a section; small consecutive
    sections are packed together up to the target size.
  * every chunk starts with a context header "page title › section path".
YAML / JSON: split at the shallowest key level (comments attached to the key
below them), recursing one level deeper for keys that are still too big.
Go: split at top-level declarations (doc comments attached).

Citation URL per chunk:
  docs  -> https://olake.io/docs/<page>/#<anchor of the chunk's section>
  repo  -> https://github.com/datazip-inc/<repo>/blob/<sha>/<path>#L<a>-L<b>
           (Markdown files get ?plain=1 so GitHub honours line anchors)

Output: $ASK_OLAKE_CACHE/index/chunks-<target>.jsonl and results/chunks.json
"""

from __future__ import annotations

import argparse
import re
import statistics
from dataclasses import dataclass, field

import tiktoken

from common.config import CORPUS_DIR, INDEX_DIR, RESULTS_DIR, read_jsonl, write_json, write_jsonl

ENC = tiktoken.get_encoding("o200k_base")
SEP = " › "


def ntok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


# ----------------------------------------------------------------------------- markdown
HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+\{#([^}]+)\})?\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
TAB = re.compile(r"^\*\*Tab: (.+)\*\*$")


@dataclass
class Block:
    kind: str  # heading | code | table | text | tab
    text: str
    start: int  # 1-based line numbers in the source
    end: int
    level: float = 0
    title: str = ""
    anchor: str | None = None
    tokens: int = 0


def parse_markdown(md: str) -> list[Block]:
    lines = md.split("\n")
    n, i, out = len(lines), 0, []
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("<!--"):  # HTML comments (license headers) are dropped
            j = i
            while j < n and "-->" not in lines[j]:
                j += 1
            i = j + 1
            continue
        m = FENCE.match(line)
        if m:
            fence = m.group(1)
            j = i + 1
            while j < n and not (lines[j].strip().startswith(fence) and lines[j].strip().strip(fence[0]) == ""):
                j += 1
            out.append(Block("code", "\n".join(lines[i:j + 1]), i + 1, min(j + 1, n)))
            i = j + 1
            continue
        h = HEADING.match(line)
        if h:
            out.append(Block("heading", line, i + 1, i + 1, level=len(h.group(1)), title=h.group(2).strip(),
                             anchor=h.group(3)))
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
                and not HEADING.match(lines[j + 1]) and not lines[j + 1].lstrip().startswith("|"):
            j += 1
        text = "\n".join(lines[i:j + 1])
        t = TAB.match(text.strip())
        if t:
            out.append(Block("tab", text, i + 1, j + 1, title="Tab: " + t.group(1)))
        else:
            out.append(Block("text", text, i + 1, j + 1))
        i = j + 1
    for b in out:
        b.tokens = ntok(b.text)
    return out


def split_oversize(b: Block, hard_max: int) -> list[Block]:
    """Split one block that alone exceeds hard_max, keeping each piece valid."""
    lines = b.text.split("\n")
    if b.kind == "code":
        head, body, tail = lines[0], lines[1:-1], lines[-1]
        wrap = lambda ls: "\n".join([head, *ls, tail])  # noqa: E731
    elif b.kind == "table":
        head, body = lines[:2], lines[2:]
        wrap = lambda ls: "\n".join([*head, *ls])  # noqa: E731
    else:
        body = lines
        wrap = lambda ls: "\n".join(ls)  # noqa: E731
    pieces, cur, cur_start = [], [], 0
    base = ntok(wrap([]))
    budget = hard_max - base
    acc = 0
    for k, ln in enumerate(body):
        t = ntok(ln) + 1
        if cur and acc + t > budget:
            pieces.append((cur_start, cur))
            cur, acc, cur_start = [], 0, k
        cur.append(ln)
        acc += t
    if cur:
        pieces.append((cur_start, cur))
    offset = 1 if b.kind == "code" else (2 if b.kind == "table" else 0)
    out = []
    for start, ls in pieces:
        txt = wrap(ls)
        s = b.start + offset + start
        out.append(Block(b.kind, txt, s, s + len(ls) - 1, tokens=ntok(txt)))
    return out


@dataclass
class Section:
    path: list[str]          # heading titles from the page root to this section
    anchor: str | None       # nearest heading anchor (docs pages)
    blocks: list[Block] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(b.tokens for b in self.blocks) + 2 * max(0, len(self.blocks) - 1)


def sections_of(blocks: list[Block]) -> list[Section]:
    stack: list[tuple[float, str, str | None]] = []  # (level, title, anchor)
    secs = [Section([], None)]
    for b in blocks:
        if b.kind in ("heading", "tab"):
            if b.kind == "tab":
                # a tab label sits just below the heading it appears under
                while stack and stack[-1][1].startswith("Tab: "):
                    stack.pop()
                level = (stack[-1][0] if stack else 0) + 0.5
                anchor = stack[-1][2] if stack else None
            else:
                level, anchor = b.level, b.anchor
            while stack and stack[-1][0] >= level:
                stack.pop()
            if anchor is None and stack:
                anchor = next((a for _, _, a in reversed(stack) if a), None)
            stack.append((level, b.title, anchor))
            secs.append(Section([t for _, t, _ in stack], anchor, [b]))
        else:
            secs[-1].blocks.append(b)
    return [s for s in secs if s.blocks]


def pack_markdown(blocks: list[Block], target: int, hard_max: int, title: str = "") -> list[dict]:
    """Return raw pieces: {path, anchor, blocks} sized <= target (header included) where possible."""
    out: list[dict] = []
    cur: dict | None = None
    head_tok = lambda path: ntok(SEP.join([title, *path])) + 2  # noqa: E731

    def flush():
        nonlocal cur
        if cur and cur["blocks"]:
            out.append(cur)
        cur = None

    for sec in sections_of(blocks):
        parent_path = sec.path[:-1] if sec.blocks[0].kind in ("heading", "tab") else sec.path
        limit = target - head_tok(sec.path)
        if cur and cur["tokens"] + sec.tokens + 2 <= limit:
            cur["blocks"] += sec.blocks
            cur["tokens"] += sec.tokens + 2
            cur["anchors"].append(sec.anchor)
            # header path = common prefix of the packed sections
            common = []
            for a, b in zip(cur["path"], parent_path):
                if a != b:
                    break
                common.append(a)
            cur["path"] = common
            continue
        flush()
        cur = {"path": parent_path, "anchor": sec.anchor, "anchors": [sec.anchor], "blocks": [], "tokens": 0}
        body_max = hard_max - head_tok(sec.path)
        for b in sec.blocks:
            parts = split_oversize(b, body_max) if b.tokens > body_max else [b]
            for p in parts:
                if cur["blocks"] and cur["tokens"] + p.tokens + 2 > limit:
                    flush()
                    cur = {"path": sec.path, "anchor": sec.anchor, "anchors": [sec.anchor], "blocks": [],
                           "tokens": 0, "continued": True}
                cur["blocks"].append(p)
                cur["tokens"] += p.tokens + 2
    flush()
    # fold tiny pieces (< target/5) into a neighbour when the result stays under the hard max
    merged: list[dict] = []
    for p in out:
        prev = merged[-1] if merged else None
        if prev and (prev["tokens"] < target / 5 or p["tokens"] < target / 5) \
                and prev["tokens"] + p["tokens"] + 2 <= hard_max - head_tok(prev["path"]):
            prev["blocks"] += p["blocks"]
            prev["tokens"] += p["tokens"] + 2
            prev["anchors"] += p["anchors"]
            common = []
            for a, b in zip(prev["path"], p["path"]):
                if a != b:
                    break
                common.append(a)
            prev["path"] = common
            continue
        merged.append(p)
    return merged


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
    """Move a boundary up over the comment/blank lines that document the key."""
    prefix = "#" if kind == "yaml" else "//"
    while k - 1 >= lo and (lines[k - 1].strip().startswith(prefix) or (kind == "go" and not lines[k - 1].strip()
                                                                       and k - 2 >= lo and lines[k - 2].strip().startswith(prefix))):
        k -= 1
    return k


def struct_split(lines: list[str], kind: str, lo: int, hi: int, path: list[str], target: int, hard_max: int,
                 depth: int = 0) -> list[dict]:
    text = "\n".join(lines[lo:hi])
    if ntok(text) <= target or depth > 3:
        return [{"path": path, "lo": lo, "hi": hi}] if text.strip() else []
    keys = key_lines(lines, kind, lo, hi)
    if kind != "go":
        if not keys:
            return line_pack(lines, lo, hi, path, hard_max)
        min_indent = min(ind for _, ind, _ in keys)
        keys = [(k, ind, name) for k, ind, name in keys if ind == min_indent]
        # the parent key line itself (first line of a nested range) is not a split point
        keys = [x for x in keys if x[0] != lo or depth == 0]
    if len(keys) < 2:
        if kind != "go" and keys and depth < 3:
            # single big key: descend into its body; the key line (and its comments)
            # is folded into the first sub-chunk so line ranges stay contiguous
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


def line_pack(lines: list[str], lo: int, hi: int, path: list[str], hard_max: int) -> list[dict]:
    out, a, acc = [], lo, 0
    for k in range(lo, hi):
        t = ntok(lines[k]) + 1
        if acc and acc + t > hard_max:
            out.append({"path": path, "lo": a, "hi": k})
            a, acc = k, 0
        acc += t
    if a < hi:
        out.append({"path": path, "lo": a, "hi": hi})
    return out


# ----------------------------------------------------------------------------- driver
def make_chunk(cid: str, source_type: str, doc_url: str, url: str, title: str, path: list[str], body: str,
               **extra) -> dict:
    header = SEP.join([title, *[p for p in path if p]])
    text = f"{header}\n\n{body}"
    return {"id": cid, "source_type": source_type, "doc_url": doc_url, "url": url, "title": title,
            "section_path": path, "text": text, "tokens": ntok(text), **extra}


def chunk_page(page: dict, source_type: str, target: int, hard_max: int) -> list[dict]:
    blocks = parse_markdown(page["markdown"])
    pieces = pack_markdown(blocks, target, hard_max, page["title"])
    url = page["url"]
    slug = url.split("olake.io/", 1)[1].strip("/")
    out = []
    for n, p in enumerate(pieces):
        body = "\n\n".join(b.text for b in p["blocks"])
        anchor = p["anchor"]
        out.append(make_chunk(f"{slug}#{n}", source_type, url, url + (f"#{anchor}" if anchor else ""),
                              page["title"], p["path"], body, anchor=anchor,
                              continued=p.get("continued", False)))
    return out


def chunk_repo_file(f: dict, target: int, hard_max: int) -> list[dict]:
    base = f["url"]  # blob URL pinned to the commit SHA
    plain = "?plain=1" if f["kind"] == "markdown" else ""
    title = f"{f['repo']}: {f['path']}"
    lines = f["text"].split("\n")
    out = []
    if f["kind"] == "markdown":
        blocks = parse_markdown(f["text"])
        for n, p in enumerate(pack_markdown(blocks, target, hard_max, title)):
            a, b = p["blocks"][0].start, p["blocks"][-1].end
            body = "\n\n".join(bl.text for bl in p["blocks"])
            out.append(make_chunk(f"{f['repo']}/{f['path']}#{n}", "repo", base, f"{base}{plain}#L{a}-L{b}",
                                  title, p["path"], body, lines=[a, b], repo=f["repo"], kind=f["kind"]))
        return out
    kind = f["kind"] if f["kind"] in ("yaml", "json", "go") else "text"
    if kind == "text":
        segs = line_pack(lines, 0, len(lines), [], hard_max)
    else:
        segs = struct_split(lines, kind, 0, len(lines), [], target, hard_max)
    for n, s in enumerate(segs):
        if kind == "go" and s["path"] and s["path"][-1] in ("(preamble)", "import"):
            continue  # package clause, license header and imports carry no answerable content
        body_lines = lines[s["lo"]:s["hi"]]
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        if not "".join(body_lines).strip():
            continue
        a, b = s["lo"] + 1, s["lo"] + len(body_lines)
        fence = {"yaml": "yaml", "json": "json", "go": "go"}.get(kind, "")
        body = f"```{fence}\n" + "\n".join(body_lines) + "\n```"
        out.append(make_chunk(f"{f['repo']}/{f['path']}#{n}", "repo", base, f"{base}#L{a}-L{b}", title,
                              [p for p in s["path"] if p != "(preamble)"], body, lines=[a, b], repo=f["repo"],
                              kind=f["kind"]))
    return out


def build(target: int, hard_max: int, include_blog: bool) -> list[dict]:
    chunks = []
    for page in read_jsonl(CORPUS_DIR / "docs.jsonl"):
        chunks += chunk_page(page, "docs", target, hard_max)
    for f in read_jsonl(CORPUS_DIR / "repos.jsonl"):
        chunks += chunk_repo_file(f, target, hard_max)
    if include_blog and (CORPUS_DIR / "blog.jsonl").exists():
        for page in read_jsonl(CORPUS_DIR / "blog.jsonl"):
            chunks += chunk_page(page, "blog", target, hard_max)
    return chunks


def describe(chunks: list[dict], target: int, hard_max: int) -> dict:
    def dist(xs):
        xs = sorted(xs)
        if not xs:
            return {}
        q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
        return {"n": len(xs), "mean": round(statistics.mean(xs), 1), "p5": q(0.05), "p50": q(0.5), "p95": q(0.95),
                "max": xs[-1], "sum": sum(xs)}

    by_type = {}
    for t in sorted({c["source_type"] for c in chunks}):
        sub = [c for c in chunks if c["source_type"] == t]
        by_type[t] = dist([c["tokens"] for c in sub])
    return {
        "target": target,
        "hard_max": hard_max,
        "chunks": len(chunks),
        "tokens": dist([c["tokens"] for c in chunks]),
        "by_source_type": by_type,
        "over_target": sum(c["tokens"] > target for c in chunks),
        "over_hard_max": sum(c["tokens"] > hard_max for c in chunks),
        "under_50_tokens": sum(c["tokens"] < 50 for c in chunks),
        "continued_section_pieces": sum(bool(c.get("continued")) for c in chunks),
        "unbalanced_fences": sum(c["text"].count("```") % 2 for c in chunks),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, action="append", help="target chunk size in o200k tokens (repeatable)")
    ap.add_argument("--max-ratio", type=float, default=1.5, help="hard max = target * ratio")
    ap.add_argument("--blog", action="store_true")
    args = ap.parse_args()
    targets = args.target or [300, 600]
    report = {"tokenizer": "tiktoken o200k_base", "header_format": "title › section › subsection", "configs": []}
    for t in targets:
        hard = int(t * args.max_ratio)
        chunks = build(t, hard, args.blog)
        suffix = f"{t}" + ("-blog" if args.blog else "")
        write_jsonl(INDEX_DIR / f"chunks-{suffix}.jsonl", chunks)
        d = describe(chunks, t, hard)
        d["include_blog"] = args.blog
        report["configs"].append(d)
        print(d)
    out = RESULTS_DIR / ("chunks-blog.json" if args.blog else "chunks.json")
    write_json(out, report)


if __name__ == "__main__":
    main()
