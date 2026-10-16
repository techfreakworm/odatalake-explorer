"""[n] parsing, renumbering by first use, dedupe after URL merging, cap 5, invalid markers, source URLs."""

from app.citations import (
    citation_details,
    parse_citation_numbers,
    resolve_citations,
    salvage_truncated,
    source_url,
    strip_sources_section,
)
from app.models import Passage


def doc(i, url, **kw):
    c = {"id": f"c{i}", "source_type": "docs", "tier": 1, "doc_url": url, "url": url + "#a", "title": f"T{i}",
         "section_path": ["S"], "text": f"T{i} | olake > S\nbody {i}"}
    c.update(kw)
    return c


def passages(*urls):
    return [Passage(n=i + 1, chunk=doc(i, u), source_url=u) for i, u in enumerate(urls)]


def test_parse_single_adjacent_comma_range_and_footnote_forms():
    assert parse_citation_numbers("a [1]. b [1][3]. c [2, 4]. d [5-6]. e [^7].") == [1, 1, 3, 2, 4, 5, 6, 7]


def test_parse_ignores_code():
    text = "Set it [2].\n```yaml\nports: [1]\nlist: [3, 4]\n```\nInline `arr[5]` stays [6]."
    assert parse_citation_numbers(text) == [2, 6]


def test_renumber_by_first_use():
    ps = passages("https://x/A/", "https://x/B/", "https://x/C/", "https://x/D/")
    r = resolve_citations("X is true [3]. Y too [1][3]. Z [2].", ps)
    assert r.sources == ["https://x/C/", "https://x/A/", "https://x/B/"]
    assert r.answer == "X is true [1]. Y too [2][1]. Z [3]."
    # [1] in the answer is sources[0]
    assert [c.n for c in r.cited] == [1, 2, 3]
    assert [c.url for c in r.cited] == r.sources


def test_comma_groups_are_rendered_as_adjacent_markers():
    ps = passages("https://x/A/", "https://x/B/")
    r = resolve_citations("Both say so [2, 1].", ps)
    assert r.answer == "Both say so [1][2]."
    assert r.sources == ["https://x/B/", "https://x/A/"]


def test_duplicates_collapse_after_url_merging():
    ps = passages("https://x/A/", "https://x/A/", "https://x/B/")
    r = resolve_citations("One [1][2]. Two [2] [3]. Three [3][3].", ps)
    assert r.sources == ["https://x/A/", "https://x/B/"]
    assert r.answer == "One [1]. Two [1][2]. Three [2]."


def test_invalid_markers_are_stripped():
    ps = passages("https://x/A/", "https://x/B/")
    r = resolve_citations("Good [1]. Bad [12]. Zero [0]. Mixed [2, 9].", ps)
    assert r.answer == "Good [1]. Bad. Zero. Mixed [2]."
    assert r.sources == ["https://x/A/", "https://x/B/"]


def test_no_valid_citation_gives_empty_sources():
    ps = passages("https://x/A/")
    r = resolve_citations("Nothing cited here. Or wrongly [4].", ps)
    assert r.sources == []
    assert r.answer == "Nothing cited here. Or wrongly."


def test_sources_capped_at_five_and_overflow_markers_dropped():
    urls = [f"https://x/{i}/" for i in range(7)]
    ps = passages(*urls)
    r = resolve_citations(" ".join(f"S{i} [{i + 1}]." for i in range(7)), ps)
    assert r.sources == urls[:5]
    assert r.answer == "S0 [1]. S1 [2]. S2 [3]. S3 [4]. S4 [5]. S5. S6."


def test_code_blocks_are_never_rewritten():
    ps = passages("https://x/A/")
    text = "Use this [1]:\n```json\n{\"ports\": [8000]}\n```\nand `x[3]`."
    r = resolve_citations(text, ps)
    assert "```json\n{\"ports\": [8000]}\n```" in r.answer
    assert "`x[3]`" in r.answer
    assert r.sources == ["https://x/A/"]


def test_factcard_passage_contributes_its_cite_urls_as_adjacent_markers():
    urls = ["https://olake.io/docs/connectors/oracle/", "https://olake.io/docs/"]
    card = doc(0, urls[0], source_type="factcard", cite_urls=urls)
    mysql = "https://olake.io/docs/connectors/mysql/"
    ps = [Passage(n=1, chunk=card, source_url=urls[0], source_urls=tuple(urls)),
          Passage(n=2, chunk=doc(1, mysql), source_url=mysql)]
    r = resolve_citations("Oracle has no CDC [1]. MySQL has CDC [2]. Again [1].", ps)
    assert r.sources == [urls[0], urls[1], mysql]
    assert r.answer == "Oracle has no CDC [1][2]. MySQL has CDC [3]. Again [1][2]."
    det = citation_details(r.cited)
    assert [d["url"] for d in det] == [urls[0], urls[1], mysql + "#a"]  # cards link to the deep link
    assert [d["source_type"] for d in det] == ["factcard", "factcard", "docs"]


def test_factcard_sources_respect_the_cap():
    urls = [f"https://x/{i}/" for i in range(4)]
    card_urls = ("https://x/card-a/", "https://x/card-b/")
    card = doc(9, card_urls[0], source_type="factcard", cite_urls=list(card_urls))
    ps = [Passage(n=i + 1, chunk=doc(i, u), source_url=u) for i, u in enumerate(urls)]
    ps.append(Passage(n=5, chunk=card, source_url=card_urls[0], source_urls=card_urls))
    r = resolve_citations("a [1]. b [2]. c [3]. d [4]. card [5].", ps)
    assert r.sources == urls + [card_urls[0]]  # only one slot left for the card
    assert r.answer.endswith("card [5].")


