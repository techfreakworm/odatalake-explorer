"""Hybrid retrieval: BM25 + dense, RRF k=60, the CLAUDE.md "Corpus" ranking rules, per-page cap, optional rerank."""

import numpy as np
import pytest

from app.index_store import load_snapshot
from app.retrieval import (
    RetrievalConfig,
    detect_connectors,
    expand_query,
    extract_identifiers,
    names_fusion,
    per_page_cap,
    retrieve,
    rrf,
)

HYBRID = RetrievalConfig(mode="hybrid", gate_threshold=0.05)
BM25 = RetrievalConfig(mode="bm25", gate_threshold=0.05)


def ids(result):
    return [h.chunk["id"] for h in result.hits]


def test_rrf_math():
    fused = dict(rrf([(1, 9.0), (2, 8.0)], [(2, 0.9), (3, 0.8)], k=60))
    assert fused[2] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1] == pytest.approx(1 / 61)
    assert fused[3] == pytest.approx(1 / 62)
    assert [i for i, _ in rrf([(1, 9.0), (2, 8.0)], [(2, 0.9), (3, 0.8)], k=60)] == [2, 1, 3]


def test_per_page_cap_keeps_order_and_limits_each_page():
    pages = ["A", "A", "B", "A", "A", "C", "B"]
    items = list(range(len(pages)))
    out = per_page_cap(items, key=lambda i: pages[i], per_page=3, k=5)
    assert out == [0, 1, 2, 3, 5]
    assert per_page_cap(items, key=lambda i: pages[i], per_page=1, k=10) == [0, 2, 5]


def test_hybrid_caps_three_chunks_per_page(snapshot, embedder):
    q = "postgres wal_level replication slot publication jsonb troubleshooting configuration max_threads"
    res = retrieve(snapshot, q, embedder=embedder, cfg=HYBRID)
    # a fact card is its own "page" for the cap, even when its doc_url is one of the pages it cites
    urls = [h.chunk["doc_url"] for h in res.hits if h.chunk["source_type"] != "factcard"]
    assert urls.count("https://olake.io/docs/connectors/postgres/") == 3
    assert len([h for h in res.ranked if h.chunk["doc_url"] == "https://olake.io/docs/connectors/postgres/"
                and h.chunk["source_type"] == "docs"]) == 5
    assert len(res.hits) <= 10


def test_gate_score_is_the_highest_dense_cosine(snapshot, embedder):
    q = "How do I install OLake UI with docker compose?"
    res = retrieve(snapshot, q, embedder=embedder, cfg=HYBRID)
    sims = snapshot.embeddings @ embedder.embed_query(q)
    sims[~snapshot.ranking.eligible] = -1
    assert res.gate_score == pytest.approx(float(sims.max()))
    assert res.hits[0].chunk["doc_url"] == "https://olake.io/docs/install/olake-ui/"


def test_bm25_mode_works_without_an_embedder(snapshot):
    res = retrieve(snapshot, "How do I install OLake UI with docker compose?", embedder=None, cfg=BM25)
    assert res.gate_score is None
    assert res.hits and res.hits[0].chunk["doc_url"] == "https://olake.io/docs/install/olake-ui/"
    assert all(h.dense is None for h in res.hits)


def test_bm25_mode_works_on_an_index_without_embeddings(tmp_path):
    from tests.app.fakes import build_fixture_index

    snap = load_snapshot(build_fixture_index(tmp_path, with_embeddings=False), blog=False, require_embeddings=False)
    res = retrieve(snap, "mysql binlog_row_metadata", embedder=None, cfg=BM25)
    assert res.hits[0].chunk["doc_url"] == "https://olake.io/docs/connectors/mysql/"


def test_unknown_words_return_nothing_in_bm25_mode(snapshot):
    res = retrieve(snapshot, "zzzz qqqq", embedder=None, cfg=BM25)
    assert res.hits == []


@pytest.mark.parametrize("q", [
    "iceberg expire snapshots orphan files compaction maintenance",
    "what does compaction do to snapshots",
    "why iceberg time travel snapshots",
])
def test_outside_and_blog_never_outrank_a_tier1_chunk_that_passes_the_gate(index_dir, embedder, q):
    snap = load_snapshot(index_dir, blog=True)
    res = retrieve(snap, q, embedder=embedder, cfg=HYBRID)
    ranked = res.ranked
    t1_ok = [pos for pos, h in enumerate(ranked) if h.chunk["tier"] == 1 and h.dense >= HYBRID.gate_threshold]
    low = [pos for pos, h in enumerate(ranked) if h.chunk["tier"] in (3, 4)]
    assert t1_ok, "the query should reach some tier-1 chunk"
    assert all(p > max(t1_ok) for p in low)


def test_blog_excluded_when_off(snapshot, embedder):
    res = retrieve(snapshot, "why iceberg time travel snapshots", embedder=embedder, cfg=HYBRID)
    assert all(h.chunk["source_type"] != "blog" for h in res.ranked)


