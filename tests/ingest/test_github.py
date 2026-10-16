from __future__ import annotations

import pytest

from index.sources import repo_chunks
from ingest.github import (allowed, keep_sections, parse_issue_url, prepare_text, redact_credentials, strip_banner,
                           strip_markdown_html)

SHA = "d20c68ed98ced12293cd621ac04136a946ba4290"


@pytest.mark.parametrize("repo,path,ok", [
    ("olake", "README.md", True),
    ("olake", "drivers/postgres/README.md", True),
    ("olake", "drivers/postgres/resources/spec.json", True),
    ("olake", "destination/iceberg/resources/spec.json", True),
    ("olake", "destination/parquet/resources/spec.json", True),
    ("olake", "destination/iceberg/README.md", True),
    ("olake", "protocol/root.go", True),
    ("olake", "docker-compose.yml", False),           # the stale root compose file
    ("olake", "drivers/postgres/internal/config.go", False),
    ("olake", "drivers/postgres/internal/postgres_test.go", False),
    ("olake", "go.sum", False),
    ("olake", ".github/workflows/ci.yml", False),
    ("olake-ui", "docker-compose-v1.yml", True),
    ("olake-ui", "server/conf/app.yaml", True),
    ("olake-ui", "ui/package-lock.json", False),
    ("olake-helm", "helm/olake/values.yaml", True),
    ("olake-helm", "helm/olake/templates/NOTES.txt", True),
    ("olake-helm", "helm/olake/templates/deployment.yaml", False),
    ("olake-fusion", "CLAUDE.md", True),
    ("olake-fusion", "docs/user-guides/configurations.md", False),  # upstream Amoro docs are never indexed
    ("olake-fusion", "site/content/index.md", False),
    ("olake-fusion", "ams/server/src/main/java/Foo.java", False),
])
def test_tier_a_allowlist(repo, path, ok):
    assert allowed(repo, path) is ok


def test_credentials_redacted_line_by_line():
    yaml = "\n".join([
        'username: &defaultUsername "admin"',
        'password: &defaultPassword "password"',
        "  POSTGRES_PASSWORD: temporal",
        '  rootPassword: "password"  # change me',
        "  - SQL_PASSWORD=temporal",
        '  existingSecret: "my-secret"',
        '  OLAKE_SECRET_KEY: ""',
        "  password: *defaultPassword",
        "  PASSWORD: ${PG_PASSWORD}",
        '        -d \'{"user":"admin","password":"password"}\'',
    ])
    out = redact_credentials(yaml, "yaml").split("\n")
    assert len(out) == 10
    assert out[0] == 'username: &defaultUsername "admin"'  # usernames are not secrets
    assert out[1] == 'password: &defaultPassword "<redacted>"'
    assert out[2] == "  POSTGRES_PASSWORD: <redacted>"
    assert out[3] == '  rootPassword: "<redacted>"  # change me'
    assert out[4] == "  - SQL_PASSWORD=<redacted>"
    assert out[5] == '  existingSecret: "my-secret"'  # a secret's name, not a credential
    assert out[6] == '  OLAKE_SECRET_KEY: ""'  # empty stays empty
    assert out[7] == "  password: *defaultPassword"  # references are not values
    assert out[8] == "  PASSWORD: ${PG_PASSWORD}"
    assert '"password":"<redacted>"' in out[9]


def test_json_in_markdown_keeps_commas():
    md = '```json\n{\n  "jdbc_password": "password",\n  "resume_token": {"_data": "8267"},\n  "port": 5432\n}\n```'
    out = redact_credentials(md, "markdown")
    assert '"jdbc_password": "<redacted>",' in out
    assert '"resume_token": {"_data": "8267"}' in out  # a CDC position, not a secret
    assert out.count("\n") == md.count("\n")


def test_prose_password_redacted():
    out = redact_credentials("- **Default login:** Username: `admin`, Password: `password`", "markdown")
    assert out == "- **Default login:** Username: `admin`, Password: `<redacted>`"


def test_fusion_claude_md_keeps_sections_1_to_4_and_line_numbers():
    text = "\n".join(["# Title", "intro", "## 1. Scope", "scope text", "### Sub", "sub text", "## 4. UI", "ui text",
                      "## 5. Testing", "test text"])
    out = keep_sections(text, 1, 4).split("\n")
    assert len(out) == 10
    assert out[2:8] == ["## 1. Scope", "scope text", "### Sub", "sub text", "## 4. UI", "ui text"]
    assert out[0] == out[1] == out[8] == out[9] == ""


