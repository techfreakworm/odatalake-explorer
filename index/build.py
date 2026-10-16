"""Build the index artifact (contract I1).

    uv run python -m index.build [--offline] [--no-outside] [--prune]

Sources (plan Appendix A "Corpus"): docs and release pages from the sitemap minus the denylist,
the last ~10 GitHub releases per repo, the two product FAQs, fact cards (index/factcards/*.md plus
the generated latest-versions card), the repo Tier A allowlist at HEAD, the 10 curated issues and
(unless --no-outside) the curated outside pages. Writes data/index/<UTC version>/ and swaps
data/index/CURRENT atomically. --offline re-extracts from the cached HTML, clones and API
responses; --prune keeps only CURRENT and the version before it.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from index import logs, sources
from index.chunk import FIELDS, fences_balanced, ntok, sha256, tab_labels_in
from index.config import CHUNK_HARD_MAX, EMBED_MODEL, INDEX_DIR
from index.embed import embed_chunks, vectors_from_index
from index.factcheck import check_cards, page_texts
from index.lock import Busy, index_lock, save_state
from index.manifest import (make_manifest, new_version, prune, read_current, swap_current, utc_now,
                            write_version)
from ingest import config
from ingest.docs import SitemapResult, fetch_docs, fetch_sitemap
from ingest.faq import fetch_faqs
from ingest.github import GitHubError, clone_repo, fetch_issue, fetch_releases, read_repo_files
from ingest.outside import fetch_outside
from ingest.sitemap import DocEntry, docs_urls, parse_sitemap, select_docs

log = logging.getLogger("index.build")


# ----------------------------------------------------------------------------- corpus
@dataclass
class Corpus:
    sitemap: SitemapResult | None = None
    sitemap_docs: list[str] = field(default_factory=list)       # every /docs/ URL in the sitemap
    entries: list[DocEntry] = field(default_factory=list)       # after the denylist
    denylist_skipped: list[str] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    page_errors: list[dict] = field(default_factory=list)
    releases: dict[str, list[dict]] = field(default_factory=dict)
    faqs: list[dict] = field(default_factory=list)
    faq_errors: list[dict] = field(default_factory=list)
    repos: dict[str, dict] = field(default_factory=dict)
    repo_files: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    issue_notes: dict[str, dict] = field(default_factory=dict)
    outside_enabled: bool = True
    outside: list[dict] = field(default_factory=list)
    outside_skipped: list[dict] = field(default_factory=list)
    factcards: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def collect_docs(c: Corpus, offline: bool) -> None:
    c.sitemap = fetch_sitemap(offline=offline)
    if c.sitemap.status != 200:
        raise RuntimeError(f"sitemap fetch failed: {c.sitemap.error or c.sitemap.status}")
    entries = parse_sitemap(c.sitemap.text)
    c.sitemap_docs = docs_urls(entries)
    c.entries, c.denylist_skipped = select_docs(entries)
    for u in c.denylist_skipped:
        log.info("denylist: skipped %s", u)
    c.pages, c.page_errors = fetch_docs(c.entries, offline=offline)


def collect_releases(c: Corpus, offline: bool) -> None:
    for repo in config.REPOS:
        try:
            c.releases[repo] = sources.mark_latest(repo, fetch_releases(repo, offline=offline))
        except GitHubError as e:
            c.errors.append(f"releases {repo}: {e}")
            log.warning("releases for %s unavailable: %s", repo, e)
            c.releases[repo] = []


def collect_repos(c: Corpus, offline: bool) -> None:
    for repo in config.REPOS:
        try:
            info = clone_repo(repo, offline=offline)
        except Exception as e:  # noqa: BLE001  (git or network failure: report, keep building)
            c.errors.append(f"repo {repo}: {e}")
            log.warning("repo %s unavailable: %s", repo, e)
            continue
        c.repos[repo] = {k: info[k] for k in ("branch", "commit", "commit_date")}
        c.repo_files += read_repo_files(info)


def collect_issues(c: Corpus, offline: bool) -> None:
    c.issue_notes = sources.load_issue_notes()
    for url in config.CURATED_ISSUES:
        try:
            c.issues.append(fetch_issue(url, offline=offline))
        except GitHubError as e:
            c.errors.append(f"issue {url}: {e}")
            log.warning("issue %s unavailable: %s", url, e)
        if url not in c.issue_notes:
            log.warning("issue %s has no curated note in index/issues/; using its opening post", url)


def latest_versions_card(releases: dict[str, list[dict]], page_urls: list[str]) -> dict | None:
    """Generated from the releases API (plan Appendix A "Fact cards": latest versions). The text holds
    no build date, so it only changes when a release or a release-notes page does."""
    lines, cite = [], []
    names = {"olake": "OLake Go (ingestion engine and connectors)", "olake-ui": "OLake UI",
             "olake-helm": "OLake Helm chart and worker", "olake-fusion": "OLake Fusion (Iceberg table maintenance)"}
    for repo in config.REPOS:
        rels = [r for r in releases.get(repo, []) if not r.get("prerelease")]
        if not rels:
            continue
        top = rels[0]
        line = f"- {names[repo]}, GitHub repo {config.GITHUB_ORG}/{repo}: latest release {top['tag']}, " \
               f"published {(top.get('published_at') or '')[:10]}."
        if repo == "olake-helm":  # chart tags (olake-x.y.z) and worker tags (vX.Y.Z) are released separately
            chart = next((r for r in rels if r["tag"].startswith("olake-")), None)
            worker = next((r for r in rels if r["tag"].startswith("v")), None)
            parts = []
            if worker:
                parts.append(f"worker {worker['tag']} ({(worker.get('published_at') or '')[:10]})")
            if chart:
                parts.append(f"Helm chart {chart['tag']} ({(chart.get('published_at') or '')[:10]})")
            line = f"- {names[repo]}, GitHub repo {config.GITHUB_ORG}/{repo}: latest releases " + " and ".join(parts) + "."
        lines.append(line)
        cite.append(top["url"])
    if not cite:
        return None
    docs_rel = {}
    for url in page_urls:
        m = re.search(r"/release/(ingestion|maintenance)/v(\d+)\.(\d+)\.(\d+)/$", url)
        if m:
            key = m.group(1)
            ver = tuple(int(x) for x in m.groups()[1:])
            if key not in docs_rel or ver > docs_rel[key][0]:
                docs_rel[key] = (ver, url)
    tail = []
    for key, label in (("ingestion", "OLake Go"), ("maintenance", "OLake Fusion")):
        if key in docs_rel:
            ver, url = docs_rel[key]
            tail.append(f"- The newest {label} release-notes page on olake.io is v{'.'.join(map(str, ver))}: {url}")
            cite.append(url)
    body = ("# Latest OLake versions\n\nThe newest releases on GitHub, from the GitHub releases API when this index was "
            "built. GitHub releases are often newer than the release notes on olake.io, which follow a few days later.\n\n"
            + "\n".join(lines) + "\n\n" + "\n".join(tail) + "\n")
    return {"name": "latest-versions", "title": "Latest OLake versions (GitHub releases)", "cite_urls": cite,
            "body": body, "hash": sha256(body)}


def collect(offline: bool = False, outside: bool = True) -> Corpus:
    c = Corpus(outside_enabled=outside)
    t = time.perf_counter()
    collect_docs(c, offline)
    log.info("docs: %d pages (%d fetch errors) in %.1fs", len(c.pages), len(c.page_errors), time.perf_counter() - t)
    collect_releases(c, offline)
    c.faqs, c.faq_errors = fetch_faqs(offline=offline)
    collect_repos(c, offline)
    collect_issues(c, offline)
    if outside:
        c.outside, c.outside_skipped = fetch_outside(offline=offline)
    c.factcards = sources.load_factcards()
    card = latest_versions_card(c.releases, [p["url"] for p in c.pages])
    if card:
        c.factcards.append(card)
    return c


def chunk_corpus(c: Corpus) -> list[dict]:
    chunks: list[dict] = []
    for p in c.pages:
        chunks += sources.docs_chunks(p)
    for repo in config.REPOS:
        for rel in c.releases.get(repo, []):
            chunks += sources.release_gh_chunks(rel)
    for rec in c.faqs:
        chunks += sources.faq_chunks(rec)
    for card in c.factcards:
        chunks += sources.factcard_chunks(card)
    for f in c.repo_files:
        chunks += sources.repo_chunks(f)
    for issue in c.issues:
        chunks.append(sources.issue_chunk(issue, c.issue_notes.get(issue["url"])))
    for page in c.outside:
        chunks += sources.outside_chunks(page)
    return sources.sort_chunks(chunks)


# ----------------------------------------------------------------------------- validation
BLOB_URL = re.compile(r"^https://github\.com/datazip-inc/(olake|olake-ui|olake-helm|olake-fusion)/blob/[^/]+/.+")
RELEASE_URL = re.compile(r"^https://github\.com/datazip-inc/(olake|olake-ui|olake-helm|olake-fusion)/releases/tag/.+")


def allowed_doc_urls(sitemap_docs_kept: set[str]) -> dict[str, set[str]]:
    return {
        "docs": sitemap_docs_kept, "release": sitemap_docs_kept,
        "faq": {u for u, _ in config.FAQ_PAGES},
        "issue": set(config.CURATED_ISSUES),
        "outside": {u for u, _ in config.OUTSIDE_PAGES},
    }


def validate(chunks: list[dict], kept_docs: set[str], hard_max: int = CHUNK_HARD_MAX) -> list[str]:
    """Every acceptance rule that can be checked on the chunk list. Returns the problems found."""
    problems: list[str] = []
    allowed = allowed_doc_urls(kept_docs)
    ids = Counter(c["id"] for c in chunks)
    for dup, n in ids.items():
        if n > 1:
            problems.append(f"duplicate id {dup} x{n}")
    for c in chunks:
        cid = c.get("id")
        if tuple(c) != FIELDS:
            problems.append(f"{cid}: fields {tuple(c)} != I1")
        body = c["text"].split("\n\n", 1)[1] if "\n\n" in c["text"] else ""
        if not body.strip():
            problems.append(f"{cid}: empty chunk")
        if c["tokens"] > hard_max or ntok(c["text"]) > hard_max:
            problems.append(f"{cid}: {c['tokens']} tokens > hard max {hard_max}")
        if c["tokens"] != ntok(c["text"]) or c["hash"] != sha256(c["text"]):
            problems.append(f"{cid}: tokens/hash do not match the text")
        if not fences_balanced(c["text"]):
            problems.append(f"{cid}: unbalanced code fence")
        if len(tab_labels_in(c["text"])) > 1:
            problems.append(f"{cid}: spans two tab panels")
        st, doc_url = c["source_type"], c["doc_url"]
        if "raw.githubusercontent.com" in doc_url or "raw.githubusercontent.com" in c["url"]:
            problems.append(f"{cid}: raw.githubusercontent.com URL")
        if st in ("docs", "release"):
            if c["product"] not in ("go", "fusion"):
                problems.append(f"{cid}: product not set")
            if doc_url not in allowed[st]:
                problems.append(f"{cid}: doc_url {doc_url} is not a kept sitemap URL")
            if c["url"] != doc_url and not (c["anchor"] and c["url"] == f"{doc_url}#{c['anchor']}"):
                problems.append(f"{cid}: url {c['url']} is not doc_url#anchor")
        elif st == "release-gh":
            if not RELEASE_URL.match(doc_url):
                problems.append(f"{cid}: doc_url {doc_url} is not a releases/tag URL")
            if c["product"] != config.REPO_PRODUCT.get(c["repo"] or ""):
                problems.append(f"{cid}: product {c['product']!r} != {config.REPO_PRODUCT.get(c['repo'] or '')!r}")
        elif st == "repo":
            if not BLOB_URL.match(doc_url) or not BLOB_URL.match(c["url"]):
                problems.append(f"{cid}: repo URL {doc_url} / {c['url']} is not a datazip-inc blob URL")
            if c["commit"] and f"/blob/{c['commit']}/" not in c["url"]:
                problems.append(f"{cid}: url is not the SHA permalink")
        elif st in ("faq", "issue", "outside"):
            if doc_url not in allowed[st]:
                problems.append(f"{cid}: doc_url {doc_url} is not a curated {st} URL")
        elif st == "factcard":
            cite = c["cite_urls"] or []
            if not cite or doc_url != cite[0]:
                problems.append(f"{cid}: doc_url must be the first cite_url")
            for u in cite:
                if u not in kept_docs and u not in allowed["faq"] and not RELEASE_URL.match(u):
                    problems.append(f"{cid}: cite_url {u} is not a kept sitemap URL, a FAQ page or a releases/tag URL")
        else:
            problems.append(f"{cid}: unexpected source_type {st}")
        if st != "factcard" and c["cite_urls"] is not None:
            problems.append(f"{cid}: cite_urls is for factcard chunks only")
    return problems


# ----------------------------------------------------------------------------- manifest pieces
def docs_section(c: Corpus) -> dict:
    lastmods = [p["lastmod"] for p in c.pages if p.get("lastmod")]
    return {
        "sitemap": config.SITEMAP_URL,
        "sitemap_etag": c.sitemap.etag if c.sitemap else None,
        "sitemap_last_modified": c.sitemap.last_modified if c.sitemap else None,
        "sitemap_docs_urls": len(c.sitemap_docs),
        "lastmod_max": max(lastmods) if lastmods else None,
        "pages": {p["url"]: {"lastmod": p.get("lastmod"), "hash": p["hash"]} for p in c.pages},
        "fetch_errors": c.page_errors,
    }


def releases_section(c: Corpus) -> dict:
    out = {}
    for repo in config.REPOS:
        rels = [r for r in c.releases.get(repo, []) if not r.get("prerelease")]
        if rels:
            out[repo] = {"tag": rels[0]["tag"], "published_at": rels[0].get("published_at")}
    return out


def sources_section(c: Corpus) -> dict:
    return {
        "repo_files": {f"{f['repo']}/{f['path']}": sha256(f["text"]) for f in c.repo_files},
        "releases": {f"{r['repo']}@{r['tag']}": sha256(sources.release_markdown(r)[1])
                     for repo in config.REPOS for r in c.releases.get(repo, [])},
        "faq": {f"{q['page_url']}#{q['n']}": sha256(q["question"] + "\n" + q["answer"]) for q in c.faqs},
        "faq_errors": c.faq_errors,
        "issues": {i["url"]: {"state": i.get("state"), "updated_at": i.get("updated_at"),
                              "note": (c.issue_notes.get(i["url"]) or {}).get("file")} for i in c.issues},
        "outside": {"enabled": c.outside_enabled, "pages": {p["url"]: p["hash"] for p in c.outside},
                    "skipped": c.outside_skipped},
        "factcards": {card["name"]: card["hash"] for card in c.factcards},
        "errors": c.errors,
    }


# ----------------------------------------------------------------------------- build
def publish(index_root: Path, chunks: list[dict], *, model: str, docs: dict, repos: dict, releases: dict,
            denylist_skipped: list[str], sources_info: dict, build_info: dict) -> tuple[str, dict, dict]:
    """Embed (reusing vectors), write a new version and swap CURRENT. Returns (version, manifest, embed stats)."""
    current = read_current(index_root)
    reuse = vectors_from_index(index_root / current, model) if current else {}
    matrix, stats = embed_chunks(chunks, model=model, reuse=reuse)
    now = utc_now()
    version = new_version(index_root, now)
    manifest = make_manifest(version=version, built_at=now, model=model, dim=stats["dim"], chunks=chunks, docs=docs,
                             repos=repos, releases=releases, denylist_skipped=denylist_skipped,
                             sources=sources_info, build={**build_info, "embedded": stats["embedded"],
                                                          "reused_vectors": stats["reused"],
                                                          "previous_version": current})
    write_version(index_root, version, chunks, matrix, manifest)
    swap_current(index_root, version)
    return version, manifest, stats


def build(*, offline: bool = False, outside: bool = True, do_prune: bool = False, index_root: Path = INDEX_DIR,
          model: str = EMBED_MODEL) -> dict:
    try:
        with index_lock():
            return _build(offline=offline, outside=outside, do_prune=do_prune, index_root=index_root, model=model)
    except Busy as e:
        raise SystemExit(str(e)) from e


def _build(*, offline: bool, outside: bool, do_prune: bool, index_root: Path, model: str) -> dict:
    t0 = time.perf_counter()
    corpus = collect(offline=offline, outside=outside)
    chunks = chunk_corpus(corpus)
    kept = {e.url for e in corpus.entries}
    factcard_misses = check_cards(corpus.factcards, page_texts(corpus))
    for m in factcard_misses:
        log.warning("factcard %s: %r not found on its cited pages (%s)", m["card"], m["token"], m["line"])
    problems = validate(chunks, kept)
    if problems:
        for p in problems[:50]:
            log.error("validation: %s", p)
        raise SystemExit(f"index validation failed: {len(problems)} problems (first: {problems[0]})")
    version, manifest, stats = publish(
        index_root, chunks, model=model, docs=docs_section(corpus), repos=corpus.repos,
        releases=releases_section(corpus), denylist_skipped=corpus.denylist_skipped,
        sources_info={**sources_section(corpus), "factcard_check": {"unmatched": len(factcard_misses),
                                                                    "items": factcard_misses}},
        build_info={"command": "index.build", "offline": offline, "outside": outside})
    removed = prune(index_root) if do_prune else []
    if index_root.resolve() == INDEX_DIR.resolve():
        # the refresher's poll state follows the main index only (an A/B build elsewhere leaves it alone):
        # it restarts from this build's sitemap ETag, with no repo or tag shortcuts
        save_state({"sitemap_etag": manifest["docs"].get("sitemap_etag")})
    report(corpus, manifest, stats, removed, time.perf_counter() - t0)
    return manifest


def report(c: Corpus, manifest: dict, stats: dict, removed: list[str], seconds: float) -> None:
    counts = manifest["counts"]
    print(f"index {manifest['version']} built in {seconds:.1f}s: {counts['chunks']} chunks; "
          f"{stats['embedded']} embedded, {stats['reused']} vectors reused; model {manifest['embed_model']} "
          f"(dim {manifest['dim']})")
    print(f"sitemap /docs/ URLs: {len(c.sitemap_docs)}; denylisted: {len(c.denylist_skipped)}; "
          f"docs + release pages indexed: {counts['pages']} (fetch errors: {len(c.page_errors)})")
    print("by source_type (pages, chunks):")
    for st, v in counts["by_source_type"].items():
        print(f"  {st:<11} {v['pages']:>4} {v['chunks']:>5}")
    print(f"denylisted URLs skipped ({len(c.denylist_skipped)}):")
    for u in c.denylist_skipped:
        print(f"  {u}")
    if c.outside_enabled:
        print(f"outside pages: {len(c.outside)} indexed, {len(c.outside_skipped)} skipped"
              + "".join(f"\n  skipped {s['url']} ({s.get('error') or s.get('status')})" for s in c.outside_skipped))
    else:
        print("outside pages: off (--no-outside)")
    for e in c.errors:
        print(f"warning: {e}")
    if removed:
        print(f"pruned versions: {', '.join(removed)}")
    print(f"CURRENT -> {manifest['version']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="re-extract from cached HTML, clones and API responses")
    ap.add_argument("--no-outside", action="store_true", help="leave the curated outside pages (tier 4) out")
    ap.add_argument("--prune", action="store_true", help="keep only CURRENT and the previous version")
    ap.add_argument("--out-root", "--index-dir", dest="out_root", type=Path, default=INDEX_DIR,
                    help="index root to write (default: INDEX_DIR, i.e. data/index); A/B builds go to .cache/index-ab")
    args = ap.parse_args(argv)
    logs.setup()
    build(offline=args.offline, outside=not args.no_outside, do_prune=args.prune, index_root=args.out_root)


if __name__ == "__main__":
    main()
