"""GitHub sources: release notes, curated issues and the Tier A repo files.

* REST GETs are cached under .cache/github/ (body, ETag, fetch time) and reused: unauthenticated
  calls are limited to 60 an hour per IP and even a 304 costs one, so a cached response younger
  than `max_age_s` is reused without a request; an older one is revalidated with If-None-Match.
  GITHUB_TOKEN is used only when the environment has it, and is never logged or cached.
* Repo files come from `git clone --depth 1` at HEAD (no API quota). `git ls-remote` answers
  "did the repo move?" for free; the compare API lists the files that changed between two SHAs.
* Credential values in repo files are replaced with <redacted>, line by line, so #L anchors stay
  valid.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from index.config import github_token
from ingest import config
from ingest.spec2md import spec_to_markdown

log = logging.getLogger("ingest.github")

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    pass


# ----------------------------------------------------------------------------- REST with a cache
def _cache_file(path: str, root: Path | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/"))
    return (root or config.GITHUB_DIR) / f"{slug}.json"


def _now() -> float:
    return time.time()


def api_get(path: str, *, max_age_s: float = 3600, offline: bool = False, client: httpx.Client | None = None,
            root: Path | None = None) -> object:
    """GET https://api.github.com/<path> as JSON, through the on-disk cache (see module docstring)."""
    cf = _cache_file(path, root)
    cached = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else None
    if offline:
        if cached is None:
            raise GitHubError(f"offline and not cached: {path}")
        return cached["body"]
    if cached is not None and _now() - cached.get("fetched_ts", 0) < max_age_s:
        return cached["body"]
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": config.USER_AGENT}
    tok = github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    if cached is not None and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    own = client is None
    client = client or httpx.Client(timeout=config.HTTP_TIMEOUT_S, follow_redirects=True)
    try:
        r = None
        for attempt in range(config.HTTP_RETRIES + 1):
            try:
                r = client.get(f"{API}/{path.lstrip('/')}", headers=headers)
            except httpx.HTTPError as e:
                if attempt == config.HTTP_RETRIES:
                    if cached is not None:
                        log.warning("github %s failed (%s); using the cached response", path, type(e).__name__)
                        return cached["body"]
                    raise GitHubError(f"{path}: {e}") from e
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 500 and attempt < config.HTTP_RETRIES:
                time.sleep(1 + attempt)
                continue
            break
    finally:
        if own:
            client.close()
    assert r is not None
    remaining = r.headers.get("x-ratelimit-remaining")
    if r.status_code == 304 and cached is not None:
        cached["fetched_ts"] = _now()
        cf.write_text(json.dumps(cached, ensure_ascii=False) + "\n", encoding="utf-8")
        return cached["body"]
    if r.status_code == 200:
        body = r.json()
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps({"path": path, "etag": r.headers.get("etag"), "fetched_ts": _now(),
                                  "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "body": body}, ensure_ascii=False) + "\n", encoding="utf-8")
        return body
    limited = r.status_code in (403, 429) and remaining == "0"
    if cached is not None:
        log.warning("github %s -> HTTP %s%s; using the cached response", path, r.status_code,
                    " (rate limited)" if limited else "")
        return cached["body"]
    if limited:
        raise RateLimited(f"{path}: rate limited (resets at {r.headers.get('x-ratelimit-reset')})")
    raise GitHubError(f"{path}: HTTP {r.status_code}")


# ----------------------------------------------------------------------------- releases
def release_url(repo: str, tag: str) -> str:
    return f"https://github.com/{config.GITHUB_ORG}/{repo}/releases/tag/{quote(tag, safe='')}"


def fetch_releases(repo: str, *, per_repo: int = config.RELEASES_PER_REPO, offline: bool = False,
                   max_age_s: float = 900, client: httpx.Client | None = None) -> list[dict]:
    """The latest `per_repo` published releases, newest first."""
    body = api_get(f"repos/{config.GITHUB_ORG}/{repo}/releases?per_page={per_repo}", max_age_s=max_age_s,
                   offline=offline, client=client)
    out = []
    for r in body if isinstance(body, list) else []:
        if r.get("draft"):
            continue
        tag = r["tag_name"]
        out.append({"repo": repo, "tag": tag, "name": r.get("name") or "", "url": release_url(repo, tag),
                    "published_at": r.get("published_at"), "prerelease": bool(r.get("prerelease")),
                    "body": (r.get("body") or "").replace("\r\n", "\n").strip()})
    return out


# ----------------------------------------------------------------------------- issues
ISSUE_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:#issuecomment-(\d+))?$")


def parse_issue_url(url: str) -> tuple[str, int, int | None]:
    m = ISSUE_URL.match(url)
    if not m or m.group(1) != config.GITHUB_ORG:
        raise ValueError(f"not a curated {config.GITHUB_ORG} issue URL: {url}")
    return m.group(2), int(m.group(3)), int(m.group(4)) if m.group(4) else None


def fetch_issue(url: str, *, offline: bool = False, max_age_s: float = 86400,
                client: httpx.Client | None = None) -> dict:
    repo, number, comment_id = parse_issue_url(url)
    base = f"repos/{config.GITHUB_ORG}/{repo}/issues"
    issue = api_get(f"{base}/{number}", max_age_s=max_age_s, offline=offline, client=client)
    comments = api_get(f"{base}/{number}/comments?per_page=100", max_age_s=max_age_s, offline=offline,
                       client=client)
    rec = {
        "url": url, "repo": repo, "number": number, "comment_id": comment_id,
        "title": issue.get("title", ""), "state": issue.get("state"), "state_reason": issue.get("state_reason"),
        "created_at": issue.get("created_at"), "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"), "labels": [lb.get("name") for lb in issue.get("labels") or []],
        "body": (issue.get("body") or "").replace("\r\n", "\n"),
        "comments": [{"id": c.get("id"), "created_at": c.get("created_at"),
                      "author_association": c.get("author_association"),
                      "body": (c.get("body") or "").replace("\r\n", "\n")} for c in comments or []],
    }
    if comment_id is not None:
        rec["comment"] = next((c for c in rec["comments"] if c["id"] == comment_id), None)
    return rec


# ----------------------------------------------------------------------------- git
def run_git(args: list[str], cwd: Path | None = None, timeout: float = 120) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def remote_url(repo: str) -> str:
    return f"https://github.com/{config.GITHUB_ORG}/{repo}.git"


def clone_info(path: Path, repo: str) -> dict:
    return {"repo": repo, "path": path, "commit": run_git(["rev-parse", "HEAD"], cwd=path),
            "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path),
            "commit_date": run_git(["log", "-1", "--format=%cI"], cwd=path)}


def clone_repo(repo: str, *, offline: bool = False, root: Path | None = None) -> dict:
    """A fresh `git clone --depth 1` at HEAD into the cache (atomically replacing the old clone).
    Offline: the existing clone. Returns {repo, path, commit, branch, commit_date}."""
    root = root or config.REPOS_DIR
    dest = root / repo
    if offline:
        if not (dest / ".git").exists():
            raise GitHubError(f"offline and no cached clone of {repo}")
        return clone_info(dest, repo)
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{repo}-", dir=root))
    try:
        run_git(["clone", "--quiet", "--depth", "1", "--single-branch", remote_url(repo), str(tmp / repo)],
                timeout=300)
        if dest.exists():
            shutil.rmtree(dest)
        (tmp / repo).rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return clone_info(dest, repo)


def ls_remote(repo: str, refs: list[str] | None = None) -> dict[str, str]:
    """{ref: sha} from `git ls-remote` (no REST quota)."""
    out = run_git(["ls-remote", remote_url(repo), *(refs or ["HEAD"])], timeout=60)
    res = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if sha and ref:
            res[ref.strip()] = sha.strip()
    return res


def ls_remote_head(repo: str) -> str:
    return ls_remote(repo, ["HEAD"])["HEAD"]


def ls_remote_tags(repo: str) -> dict[str, str]:
    """{tag: sha}; annotated tags report the tag object, which is fine for change detection."""
    refs = ls_remote(repo, ["refs/tags/*"])
    return {ref.removeprefix("refs/tags/").removesuffix("^{}"): sha for ref, sha in refs.items()}


def compare_files(repo: str, old: str, new: str, *, client: httpx.Client | None = None) -> list[dict]:
    """Files changed between two commits: [{filename, status, previous_filename}] (compare API)."""
    body = api_get(f"repos/{config.GITHUB_ORG}/{repo}/compare/{old}...{new}", max_age_s=10 ** 9, client=client)
    return [{"filename": f.get("filename"), "status": f.get("status"),
             "previous_filename": f.get("previous_filename")} for f in (body or {}).get("files") or []]


def tracked_files(path: Path) -> list[str]:
    return run_git(["ls-files"], cwd=path).splitlines()


# ----------------------------------------------------------------------------- allowlist and file treatment
def allowed(repo: str, path: str, allow: dict[str, tuple[str, ...]] | None = None) -> bool:
    allow = allow or config.REPO_ALLOWLIST
    if repo not in allow:
        return False
    if any(fnmatch.fnmatch(path, d) or fnmatch.fnmatch("/" + path, d) for d in config.REPO_DENY):
        return False
    return any(fnmatch.fnmatchcase(path, pat) for pat in allow[repo])


def kind_of(path: str) -> str:
    p = path.lower()
    if p.endswith("resources/spec.json"):
        return "spec"
    if p.endswith(".md"):
        return "markdown"
    if p.endswith((".yaml", ".yml")):
        return "yaml"
    if p.endswith(".json"):
        return "json"
    if p.endswith(".go"):
        return "go"
    return "text"


def keep_sections(text: str, first: int, last: int) -> str:
    """Keep only '## <n>.' sections first..last of a Markdown file; other lines are blanked so line
    numbers (and GitHub #L anchors) stay valid."""
    keep, out = False, []
    for ln in text.split("\n"):
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            keep = first <= int(m.group(1)) <= last
        elif re.match(r"^# ", ln) or re.match(r"^## (?!\d+\.)", ln):
            keep = False
        out.append(ln if keep else "")
    return "\n".join(out)


def strip_banner(text: str) -> str:
    """NOTES.txt: blank the ASCII-art banner lines (only symbols), keeping line numbers."""
    return "\n".join("" if re.fullmatch(r"[\s&*#=_\-|/\\().'`~^\"<>:,;+@%$!?\[\]{}]*", ln) and ln.strip() else ln
                     for ln in text.split("\n"))


REDACTED = "<redacted>"
CRED_NAME = re.compile(r"(?i)(pass(word)?|passwd|pwd|secret[_-]?(access[_-]?)?key|secretkey|client[_-]?secret|"
                       r"api[_-]?key|apikey|access[_-]?key[_-]?id|private[_-]?key|auth[_-]?token|token|"
                       r"encryption[_-]?key)$")
CRED_NAME_EXCLUDE = re.compile(r"(?i)(existing[_-]?secret|secret[_-]?name|secret[_-]?keys|image[_-]?pull[_-]?secrets|"
                               r"secret[_-]?ref|token[_-]?url|token[_-]?uri|token[_-]?endpoint|resume[_-]?token|"
                               r"next[_-]?token|page[_-]?token|continuation[_-]?token)$")
YAML_KV = re.compile(r"^(?P<pre>\s*(?:-\s+)?)(?P<key>[\"']?[A-Za-z0-9_.\-]+[\"']?)(?P<sep>\s*:\s+)"
                     r"(?P<anchor>&\S+\s+)?(?P<val>\"[^\"]*\"|'[^']*'|[^#\s,][^#,]*?)(?P<comma>,?)(?P<post>\s+#.*)?\s*$")
ENV_KV = re.compile(r"(?P<key>\b[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET_ACCESS_KEY|SECRET_KEY|API_KEY|TOKEN|"
                    r"password|passwd|secret_key|api_key|token)[A-Za-z0-9_]*)=(?P<q>['\"]?)(?P<val>[^\s'\"\\]+)(?P=q)")
JSON_KV = re.compile(r"(?P<pre>\\?\"(?:password|passwd|secret|secret_key|token|api_key|apiKey)\\?\"\s*:\s*\\?\")"
                     r"(?P<val>[^\"\\]+)(?P<post>\\?\")")
PROSE_PW = re.compile(r"(?i)(?P<pre>\bpassword\b\s*[:=]?\s*)`(?P<val>[^`]+)`")
PROSE_PAIR = re.compile(r"(?i)(?P<pre>credentials?\b[^`\n]{0,40}`[^`]+`\s*/\s*)`(?P<val>[^`]+)`")
LOGIN_ECHO = re.compile(r"(?i)(?P<pre>\blogin\s*:\s*\S+\s*/\s*)(?P<val>[^\s\"']+)")


def _is_reference(val: str) -> bool:
    v = val.strip().strip("\"'")
    return (not v or v.startswith(("*", "$", "<", "{{", "%")) or v.lower() in ("true", "false", "null", "~")
            or v == REDACTED)


def redact_line(line: str, yaml_like: bool) -> str:
    if yaml_like:
        m = YAML_KV.match(line)
        if m:
            key = m.group("key").strip("\"'")
            val = m.group("val")
            if CRED_NAME.search(key) and not CRED_NAME_EXCLUDE.search(key) and not _is_reference(val):
                q = val[0] if val[:1] in "\"'" else ""
                line = (m.group("pre") + m.group("key") + m.group("sep") + (m.group("anchor") or "")
                        + f"{q}{REDACTED}{q}" + m.group("comma") + (m.group("post") or ""))
        line = LOGIN_ECHO.sub(lambda m: m.group("pre") + REDACTED, line)
    line = ENV_KV.sub(lambda m: m.group(0) if _is_reference(m.group("val"))
                      else f"{m.group('key')}={m.group('q')}{REDACTED}{m.group('q')}", line)
    line = JSON_KV.sub(lambda m: m.group(0) if _is_reference(m.group("val"))
                       else m.group("pre") + REDACTED + m.group("post"), line)
    line = PROSE_PW.sub(lambda m: m.group(0) if _is_reference(m.group("val"))
                        else m.group("pre") + f"`{REDACTED}`", line)
    line = PROSE_PAIR.sub(lambda m: m.group(0) if _is_reference(m.group("val"))
                          else m.group("pre") + f"`{REDACTED}`", line)
    return line


def redact_credentials(text: str, kind: str) -> str:
    """Replace credential values with <redacted>; one output line per input line."""
    yaml_like = kind in ("yaml", "markdown", "text")
    return "\n".join(redact_line(ln, yaml_like) for ln in text.split("\n"))


def prepare_text(repo: str, path: str, text: str) -> tuple[str, str]:
    """(kind, text) after the per-file treatment: spec.json -> Markdown field table, olake-fusion
    CLAUDE.md sections 1-4 only, NOTES.txt without the banner, credentials redacted."""
    kind = kind_of(path)
    if kind == "spec":
        what = path.split("/")[1]
        side = "source connector" if path.startswith("drivers/") else "destination (writer)"
        title = f"OLake {what} {side}: configuration fields from {path}"
        return "spec", redact_credentials(spec_to_markdown(text, title), "markdown")
    if repo == "olake-fusion" and path == "CLAUDE.md":
        text = keep_sections(text, *config.FUSION_CLAUDE_SECTIONS)
    if path.endswith("NOTES.txt"):
        text = strip_banner(text)
    return kind, redact_credentials(text, kind)


def blob_url(repo: str, ref: str, path: str) -> str:
    return f"https://github.com/{config.GITHUB_ORG}/{repo}/blob/{ref}/{path}"


def read_repo_files(info: dict, paths: list[str] | None = None) -> list[dict]:
    """Allowlisted files of one clone: [{repo, path, kind, text, branch, commit, commit_date}]."""
    repo, root = info["repo"], Path(info["path"])
    files = paths if paths is not None else tracked_files(root)
    out = []
    for path in sorted(files):
        if not allowed(repo, path):
            continue
        fp = root / path
        if not fp.is_file():
            continue
        raw = fp.read_bytes().decode("utf-8", errors="replace")
        kind, text = prepare_text(repo, path, raw)
        out.append({"repo": repo, "path": path, "kind": kind, "text": text, "branch": info["branch"],
                    "commit": info["commit"], "commit_date": info["commit_date"]})
    return out
