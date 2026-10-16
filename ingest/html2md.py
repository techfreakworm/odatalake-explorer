"""HTML -> Markdown that keeps what retrieval and citation need (ported from poc/ingest/html2md.py).

* headings keep their anchor id:      ``## Prerequisites {#prerequisites}`` (the zero-width-space
  hash link inside Docusaurus headings is dropped)
* fenced code keeps its language and title: ```` ```json title="destination.json" ````
  (lines from ``.token-line``; the title from the ``olake-code`` wrapper or ``codeBlockTitle``)
* tables become GitHub pipe tables; admonitions become ``> **Note:** ...`` quotes;
  ``<details>`` become a bold summary line followed by the body
* every tab panel is kept (the static HTML ships hidden panels too), each prefixed with
  ``**Tab: <label>**``; each tab group is wrapped in invisible ``<!-- tabs:start -->`` /
  ``<!-- tabs:end -->`` markers so the chunker can resolve nested groups. Only the panels whose
  nearest ``.tabs-container`` is the current group are taken, so nested panels are emitted once.

Always parse with lxml: the minified olake.io HTML omits </li> and </p>, and html.parser
mis-nests it (and concatenates tab labels). Images, SVGs, buttons and navigation are dropped.
"""

from __future__ import annotations

import copy
import re

from bs4 import BeautifulSoup, NavigableString, Tag

ZW = "​"
TABS_START = "<!-- tabs:start -->"
TABS_END = "<!-- tabs:end -->"
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "header", "footer", "aside",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "pre", "table",
    "blockquote", "details", "summary", "figure", "hr", "dl", "dt", "dd", "nav",
}
DROP_TAGS = {"script", "style", "noscript", "svg", "img", "button", "iframe", "video", "picture", "source",
             "input", "select", "textarea", "form", "template", "canvas", "audio", "object", "embed"}
PERMALINK_TEXT = {"", "#", "¶", "§", "🔗", "​"}


def _clean(text: str) -> str:
    return text.replace(ZW, "").replace("\xa0", " ").replace("﻿", "")


def _classes(el: Tag) -> str:
    return " ".join(el.get("class") or [])


def is_permalink(a: Tag) -> bool:
    """Heading self-links: Docusaurus .hash-link (a zero-width space), Sphinx/MkDocs .headerlink (¶)."""
    cls = _classes(a)
    if "hash-link" in cls or "headerlink" in cls or "anchorjs-link" in cls:
        return True
    href = a.get("href") or ""
    return href.startswith("#") and _clean(a.get_text()).strip() in PERMALINK_TEXT


def code_language(node: Tag) -> str:
    """Docusaurus puts ``language-xxx`` on the container div and on <pre>."""
    for el in [node, *node.parents]:
        if not isinstance(el, Tag):
            continue
        for c in el.get("class") or []:
            if c.startswith("language-"):
                return c[len("language-"):]
            if c.startswith("lang-"):
                return c[len("lang-"):]
        if "codeBlockContainer" in _classes(el) or (el.name == "div" and any(
                c.startswith("theme-code-block") for c in el.get("class") or [])):
            break
    code = node.find("code") if isinstance(node, Tag) else None
    if isinstance(code, Tag):
        for c in code.get("class") or []:
            if c.startswith("language-"):
                return c[len("language-"):]
    return ""


def code_text(pre: Tag) -> str:
    lines = pre.select(".token-line")
    if lines:
        return "\n".join(_clean(line.get_text()) for line in lines).rstrip("\n")
    for br in pre.find_all("br"):
        br.replace_with("\n")
    return _clean(pre.get_text()).rstrip("\n")


def code_title(container: Tag | None) -> str:
    if container is None:
        return ""
    t = container.select_one(".olake-code__title, [class*=codeBlockTitle]")
    return _clean(t.get_text(strip=True)) if t else ""


