"""Source records -> chunks.jsonl records (contract I1), one builder per source_type.

Every builder is a pure function of its source record, so the build and the refresher produce the
same chunks for the same content. `doc_key(chunk)` groups chunks by source document and
`order_key(chunk)` gives one deterministic order for the whole index (row i = line i).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from index.chunk import chunk_code, chunk_markdown, make_chunk
from ingest import config
from ingest.github import blob_url

INDEX_PKG = Path(__file__).resolve().parent
FACTCARD_DIR = INDEX_PKG / "factcards"
ISSUE_DIR = INDEX_PKG / "issues"

PRODUCT_LABEL = {"go": "OLake Go", "fusion": "OLake Fusion"}
SOURCE_RANK = {"docs": 0, "release": 0, "release-gh": 1, "faq": 2, "factcard": 3, "repo": 4, "issue": 5,
               "outside": 6, "blog": 7}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def url_slug(url: str) -> str:
    parts = urlsplit(url)
    return parts.path.strip("/")


# ----------------------------------------------------------------------------- docs + release pages
def docs_chunks(page: dict) -> list[dict]:
    """A docs or release page (ingest.docs record) -> chunks. doc_url = the sitemap URL exactly."""
    url, ids = page["url"], set(page.get("ids") or ())
    out = []
    for n, r in enumerate(chunk_markdown(page["markdown"], title=page["title"],
                                         lead=PRODUCT_LABEL.get(page["product"]), crumbs=page["breadcrumb"])):
        anchor = r.anchor if r.anchor and r.anchor in ids else None
        out.append(make_chunk(id=f"{url_slug(url)}#{n}", source_type=page["source_type"], product=page["product"],
                              doc_url=url, url=f"{url}#{anchor}" if anchor else url, title=page["title"],
                              section_path=r.section_path, text=r.text, ord=n, anchor=anchor,
                              lastmod=page.get("lastmod")))
    return out


# ----------------------------------------------------------------------------- GitHub releases
def release_markdown(rel: dict) -> tuple[str, str]:
    title = f"{rel['repo']} {rel['tag']} release notes"
    if rel.get("name") and rel["name"].strip() not in (rel["tag"], ""):
        title += f": {rel['name'].strip()}"
    date = (rel.get("published_at") or "")[:10]
    pre = " (pre-release)" if rel.get("prerelease") else ""
    latest = f" It is the latest {rel['latest']} on GitHub when this index was built." if rel.get("latest") else ""
    md = f"# {title}\n\nGitHub release {rel['tag']} of {config.GITHUB_ORG}/{rel['repo']}, published {date}{pre}.{latest}" \
         f"\n\n{rel.get('body') or '(no release notes)'}\n"
    return title, md


def mark_latest(repo: str, rels: list[dict]) -> list[dict]:
    """Flag the newest published release (per tag family for olake-helm: worker vX.Y.Z and chart
    olake-X.Y.Z) with a "latest" label; rels are newest first, as the releases API returns them."""
    seen = set()
    out = []
    for r in rels:
        r = {k: v for k, v in r.items() if k != "latest"}
        if not r.get("prerelease"):
            family = "chart" if repo == "olake-helm" and r["tag"].startswith("olake-") else "release"
            if family not in seen:
                seen.add(family)
                what = "Helm chart release" if family == "chart" else (
                    "worker release" if repo == "olake-helm" else "release")
                r["latest"] = f"{config.GITHUB_ORG}/{repo} {what}"
        out.append(r)
    return out


def release_gh_chunks(rel: dict) -> list[dict]:
    title, md = release_markdown(rel)
    lead = f"GitHub release {config.GITHUB_ORG}/{rel['repo']}"
    out = []
    for n, r in enumerate(chunk_markdown(md, title=title, lead=lead)):
        out.append(make_chunk(id=f"release-gh/{rel['repo']}/{rel['tag']}#{n}", source_type="release-gh",
                              product=config.REPO_PRODUCT.get(rel["repo"]), doc_url=rel["url"], url=rel["url"],
                              title=title, section_path=r.section_path, text=r.text, ord=n, repo=rel["repo"],
                              lastmod=rel.get("published_at")))
    return out


# ----------------------------------------------------------------------------- product FAQs
def faq_chunks(rec: dict) -> list[dict]:
    """One FAQ question + answer -> one chunk (split only if it exceeded the hard max)."""
    md = f"### {rec['question']}\n\n{rec['answer']}\n"
    slug = url_slug(rec["page_url"]) or "home"
    out = []
    for k, r in enumerate(chunk_markdown(md, title=rec["label"], lead="olake.io product page")):
        out.append(make_chunk(id=f"faq/{slug}/{rec['n']}#{k}", source_type="faq", doc_url=rec["page_url"],
                              url=rec["page_url"], title=rec["label"], section_path=[rec["question"]],
                              text=r.text, ord=rec["n"]))
    return out


# ----------------------------------------------------------------------------- repo files
def repo_chunks(f: dict) -> list[dict]:
    """An allowlisted repo file (ingest.github.read_repo_files record) -> chunks.
    doc_url = the branch form; url = the full-SHA permalink with #L<a>-L<b> (?plain=1 for Markdown)."""
    repo, path, commit = f["repo"], f["path"], f["commit"]
    title = f"{repo}: {path}"
    lead = f"GitHub repo {config.GITHUB_ORG}/{repo}"
    doc_url = blob_url(repo, f["branch"], path)
    sha_url = blob_url(repo, commit, path)
    out = []
    if f["kind"] in ("markdown", "spec"):
        for n, r in enumerate(chunk_markdown(f["text"], title=title, lead=lead)):
            if f["kind"] == "spec":  # converted field tables no longer match the JSON's line numbers
                url, lines = sha_url, None
            else:
                url, lines = f"{sha_url}?plain=1#L{r.start}-L{r.end}", [r.start, r.end]
            out.append(make_chunk(id=f"{repo}/{path}#{n}", source_type="repo", doc_url=doc_url, url=url,
                                  title=title, section_path=r.section_path, text=r.text, ord=n, repo=repo,
                                  commit=commit, lines=lines, lastmod=f.get("commit_date")))
        return out
    for n, p in enumerate(chunk_code(f["text"], f["kind"], title=title, lead=lead)):
        out.append(make_chunk(id=f"{repo}/{path}#{n}", source_type="repo", doc_url=doc_url,
                              url=f"{sha_url}#L{p.start}-L{p.end}", title=title, section_path=p.section_path,
                              text=p.text, ord=n, repo=repo, commit=commit, lines=[p.start, p.end],
                              lastmod=f.get("commit_date")))
    return out