def test_notes_banner_removed_keeping_lines():
    text = "*****\n&&&&&&\nThank you for installing OLake.\n  &&&\nGet the URL: kubectl get svc"
    out = strip_banner(text).split("\n")
    assert out == ["", "", "Thank you for installing OLake.", "", "Get the URL: kubectl get svc"]


def test_readme_html_stripped_outside_code():
    md = '<p align="center"><img src="logo.png" width="100"/></p>\n[![CI](https://x/badge.svg)](https://x)\n' \
         '**OLake** is fast.\n```html\n<div>keep me</div>\n```'
    out = strip_markdown_html(md).split("\n")
    assert out[0] == "" and out[1] == "" and out[2] == "**OLake** is fast."
    assert out[4] == "<div>keep me</div>"
    assert len(out) == len(md.split("\n"))


def test_prepare_spec_and_repo_urls(fixture_text):
    kind, text = prepare_text("olake", "drivers/postgres/resources/spec.json", fixture_text("spec.json"))
    assert kind == "spec" and text.startswith("# OLake postgres source connector: configuration fields from")
    f = {"repo": "olake", "path": "drivers/postgres/resources/spec.json", "kind": kind, "text": text,
         "branch": "master", "commit": SHA, "commit_date": "2026-10-15T18:47:35+05:30"}
    chunks = repo_chunks(f)
    assert chunks
    for c in chunks:
        assert c["doc_url"] == "https://github.com/datazip-inc/olake/blob/master/drivers/postgres/resources/spec.json"
        assert c["url"] == f"https://github.com/datazip-inc/olake/blob/{SHA}/drivers/postgres/resources/spec.json"
        assert c["lines"] is None and c["repo"] == "olake" and c["commit"] == SHA and c["tier"] == 2


def test_markdown_repo_chunks_link_lines_with_plain():
    text = "# Driver\n\nIntro line.\n\n## Config\n\nSome config text.\n"
    f = {"repo": "olake", "path": "drivers/postgres/README.md", "kind": "markdown", "text": text,
         "branch": "master", "commit": SHA, "commit_date": None}
    c = repo_chunks(f)[0]
    assert c["url"] == f"https://github.com/datazip-inc/olake/blob/{SHA}/drivers/postgres/README.md?plain=1#L1-L7"
    assert c["lines"] == [1, 7]


def test_issue_urls():
    assert parse_issue_url("https://github.com/datazip-inc/olake/issues/811#issuecomment-3895500238") == \
        ("olake", 811, 3895500238)
    assert parse_issue_url("https://github.com/datazip-inc/olake-ui/issues/93") == ("olake-ui", 93, None)
    with pytest.raises(ValueError):
        parse_issue_url("https://github.com/other/olake/issues/1")


# ----------------------------------------------------------------------------- ls-remote without git
FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_ref_advertisement_parses_like_git_ls_remote():
    from ingest.github import parse_ref_advertisement
    refs = parse_ref_advertisement((FIXTURES / "info-refs-olake-helm.bin").read_bytes())
    assert len(refs["HEAD"]) == 40 and refs["HEAD"] == refs["refs/heads/master"]
    tags = [r for r in refs if r.startswith("refs/tags/")]
    assert tags and all(len(refs[t]) == 40 for t in tags)
    assert not any("\0" in r or " " in r for r in refs)  # capabilities were dropped


def test_ls_remote_uses_http_without_git(monkeypatch):
    import httpx
    from ingest import github as gh
    data = (FIXTURES / "info-refs-olake-helm.bin").read_bytes()
    monkeypatch.setattr(gh.shutil, "which", lambda name: None)
    real = httpx.Client

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(lambda req: httpx.Response(200, content=data))
        return real(*a, **kw)
    monkeypatch.setattr(gh.httpx, "Client", client)
    head = gh.ls_remote("olake-helm", ["HEAD"])
    assert list(head) == ["HEAD"]
    tags = gh.ls_remote_tags("olake-helm")
    assert tags and not any(t.endswith("^{}") for t in tags)