def test_connector_detection():
    assert detect_connectors("CDC on MariaDB 10.6") == {"mysql"}
    assert detect_connectors("SQL Server on RDS and Postgres") == {"mssql", "postgres"}
    assert detect_connectors("supabase connection pooler") == {"postgres"}
    assert detect_connectors("our MSK cluster TLS listener") == {"kafka"}
    assert detect_connectors("S3 source: bucket of csv.gz files") == {"s3"}
    assert detect_connectors("write iceberg on s3 with glue") == set()
    assert detect_connectors("mongo standalone node oplog") == {"mongodb"}


def test_connector_page_named_in_the_question_is_boosted(snapshot, embedder):
    res = retrieve(snapshot, "mariadb binlog settings", embedder=embedder, cfg=HYBRID)
    assert res.hits[0].chunk["doc_url"] == "https://olake.io/docs/connectors/mysql/"
    assert "mysql" in res.info["connectors"]


def test_synonym_expansion():
    q = expand_query("Strict CDC on MariaDB with OLake Go and the Maintenance tab")
    for term in ("strict_cdc", "MySQL", "OLake", "Fusion"):
        assert term in q
    assert expand_query("plain question") == "plain question"


def test_identifier_extraction():
    found = extract_identifiers("Use --destination-database-prefix, initial_wait_time, global.logFileStorageMode, "
                                "jsonb and `LSN not updated after 5 minutes` with ORA-01031 and SQL0668N")
    for ident in ("--destination-database-prefix", "initial_wait_time", "global.logfilestoragemode", "jsonb",
                  "lsn not updated after 5 minutes", "ora-01031", "sql0668n"):
        assert ident in found
    assert extract_identifiers("how do I install olake") == []


def test_exact_match_boost_finds_identifiers_defined_only_in_code(snapshot):
    q = "Can I change the database name prefix from the CLI with --destination-database-prefix?"
    res = retrieve(snapshot, q, embedder=None, cfg=BM25)
    assert "olake/protocol/root.go#1" in ids(res)[:3]


def test_twins_prefer_fusion_when_the_question_names_fusion_or_compaction(snapshot, embedder):
    assert names_fusion("compaction quickstart") and names_fusion("OLake Fusion setup")
    assert not names_fusion("olake quickstart")

    def order(q):
        r = [h.chunk["doc_url"] for h in retrieve(snapshot, q, embedder=embedder, cfg=HYBRID).ranked]
        return (r.index("https://olake.io/docs/getting-started/quickstart/"),
                r.index("https://olake.io/docs/fusion/getting-started/quickstart/"))

    go, fusion = order("compaction quickstart: create a source and a job and run the first sync")
    assert fusion < go
    go, fusion = order("quickstart: create a source and a job and run the first sync")
    assert go < fusion


def test_factcard_cites_the_page_most_relevant_to_the_question(snapshot, embedder):
    res = retrieve(snapshot, "Does OLake support Oracle CDC?", embedder=embedder, cfg=HYBRID)
    card = next(h for h in res.hits if h.chunk["source_type"] == "factcard")
    assert card.source_url == "https://olake.io/docs/connectors/oracle/"  # the connector named in the question
    assert card.source_urls[0] == card.source_url and len(card.source_urls) == 2  # at most 2 per card
    assert set(card.source_urls) <= set(card.chunk["cite_urls"])


def test_repo_source_url_follows_source_url_style(snapshot):
    q = "--destination-database-prefix flag"
    sha = retrieve(snapshot, q, embedder=None, cfg=RetrievalConfig(mode="bm25", source_url_style="sha"))
    branch = retrieve(snapshot, q, embedder=None, cfg=RetrievalConfig(mode="bm25", source_url_style="branch"))
    hs = next(h for h in sha.hits if h.chunk["source_type"] == "repo")
    hb = next(h for h in branch.hits if h.chunk["source_type"] == "repo")
    assert hs.source_url.startswith("https://github.com/datazip-inc/olake/blob/0123456789abcdef")
    assert hb.source_url == "https://github.com/datazip-inc/olake/blob/master/protocol/root.go"


class PreferIdReranker:
    """Scores one chunk id highest, everything else by reverse input order."""

    def __init__(self, favourite):
        self.favourite = favourite
        self.seen = 0

    def rerank(self, query, chunks):
        self.seen = len(chunks)
        return [10.0 if c["id"] == self.favourite else -float(i) for i, c in enumerate(chunks)]


def test_rerank_reorders_the_fused_top20_before_the_page_cap(snapshot, embedder):
    q = "How do I install OLake UI with docker compose and disable telemetry?"
    base = retrieve(snapshot, q, embedder=embedder, cfg=HYBRID)
    target = base.ranked[4].chunk["id"]
    rr = PreferIdReranker(target)
    res = retrieve(snapshot, q, embedder=embedder, reranker=rr, cfg=HYBRID)
    assert ids(res)[0] == target
    assert rr.seen == min(20, len(base.ranked))
    assert "rerank" in res.timings_ms


def test_results_are_deterministic(snapshot, embedder):
    q = "postgres cdc replication slot"
    a = retrieve(snapshot, q, embedder=embedder, cfg=HYBRID)
    b = retrieve(snapshot, q, embedder=embedder, cfg=HYBRID)
    assert ids(a) == ids(b)
    assert np.isfinite([h.score for h in a.hits]).all()