def retarget_repo_chunk(c: dict, commit: str, commit_date: str | None) -> dict:
    """An unchanged file at a new HEAD: same text and hash, permalink moved to the new SHA."""
    c = dict(c)
    if c.get("commit") and c["commit"] != commit:
        c["url"] = c["url"].replace(f"/blob/{c['commit']}/", f"/blob/{commit}/", 1)
        c["commit"] = commit
    c["lastmod"] = commit_date
    return c


# ----------------------------------------------------------------------------- curated issues
def read_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2).strip() + "\n"


def load_issue_notes(directory: Path = ISSUE_DIR) -> dict[str, dict]:
    """{issue url: {fixed_in, facts}} from index/issues/*.md (key facts written from each thread)."""
    out = {}
    for p in sorted(directory.glob("*.md")):
        meta, body = read_front_matter(p)
        out[meta["url"]] = {"fixed_in": meta.get("fixed_in"), "facts": body, "file": p.name}
    return out


def issue_status(issue: dict, fixed_in: str | None) -> str:
    state = issue.get("state") or "unknown"
    return f"{state}; fixed in {fixed_in}" if fixed_in else state


def issue_chunk(issue: dict, note: dict | None) -> dict:
    """One curated issue -> exactly one chunk: "known issue #N (state; fixed in vX)" + its key facts."""
    repo, number = issue["repo"], issue["number"]
    title = f"{repo} issue #{number}: {issue['title']}"
    lead = f"GitHub issue {config.GITHUB_ORG}/{repo}#{number}"
    status = issue_status(issue, (note or {}).get("fixed_in"))
    if note:
        facts = note["facts"].strip()
    else:  # no curated note: the opening post, trimmed
        facts = re.sub(r"```.*?```", "", issue.get("body") or "", flags=re.S).strip()[:1200]
    md = f"Known issue #{number} in {config.GITHUB_ORG}/{repo} ({status}): {issue['title']}\n\n{facts}\n"
    pieces = chunk_markdown(md, title=title, lead=lead)
    if len(pieces) > 1:
        raise ValueError(f"curated issue {issue['url']} does not fit one chunk; shorten its note")
    text = pieces[0].text
    return make_chunk(id=f"issue/{repo}/{number}#0", source_type="issue", doc_url=issue["url"], url=issue["url"],
                      title=title, section_path=[f"known issue #{number}"], text=text, ord=0, repo=repo,
                      lastmod=issue.get("updated_at"))


# ----------------------------------------------------------------------------- outside pages
def outside_chunks(page: dict) -> list[dict]:
    url, ids = page["url"], set(page.get("ids") or ())
    parts = urlsplit(url)
    slug = (parts.hostname or "") + "/" + parts.path.strip("/")
    out = []
    for n, r in enumerate(chunk_markdown(page["markdown"], title=page["title"], lead=page["label"])):
        anchor = r.anchor if r.anchor and r.anchor in ids else None
        out.append(make_chunk(id=f"outside/{slug.strip('/')}#{n}", source_type="outside", doc_url=url,
                              url=f"{url}#{anchor}" if anchor else url, title=page["title"],
                              section_path=r.section_path, text=r.text, ord=n, anchor=anchor))
    return out