def test_source_url_style_branch_vs_sha_for_repo_chunks():
    repo = {"source_type": "repo", "doc_url": "https://github.com/datazip-inc/olake/blob/master/protocol/root.go",
            "url": "https://github.com/datazip-inc/olake/blob/0123456/protocol/root.go#L20-L48"}
    assert source_url(repo, "branch") == repo["doc_url"]
    assert source_url(repo, "sha") == repo["url"]
    d = doc(1, "https://olake.io/docs/x/")
    assert source_url(d, "sha") == "https://olake.io/docs/x/"  # docs always cite doc_url


def test_trailing_sources_section_is_removed():
    text = "Answer [1].\n\n**Sources:**\n[1] T1 (https://x/A/)\n[2] T2 (https://x/B/)"
    assert strip_sources_section(text) == "Answer [1]."
    assert strip_sources_section("References:\n- [1]") == "References:\n- [1]"  # nothing before it: keep


def test_salvage_cuts_after_last_valid_citation_and_closes_fences():
    text = "First fact [1]. Second fact [2]. Then a cut-off sent"
    assert salvage_truncated(text, max_n=2) == "First fact [1]. Second fact [2]."
    fenced = "Run this [1]:\n```bash\ndocker compose up -d\n```\nAnd then [2]. ```yaml\nkey: va"
    out = salvage_truncated(fenced, max_n=2)
    assert out == "Run this [1]:\n```bash\ndocker compose up -d\n```\nAnd then [2]."
    assert salvage_truncated("No citations at all and cut", max_n=3) == ""
    assert salvage_truncated("Only invalid [9] cut", max_n=3) == ""


def test_citation_details_labels():
    repo = {"id": "olake/protocol/root.go#1", "source_type": "repo", "tier": 2, "repo": "olake",
            "commit": "0123456789abcdef", "lines": [20, 48], "title": "olake: protocol/root.go",
            "doc_url": "https://github.com/datazip-inc/olake/blob/master/protocol/root.go",
            "url": "https://github.com/datazip-inc/olake/blob/0123456789abcdef/protocol/root.go#L20-L48",
            "text": "olake: protocol/root.go | CLI flags\nflag body"}
    rel = {"id": "gh/olake/v0.12.1", "source_type": "release-gh", "tier": 1, "title": "olake v0.12.1",
           "doc_url": "https://github.com/datazip-inc/olake/releases/tag/v0.12.1",
           "url": "https://github.com/datazip-inc/olake/releases/tag/v0.12.1", "text": "olake v0.12.1\nnotes"}
    issue = {"id": "issue/olake/867", "source_type": "issue", "tier": 2, "title": "known issue #867",
             "doc_url": "https://github.com/datazip-inc/olake/issues/867",
             "url": "https://github.com/datazip-inc/olake/issues/867", "text": "known issue #867\nbody"}
    out = {"id": "outside/iceberg", "source_type": "outside", "tier": 4, "title": "Iceberg maintenance",
           "doc_url": "https://iceberg.apache.org/docs/latest/maintenance/",
           "url": "https://iceberg.apache.org/docs/latest/maintenance/", "text": "Iceberg maintenance\nexpire"}
    d = doc(5, "https://olake.io/docs/x/", section_path=["REST Catalog", "Configuration"],
            text="REST | olake > REST Catalog > Configuration\n" + "word " * 100)
    ps = [Passage(n=i + 1, chunk=c, source_url=c["doc_url"]) for i, c in enumerate([repo, rel, issue, out, d])]
    r = resolve_citations("a [1]. b [2]. c [3]. d [4]. e [5].", ps)
    det = citation_details(r.cited)
    assert [x["n"] for x in det] == [1, 2, 3, 4, 5]
    assert det[0]["label"] == "olake@0123456 · protocol/root.go L20-L48"
    assert det[0]["url"] == repo["url"]  # the UI card links to the SHA permalink
    assert det[1]["label"] == "v0.12.1"
    assert det[2]["label"] == "issue #867"
    assert det[3]["label"] == "outside OLake docs"
    assert det[4]["label"] == "REST Catalog › Configuration"
    assert det[4]["url"] == "https://olake.io/docs/x/#a"
    assert det[4]["snippet"].startswith("word word")
    assert len(det[4]["snippet"]) <= 241
    assert set(det[0]) == {"n", "url", "label", "title", "source_type", "snippet"}


def test_snippets_are_plain_text_without_markdown_syntax():
    text = ("Alerts | olake > Alerts\n\n<!-- tabs:start -->\n## Alert Message Format\n\n"
            "When a job fails, OLake sends a **POST** request to your [webhook](https://x.example/) URL:\n\n"
            "```json\n{\"a\": 1}\n```\n\n| Field | Meaning |\n|---|---|\n| `job_id` | the job |\n\n- one\n> quoted")
    c = doc(0, "https://olake.io/docs/a/", text=text)
    snip = citation_details(resolve_citations("x [1].", [Passage(1, c, c["doc_url"])]).cited)[0]["snippet"]
    assert snip == ('Alert Message Format When a job fails, OLake sends a POST request to your webhook URL: '
                    '{"a": 1} Field Meaning job_id the job one quoted')


def test_docs_label_skips_the_page_title_and_site_suffix():
    def label(title, path):
        c = doc(0, "https://olake.io/docs/a/", title=title, section_path=path)
        return citation_details(resolve_citations("x [1].", [Passage(1, c, c["doc_url"])]).cited)[0]["label"]

    assert label("Alerts and Notifications - Move and Manage Data",
                 ["Alerts and Notifications", "Alert Message Format"]) == "Alert Message Format"
    assert label("Alerts and Notifications - Move and Manage Data", ["Alerts and Notifications"]) == ""
    assert label("REST Catalog | OLake", ["Configuration", "Auth"]) == "Configuration › Auth"
