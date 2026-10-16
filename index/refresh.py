"""Incremental refresh of the active index (plan Appendix A "Freshness", research.md §3.6).

    uv run python -m index.refresh [--check]
    from index.refresh import refresh_once
    refresh_once(index_root=INDEX_DIR, *, check=False) -> dict

* Docs: a conditional GET of sitemap.xml with If-None-Match (the stored ETag). 304: nothing to do.
  200: re-fetch every docs page, hash the extracted text per page; re-chunk only new or changed
  pages, tombstone URLs that left the sitemap, and re-check the two FAQ pages (same site deploy).
  The ETag only decides whether to re-fetch: ETag, Last-Modified and lastmod are never content
  signals (every site deploy changes them on every page).
* Repos: `git ls-remote HEAD` (no API quota). On a new SHA: the compare API {old}...{new}, filtered
  by the Tier A allowlist; only those files are fetched at the new SHA (contents API), re-chunked
  and re-embedded; unchanged files keep their chunks, re-pointed at the new SHA. If the compare
  fails, a fresh shallow clone is diffed by content hash instead.
* Releases: `git ls-remote --tags`; when the tag set changes, the releases API for the new list.
* Chunks are re-embedded only when their (hash, model) is new. A new version is written and
  CURRENT swapped only when content changed; --check reports without writing anything.

refresh_once never raises: errors are listed in result["errors"]. It blocks (network, git,
embedding), so the app calls it from a worker thread; concurrent calls return {"skipped": "busy"}.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from index import logs, sources
from index.build import RELEASE_URL, latest_versions_card, publish, validate
from index.chunk import sha256
from index.config import INDEX_DIR
from index.lock import Busy, index_lock, load_state, save_state
from index.manifest import iso, load_version, prune, read_current, utc_now
from ingest import config
from ingest.docs import fetch_docs, fetch_sitemap
from ingest.faq import fetch_faqs
from ingest.github import (GitHubError, allowed, blob_url, clone_repo, compare_files, fetch_file_at,
                           fetch_releases, ls_remote_head, ls_remote_tags, prepare_text, read_repo_files,
                           release_url)
from ingest.sitemap import docs_urls, parse_sitemap, select_docs

log = logging.getLogger("index.refresh")

_LOCK = threading.Lock()
MAX_FILE_FETCHES = 20  # more changed allowlisted files than this: one shallow clone instead


def tag_fingerprint(tags: dict[str, str]) -> str:
    return sha256("\n".join(f"{t} {s}" for t, s in sorted(tags.items())))


# ----------------------------------------------------------------------------- entry point
def refresh_once(index_root: str | Path = INDEX_DIR, *, check: bool = False) -> dict:
    if not _LOCK.acquire(blocking=False):
        return {"changed": False, "version": None, "written": False, "skipped": "busy", "errors": []}
    try:
        try:
            with index_lock():
                return Refresher(Path(index_root), check).run()
        except Busy as e:
            return {"changed": False, "version": None, "written": False, "skipped": "busy", "errors": [str(e)]}
        except Exception as e:  # noqa: BLE001  (the poller must survive anything; the log has the traceback)
            log.exception("refresh failed")
            return {"changed": False, "version": None, "written": False, "errors": [f"{type(e).__name__}: {e}"]}
    finally:
        _LOCK.release()


class Refresher:
    def __init__(self, index_root: Path, check: bool):
        self.index_root = index_root
        self.check = check
        self.t0 = time.perf_counter()
        self.replace: dict[str, list[dict]] = {}          # doc key -> new chunks ([] = tombstone)
        self.retarget: dict[str, tuple[str, str | None]] = {}  # repo -> (commit, date) for unchanged files
        self.releases_by_repo: dict[str, list[dict]] = {}
        self.docs_changed = False
        self.report: dict = {"changed": False, "version": None, "written": False, "check": check,
                             "checked_at": iso(utc_now()), "docs": {}, "faq": {}, "repos": {}, "releases": {},
                             "factcards": {}, "chunks": {}, "errors": []}

    def err(self, msg: str) -> None:
        log.warning("refresh: %s", msg)
        self.report["errors"].append(msg)

    def done(self) -> dict:
        self.report["seconds"] = round(time.perf_counter() - self.t0, 2)
        return self.report

    # ------------------------------------------------------------------------- run
    def run(self) -> dict:
        current = read_current(self.index_root)
        if not current:
            self.err("no index yet: run `uv run python -m index.build` first")
            return self.done()
        self.report["previous_version"] = current
        self.manifest, self.chunks, _ = load_version(self.index_root, current)
        self.state = load_state()
        self.new_state = copy.deepcopy(self.state)
        self.docs = copy.deepcopy(self.manifest["docs"])
        self.repos = copy.deepcopy(self.manifest["repos"])
        self.releases = copy.deepcopy(self.manifest["releases"])
        self.src = copy.deepcopy(self.manifest.get("sources") or {})
        for key in ("repo_files", "releases", "faq", "factcards"):
            self.src.setdefault(key, {})
        self.denylist_skipped = list(self.manifest.get("denylist_skipped") or [])

        self.refresh_docs()
        with ThreadPoolExecutor(max_workers=4) as pool:  # ls-remote calls cost ~1 s each: overlap them
            heads = dict(zip(config.REPOS, pool.map(self._safe_head, config.REPOS)))
            tags = dict(zip(config.REPOS, pool.map(self._safe_tags, config.REPOS)))
        for repo in config.REPOS:
            self.refresh_repo(repo, heads[repo])
        for repo in config.REPOS:
            self.refresh_releases(repo, tags[repo])
        self.refresh_latest_card()

        if not self.replace:
            if not self.check:
                save_state(self.new_state)
            self.report["chunks"] = {"total": len(self.chunks), "replaced_docs": 0}
            return self.done()
        return self.publish()

    # ------------------------------------------------------------------------- docs + faq
    def refresh_docs(self) -> None:
        etag = self.state.get("sitemap_etag") or self.docs.get("sitemap_etag")
        sm = fetch_sitemap(etag=etag)
        r = self.report["docs"]
        r["sitemap_status"] = sm.status
        if sm.status == 304:
            r.update(added=[], changed=[], removed=[])
            return
        if sm.status != 200:
            self.err(f"sitemap: {sm.error or sm.status}")
            return
        entries = parse_sitemap(sm.text)
        kept, skipped = select_docs(entries)
        pages, errors = fetch_docs(kept)
        old_pages = self.docs.get("pages") or {}
        fetched = {p["url"]: p for p in pages}
        kept_urls = {e.url for e in kept}
        added = [u for u in fetched if u not in old_pages]
        changed = [u for u in fetched if u in old_pages and old_pages[u].get("hash") != fetched[u]["hash"]]
        removed = [u for u in old_pages if u not in kept_urls]
        for u in added + changed:
            page = fetched[u]
            self.replace[f"{page['source_type']}:{u}"] = sources.docs_chunks(page)
        for u in removed:
            st = "release" if u.startswith(config.RELEASE_PREFIXES) else "docs"
            self.replace[f"{st}:{u}"] = []
        new_pages = {}
        for e in kept:
            if e.url in fetched:
                new_pages[e.url] = {"lastmod": e.lastmod, "hash": fetched[e.url]["hash"]}
            elif e.url in old_pages:  # a failed fetch keeps the page's old chunks (no tombstone on errors)
                new_pages[e.url] = old_pages[e.url]
        lastmods = [v["lastmod"] for v in new_pages.values() if v.get("lastmod")]
        self.docs.update({"sitemap_etag": sm.etag, "sitemap_last_modified": sm.last_modified,
                          "sitemap_docs_urls": len(docs_urls(entries)),
                          "lastmod_max": max(lastmods) if lastmods else None, "pages": new_pages,
                          "fetch_errors": errors})
        self.denylist_skipped = skipped
        self.new_state["sitemap_etag"] = sm.etag
        self.docs_changed = bool(added or removed)
        r.update(added=added, changed=changed, removed=removed, fetch_errors=len(errors))
        self.refresh_faq()

    def refresh_faq(self) -> None:
        recs, errors = fetch_faqs()
        failed = {e["url"] for e in errors}
        old = self.src["faq"]
        new = {k: h for k, h in old.items() if k.split("#", 1)[0] in failed}  # keep pages that failed
        changed = 0
        for rec in recs:
            key = f"{rec['page_url']}#{rec['n']}"
            h = sha256(rec["question"] + "\n" + rec["answer"])
            new[key] = h
            if old.get(key) != h:
                chunks = sources.faq_chunks(rec)
                self.replace[sources.doc_key(chunks[0])] = chunks
                changed += 1
        removed = 0
        for key in old:
            if key not in new:
                page_url, n = key.rsplit("#", 1)
                self.replace[f"faq/{sources.url_slug(page_url) or 'home'}/{n}"] = []
                removed += 1
        self.src["faq"] = new
        self.src["faq_errors"] = errors
        self.report["faq"] = {"changed": changed, "removed": removed}

    # ------------------------------------------------------------------------- repos
    def _safe_head(self, repo: str) -> str | None:
        try:
            return ls_remote_head(repo)
        except Exception as e:  # noqa: BLE001
            self.err(f"git ls-remote {repo}: {e}")
            return None

    def _safe_tags(self, repo: str) -> dict | None:
        try:
            return ls_remote_tags(repo)
        except Exception as e:  # noqa: BLE001
            self.err(f"git ls-remote --tags {repo}: {e}")
            return None

    def refresh_repo(self, repo: str, head: str | None) -> None:
        r = self.report["repos"][repo] = {"moved": False}
        old = self.repos.get(repo)
        if head is None:
            return
        r["head"] = head[:7]
        if old and head == old["commit"]:
            return
        if old and (self.state.get("repos_checked") or {}).get(repo) == head:
            r["no_allowlisted_change_since"] = old["commit"][:7]
            return
        r["moved"] = True
        if not old:
            self.err(f"repo {repo} is not in the index; run a full build")
            return
        try:
            recs, removed, method, head, date = self.repo_changes(repo, old, head)
        except Exception as e:  # noqa: BLE001
            self.err(f"repo {repo}: {e}")
            return
        r.update(method=method, changed_files=[f["path"] for f in recs], removed_files=sorted(removed))
        if not recs and not removed:  # HEAD moved, but no allowlisted file changed: nothing to re-index
            self.new_state.setdefault("repos_checked", {})[repo] = head
            return
        branch = old["branch"]
        for f in recs:
            self.replace[f"repo:{blob_url(repo, branch, f['path'])}"] = sources.repo_chunks(f)
            self.src["repo_files"][f"{repo}/{f['path']}"] = sha256(f["text"])
        for path in removed:
            self.replace[f"repo:{blob_url(repo, branch, path)}"] = []
            self.src["repo_files"].pop(f"{repo}/{path}", None)
        self.retarget[repo] = (head, date)
        self.repos[repo] = {"branch": branch, "commit": head, "commit_date": date}
        self.new_state.setdefault("repos_checked", {}).pop(repo, None)

    def repo_changes(self, repo: str, old: dict, head: str) -> tuple[list[dict], set[str], str, str, str | None]:
        """(changed allowlisted file records at the new SHA, removed paths, method, head, commit date)."""
        try:
            files, date = compare_files(repo, old["commit"], head)
            relevant = [f for f in files if allowed(repo, f["filename"] or "")
                        or (f.get("previous_filename") and allowed(repo, f["previous_filename"]))]
            removed = {f["filename"] for f in relevant if f["status"] == "removed"}
            removed |= {f["previous_filename"] for f in relevant
                        if f["status"] == "renamed" and f.get("previous_filename") and allowed(repo, f["previous_filename"])}
            to_fetch = [f["filename"] for f in relevant if f["status"] != "removed" and allowed(repo, f["filename"])]
            if len(to_fetch) > MAX_FILE_FETCHES:
                raise GitHubError(f"{len(to_fetch)} changed allowlisted files; cloning instead")
            recs = []
            for path in to_fetch:
                kind, text = prepare_text(repo, path, fetch_file_at(repo, head, path))
                recs.append({"repo": repo, "path": path, "kind": kind, "text": text, "branch": old["branch"],
                             "commit": head, "commit_date": date or old.get("commit_date")})
            return recs, removed, "compare", head, date or old.get("commit_date")
        except GitHubError as e:
            log.info("compare for %s unavailable (%s); diffing a fresh clone by content hash", repo, e)
        info = clone_repo(repo)
        files = read_repo_files(info)
        old_hashes = {k.split("/", 1)[1]: h for k, h in self.src["repo_files"].items() if k.split("/", 1)[0] == repo}
        recs = [dict(f, branch=old["branch"]) for f in files if old_hashes.get(f["path"]) != sha256(f["text"])]
        removed = set(old_hashes) - {f["path"] for f in files}
        return recs, removed, "clone", info["commit"], info["commit_date"]

    # ------------------------------------------------------------------------- releases
    def refresh_releases(self, repo: str, tags: dict | None) -> None:
        r = self.report["releases"][repo] = {"checked": False}
        if tags is None:
            return
        fp = tag_fingerprint(tags)
        known = (self.state.get("tags") or {}).get(repo)
        if known == fp:
            return
        try:
            rels = sources.mark_latest(repo, fetch_releases(repo, max_age_s=0 if known else 600))
        except GitHubError as e:
            self.err(f"releases {repo}: {e}")
            return
        r["checked"] = True
        self.releases_by_repo[repo] = rels
        old = {k: h for k, h in self.src["releases"].items() if k.split("@", 1)[0] == repo}
        new_keys = set()
        changed = []
        for rel in rels:
            key = f"{repo}@{rel['tag']}"
            new_keys.add(key)
            h = sha256(sources.release_markdown(rel)[1])
            if old.get(key) != h:
                self.replace[f"release-gh:{rel['url']}"] = sources.release_gh_chunks(rel)
                changed.append(rel["tag"])
            self.src["releases"][key] = h
        removed = [k for k in old if k not in new_keys]
        for key in removed:
            self.replace[f"release-gh:{release_url(repo, key.split('@', 1)[1])}"] = []
            self.src["releases"].pop(key, None)
        latest = next((x for x in rels if not x.get("prerelease")), None)
        if latest:
            self.releases[repo] = {"tag": latest["tag"], "published_at": latest.get("published_at")}
        self.new_state.setdefault("tags", {})[repo] = fp
        r.update(changed=changed, removed=[k.split("@", 1)[1] for k in removed])

    def refresh_latest_card(self) -> None:
        if not self.releases_by_repo and not self.docs_changed:
            return
        rels = {}
        for repo in config.REPOS:
            if repo in self.releases_by_repo:
                rels[repo] = self.releases_by_repo[repo]
                continue
            try:  # unchanged repos: the cached API response (online only if the cache is gone)
                rels[repo] = sources.mark_latest(repo, fetch_releases(repo, offline=True))
            except GitHubError:
                try:
                    rels[repo] = sources.mark_latest(repo, fetch_releases(repo))
                except GitHubError as e:
                    self.err(f"latest-versions card: releases {repo}: {e}")
                    return
        card = latest_versions_card(rels, list((self.docs.get("pages") or {}).keys()))
        if card and self.src["factcards"].get(card["name"]) != card["hash"]:
            self.replace[f"factcard/{card['name']}"] = sources.factcard_chunks(card)
            self.src["factcards"][card["name"]] = card["hash"]
            self.report["factcards"]["regenerated"] = [card["name"]]

    # ------------------------------------------------------------------------- assemble + publish
    def assemble(self) -> list[dict]:
        keep = []
        for c in self.chunks:
            if sources.doc_key(c) in self.replace:
                continue
            if c["source_type"] == "repo" and c.get("repo") in self.retarget:
                c = sources.retarget_repo_chunk(c, *self.retarget[c["repo"]])
            keep.append(c)
        new = [c for cs in self.replace.values() for c in cs]
        out = sources.sort_chunks(keep + new)
        # fact cards keep only citations that are still valid (a cited page may have left the sitemap)
        valid = set(self.docs.get("pages") or {}) | {u for u, _ in config.FAQ_PAGES}
        fixed = []
        for c in out:
            if c["source_type"] == "factcard":
                cite = [u for u in c["cite_urls"] or [] if u in valid or RELEASE_URL.match(u)]
                if not cite:
                    self.err(f"factcard chunk {c['id']} lost every citation; dropped (fix index/factcards/)")
                    continue
                if cite != c["cite_urls"]:
                    self.err(f"factcard chunk {c['id']}: dropped citations {sorted(set(c['cite_urls']) - set(cite))}")
                    c = dict(c, cite_urls=cite, doc_url=cite[0], url=cite[0])
            fixed.append(c)
        return fixed

    def publish(self) -> dict:
        new_chunks = self.assemble()
        old_hashes = {c["hash"] for c in self.chunks}
        self.report["chunks"] = {"before": len(self.chunks), "after": len(new_chunks),
                                 "replaced_docs": len(self.replace),
                                 "new_or_changed": sum(c["hash"] not in old_hashes for c in new_chunks)}
        self.report["changed"] = True
        problems = validate(new_chunks, set(self.docs.get("pages") or {}))
        if problems:
            for p in problems[:20]:
                self.err(f"validation: {p}")
            self.report["written"] = False
            return self.done()
        if self.check:
            return self.done()
        version, manifest, stats = publish(
            self.index_root, new_chunks, model=self.manifest["embed_model"], docs=self.docs, repos=self.repos,
            releases=self.releases, denylist_skipped=self.denylist_skipped, sources_info=self.src,
            build_info={"command": "index.refresh", "outside": (self.src.get("outside") or {}).get("enabled")})
        save_state(self.new_state)
        # keep CURRENT and the version before it: a container (Cloud Run's in-memory disk) must not grow per refresh
        pruned = prune(self.index_root)
        self.report.update(version=version, written=True, embedded=stats["embedded"], pruned=pruned)
        log.info("refresh wrote %s (%d chunks, %d embedded)", version, len(new_chunks), stats["embedded"])
        return self.done()


def summarize(r: dict) -> str:
    lines = [f"changed: {r.get('changed')}  written: {r.get('written')}  version: {r.get('version')}  "
             f"(previous {r.get('previous_version')}, {r.get('seconds')} s)"]
    if r.get("skipped"):
        lines.append(f"skipped: {r['skipped']}")
    d = r.get("docs") or {}
    if d:
        lines.append(f"docs: sitemap HTTP {d.get('sitemap_status')}; added {len(d.get('added') or [])}, "
                     f"changed {len(d.get('changed') or [])}, removed {len(d.get('removed') or [])}")
        for k in ("added", "changed", "removed"):
            lines += [f"  {k}: {u}" for u in d.get(k) or []]
    if r.get("faq"):
        lines.append(f"faq: {r['faq']}")
    for repo, v in (r.get("repos") or {}).items():
        lines.append(f"repo {repo}: head {v.get('head')} moved={v.get('moved')}"
                     + (f" via {v['method']}: changed {v.get('changed_files')}, removed {v.get('removed_files')}"
                        if v.get("method") else ""))
    for repo, v in (r.get("releases") or {}).items():
        if v.get("checked"):
            lines.append(f"releases {repo}: changed {v.get('changed')}, removed {v.get('removed')}")
    if r.get("chunks"):
        lines.append(f"chunks: {r['chunks']}")
    lines += [f"error: {e}" for e in r.get("errors") or []]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Refresh the active index incrementally")
    ap.add_argument("--check", action="store_true", help="report what changed; write nothing")
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)
    logs.setup()
    result = refresh_once(args.index_dir, check=args.check)
    print(json.dumps(result, indent=1) if args.json else summarize(result))


if __name__ == "__main__":
    main()