# ----------------------------------------------------------------------------- fact cards
def load_factcards(directory: Path = FACTCARD_DIR) -> list[dict]:
    """index/factcards/*.md -> [{name, title, cite_urls, body, hash}]."""
    cards = []
    for p in sorted(directory.glob("*.md")):
        meta, body = read_front_matter(p)
        cite = meta.get("cite_urls") or []
        if not cite:
            raise ValueError(f"factcard {p.name}: cite_urls is empty")
        cards.append({"name": p.stem, "title": meta.get("title") or p.stem.replace("-", " "), "cite_urls": cite,
                      "body": body, "hash": sha(p.read_text(encoding="utf-8"))})
    return cards


CITE_COMMENT = re.compile(r"^\s*<!--\s*cite:\s*(.*?)\s*-->\s*$")
HEADING_LINE = re.compile(r"^(#{1,6})\s+\S")


def line_cites(body: str, default: list[str]) -> list[list[str] | None]:
    """The citation URLs in effect on each line (index 0 = line 1) of a fact card body.

    A section declares its sources with a `<!-- cite: url url ... -->` line under its heading;
    subsections without their own comment inherit it, and lines outside any declaring section use
    the card's front-matter cite_urls. Heading, blank and comment lines get None (they carry no facts)."""
    stack: list[tuple[int, list[str] | None]] = [(0, None)]
    out: list[list[str] | None] = []
    for line in body.split("\n"):
        h = HEADING_LINE.match(line)
        m = CITE_COMMENT.match(line)
        if h:
            level = len(h.group(1))
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, None))
            out.append(None)
        elif m:
            stack[-1] = (stack[-1][0], m.group(1).split())
            out.append(None)
        elif not line.strip():
            out.append(None)
        else:
            out.append(next((c for _, c in reversed(stack) if c), default))
    return out


def card_cite_urls(card: dict) -> list[str]:
    """Every URL a card cites: its front matter plus each section's cite comment."""
    urls = list(card["cite_urls"])
    for line in card["body"].split("\n"):
        m = CITE_COMMENT.match(line)
        if m:
            urls += [u for u in m.group(1).split() if u not in urls]
    return urls


def factcard_chunks(card: dict) -> list[dict]:
    """Card -> chunks; each chunk's cite_urls are the sources of the sections it holds (doc_url = the first)."""
    per_line = line_cites(card["body"], list(card["cite_urls"]))
    out = []
    for n, r in enumerate(chunk_markdown(card["body"], title=card["title"], lead="OLake fact card", split_level=2)):
        cite: list[str] = []
        for urls in per_line[r.start - 1:r.end]:
            for u in urls or ():
                if u not in cite:
                    cite.append(u)
        cite = cite or list(card["cite_urls"])
        out.append(make_chunk(id=f"factcard/{card['name']}#{n}", source_type="factcard", doc_url=cite[0],
                              url=cite[0], title=card["title"], section_path=r.section_path, text=r.text, ord=n,
                              cite_urls=cite))
    return out


# ----------------------------------------------------------------------------- grouping and order
def doc_key(c: dict) -> str:
    """The source document a chunk came from (one page, file, release, Q&A, issue or card)."""
    if c["source_type"] in ("factcard", "faq"):
        return c["id"].split("#", 1)[0]
    return f"{c['source_type']}:{c['doc_url']}"


def _index_of(seq, item, default: int = 10 ** 6) -> int:
    try:
        return list(seq).index(item)
    except ValueError:
        return default


def order_key(c: dict) -> tuple:
    st = c["source_type"]
    rank = SOURCE_RANK.get(st, 9)
    if st in ("docs", "release"):
        sub = (c["doc_url"],)
    elif st == "release-gh":
        # newest first within a repo; ISO timestamps sort as strings
        neg = "".join(chr(0x10FFFF - ord(ch)) for ch in (c.get("lastmod") or ""))
        sub = (_index_of(config.REPOS, c.get("repo")), neg, c["doc_url"])
    elif st == "faq":
        sub = (_index_of([u for u, _ in config.FAQ_PAGES], c["doc_url"]), c["id"].split("#", 1)[0])
    elif st == "factcard":
        sub = (c["id"].split("#", 1)[0],)
    elif st == "repo":
        sub = (_index_of(config.REPOS, c.get("repo")), c["title"])
    elif st == "issue":
        sub = (_index_of(config.CURATED_ISSUES, c["doc_url"]),)
    elif st == "outside":
        sub = (_index_of([u for u, _ in config.OUTSIDE_PAGES], c["doc_url"]),)
    else:
        sub = (c["doc_url"],)
    return (rank, *sub, c["ord"])


def sort_chunks(chunks: list[dict]) -> list[dict]:
    return sorted(chunks, key=order_key)