class Converter:
    def __init__(self) -> None:
        self.stats = {"code_blocks": 0, "tables": 0, "tabs": 0, "admonitions": 0, "details": 0, "headings": 0}

    # ---------- inline ----------
    def inline(self, node) -> str:
        if isinstance(node, NavigableString):
            if type(node).__name__ in ("Comment", "Doctype", "Declaration", "ProcessingInstruction", "CData"):
                return ""
            return re.sub(r"\s+", " ", _clean(str(node)))
        if not isinstance(node, Tag) or node.name in DROP_TAGS:
            return ""
        name = node.name
        if name == "br":
            return "\n"
        if name == "a" and is_permalink(node):
            return ""
        inner = "".join(self.inline(c) for c in node.children)
        if name == "code":
            txt = _clean(node.get_text())
            return f"`{txt}`" if txt.strip() else ""
        if name in ("strong", "b"):
            return f"**{inner.strip()}**" if inner.strip() else ""
        if name in ("em", "i"):
            return f"_{inner.strip()}_" if inner.strip() else ""
        return inner

    # ---------- blocks ----------
    def blocks(self, node: Tag) -> list[str]:
        out: list[str] = []
        buf: list[str] = []

        def flush():
            text = "".join(buf).strip()
            text = re.sub(r"[ \t]+\n", "\n", text)
            text = re.sub(r"\n[ \t]+", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            if text:
                out.append(text)
            buf.clear()

        for child in node.children:
            if isinstance(child, NavigableString):
                buf.append(self.inline(child))
                continue
            if not isinstance(child, Tag) or child.name in DROP_TAGS:
                continue
            if child.name in BLOCK_TAGS or self._is_special(child):
                flush()
                out.extend(self.block(child))
            else:
                buf.append(self.inline(child))
        flush()
        return out

    def _is_special(self, el: Tag) -> bool:
        cls = _classes(el)
        return "tabs-container" in cls or "theme-admonition" in cls

    def block(self, el: Tag) -> list[str]:
        name = el.name
        cls = _classes(el)
        if re.fullmatch(r"h[1-6]", name):
            self.stats["headings"] += 1
            level = int(name[1])
            text = re.sub(r"\s+", " ", "".join(self.inline(c) for c in el.children)).strip()
            if not text:
                return []
            anchor = el.get("id")
            return [f"{'#' * level} {text}" + (f" {{#{anchor}}}" if anchor else "")]
        if name == "pre":
            return [self.code_block(el)]
        if name == "div" and ("codeBlockContainer" in cls or "theme-code-block" in cls):
            pre = el.find("pre")
            return [self.code_block(pre, container=el)] if pre else []
        if name == "table":
            t = self.table(el)
            return [t] if t else []
        if name in ("ul", "ol"):
            t = self.list_block(el)
            return [t] if t else []
        if name == "blockquote":
            inner = self.blocks(el)
            if not inner:
                return []
            return ["\n".join("> " + line if line else ">" for line in "\n\n".join(inner).split("\n"))]
        if "tabs-container" in cls:
            return self.tabs(el)
        if "theme-admonition" in cls:
            return self.admonition(el)
        if name == "details":
            self.stats["details"] += 1
            summary = el.find("summary")
            title = _clean(summary.get_text(" ", strip=True)) if summary else "Details"
            if summary:
                summary.extract()
            return [f"**{title}**", *self.blocks(el)]
        if name == "dt":
            text = re.sub(r"\s+", " ", "".join(self.inline(c) for c in el.children)).strip()
            return [f"**{text.strip('*')}**"] if text else []
        if name in ("hr", "nav"):
            return []
        return self.blocks(el)

    def code_block(self, pre: Tag, container: Tag | None = None) -> str:
        self.stats["code_blocks"] += 1
        if container is None:
            container = pre.find_parent(class_=re.compile(r"codeBlockContainer|theme-code-block"))
        lang = code_language(pre)
        title = code_title(container)
        info = lang + (f' title="{title}"' if title else "")
        body = code_text(pre)
        fence = "````" if "```" in body else "```"
        return f"{fence}{info}\n{body}\n{fence}"

    def table(self, table: Tag) -> str:
        self.stats["tables"] += 1
        rows = []
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:  # rows of a nested table stay in their cell
                continue
            cells = []
            for cell in tr.find_all(["th", "td"], recursive=False):
                parts = self.blocks(cell)
                txt = "<br>".join(p.replace("\n", "<br>") for p in parts)
                cells.append(txt.replace("|", "\\|").strip())
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def list_block(self, lst: Tag) -> str:
        ordered = lst.name == "ol"
        start = int(lst.get("start", 1)) if ordered and str(lst.get("start", "1")).isdigit() else 1
        lines = []
        for i, li in enumerate(lst.find_all("li", recursive=False)):
            marker = f"{start + i}." if ordered else "-"
            parts = self.blocks(li)
            if not parts:
                continue
            pad = " " * (len(marker) + 1)
            first, *rest = parts
            item = marker + " " + first.replace("\n", "\n" + pad)
            for p in rest:
                item += "\n\n" + "\n".join(pad + line if line else "" for line in p.split("\n"))
            lines.append(item)
        return "\n".join(lines)

    def tabs(self, el: Tag) -> list[str]:
        self.stats["tabs"] += 1

        def own(node: Tag) -> bool:  # skip tabs/panels that belong to a nested tabs-container
            return node.find_parent(class_="tabs-container") is el

        labels = [_clean(li.get_text(" ", strip=True)) for li in el.select('[role="tab"]') if own(li)]
        panels = [p for p in el.select('[role="tabpanel"]') if own(p)]
        out = [TABS_START]
        for i, panel in enumerate(panels):
            label = labels[i] if i < len(labels) and labels[i] else f"Tab {i + 1}"
            out.append(f"**Tab: {label}**")
            out.extend(self.blocks(panel))
        out.append(TABS_END)
        return out

    def admonition(self, el: Tag) -> list[str]:
        self.stats["admonitions"] += 1
        kind = "Note"
        for c in el.get("class") or []:
            m = re.match(r"theme-admonition-(\w+)", c)
            if m:
                kind = m.group(1).capitalize()
        heading = el.select_one('[class*="admonitionHeading"]')
        content = el.select_one('[class*="admonitionContent"]')
        title = _clean(heading.get_text(" ", strip=True)) if heading else ""
        if title and title.lower() != kind.lower():
            kind = f"{kind}: {title}"
        body = self.blocks(content if content else el)
        text = "\n\n".join(body)
        lines = [f"**{kind}:**", *text.split("\n")]
        return ["\n".join("> " + ln if ln else ">" for ln in lines)]


def page_ids(soup: BeautifulSoup) -> set[str]:
    return {str(t.get("id")) for t in soup.find_all(id=True)}


def extract_page(html: str, url: str) -> dict:
    """Metadata + Markdown for one Docusaurus docs page.

    breadcrumb: the docs breadcrumb trail without the home icon and without the active item (the
    page itself). ids: every element id on the page, so a chunk keeps an anchor only if it exists.
    """
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    title = _clean(re.sub(r"\s*\|\s*OLake\s*$", "", title)).strip()
    canonical = soup.find("link", rel="canonical")
    canonical = canonical.get("href") if canonical else url
    desc = soup.find("meta", attrs={"name": "description"})
    crumbs = []
    for li in soup.select("nav.theme-doc-breadcrumbs li, nav[aria-label=Breadcrumbs] li"):
        if "breadcrumbs__item--active" in _classes(li):
            continue
        txt = _clean(li.get_text(" ", strip=True))
        if txt:
            crumbs.append(txt)
    last_updated = soup.select_one(".theme-last-updated time, .olake-docsinfo__updated time, article time[datetime]")
    root = (
        soup.select_one(".theme-doc-markdown")
        or soup.select_one('article [itemprop="articleBody"]')
        or soup.select_one("article .markdown")
        or soup.find("article")
    )
    ids = page_ids(soup)
    conv = Converter()
    md = "\n\n".join(b for b in conv.blocks(root) if b.strip()) if root else ""
    h1 = soup.select_one(".theme-doc-markdown h1, article h1")
    return {
        "url": url,
        "canonical": canonical,
        "title": title or (_clean(h1.get_text(" ", strip=True)) if h1 else ""),
        "h1": _clean(h1.get_text(" ", strip=True)) if h1 else "",
        "description": desc.get("content", "") if desc else "",
        "breadcrumb": crumbs,
        "last_updated": last_updated.get("datetime") if last_updated else None,
        "markdown": md,
        "ids": ids,
        "extract_stats": conv.stats,
    }


# ----------------------------------------------------------------------------- outside pages
MAIN_SELECTORS = (
    ".theme-doc-markdown",                 # Docusaurus (Databricks, Temporal)
    "article.md-content__inner",           # MkDocs Material (Iceberg, Lakekeeper, Nessie)
    ".md-content",
    "#docContent",                         # postgresql.org
    "#docs-body", ".docs-body",            # dev.mysql.com
    ".td-content",                         # Hugo Docsy (Kafka, Polaris)
    "#main-col-body",                      # AWS docs
    ".devsite-article-body",               # Google Cloud
    "main article", "article", "main", "[role=main]", "#content", ".content", "body",
)
NOISE_SELECTORS = (
    "nav", "header", "footer", "aside", "form", ".toc", "#toc", ".table-of-contents", ".breadcrumbs",
    ".breadcrumb", ".md-sidebar", ".md-footer", ".md-header", ".feedback", "[role=navigation]",
    ".pagination-nav", ".theme-doc-footer", ".edit-this-page", ".td-sidebar", ".td-toc",
    "[aria-hidden=true]", ".visually-hidden", ".sr-only",
)


def extract_main(html: str, url: str, min_chars: int = 400) -> dict:
    """Main-content extraction for a curated outside page: the first selector whose cleaned-up
    Markdown has real text (landing pages often keep their content outside <main>)."""
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.title.get_text(" ", strip=True)) if soup.title else url
    title = re.sub(r"\s+", " ", title).strip()[:160]
    ids = page_ids(soup)
    best = {"url": url, "title": title, "markdown": "", "ids": ids, "selector": None}
    tried = set()
    for selector in MAIN_SELECTORS:
        cand = soup.select_one(selector)
        if cand is None or id(cand) in tried or len(cand.get_text(" ", strip=True)) < min_chars:
            continue
        tried.add(id(cand))
        root = copy.copy(cand)  # clean a copy, so a rejected candidate leaves the page intact
        for noise in NOISE_SELECTORS:
            for el in root.select(noise):
                el.decompose()
        conv = Converter()
        md = "\n\n".join(b for b in conv.blocks(root) if b.strip())
        if len(md) >= min_chars:
            return {"url": url, "title": title, "markdown": md, "ids": ids, "selector": selector,
                    "extract_stats": conv.stats}
        if len(md) > len(best["markdown"]):
            best = {"url": url, "title": title, "markdown": md, "ids": ids, "selector": selector,
                    "extract_stats": conv.stats}
    return best
