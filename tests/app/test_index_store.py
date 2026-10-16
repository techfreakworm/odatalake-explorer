"""Loading contract I1: data/index/CURRENT -> chunks.jsonl + embeddings.npy + manifest.json, hot-swappable."""

import json
import shutil

import numpy as np
import pytest

from app.index_store import IndexHolder, IndexLoadError, index_info, load_snapshot, read_current
from tests.app.fakes import VERSION, build_fixture_index


def test_load_from_current(snapshot, index_dir):
    assert snapshot.version == VERSION
    assert read_current(index_dir) == VERSION
    assert len(snapshot.chunks) == 25
    assert snapshot.embeddings.shape == (25, 512)
    assert snapshot.embeddings.dtype == np.float32
    assert not snapshot.embeddings.flags.writeable  # shared by concurrent requests: read-only
    assert snapshot.embed_model == "test/hash-embedder"
    assert snapshot.query_prefix == ""


def test_facts_line_from_manifest(snapshot):
    assert snapshot.facts_line == ("Docs indexed 2026-10-17; latest releases: olake v0.12.1 (2026-10-15), "
                                   "olake-ui v0.7.1 (2026-10-15)")


def test_facts_line_falls_back_to_release_gh_chunks(tmp_path):
    d = build_fixture_index(tmp_path)
    mpath = d / VERSION / "manifest.json"
    m = json.loads(mpath.read_text())
    del m["releases"]
    mpath.write_text(json.dumps(m))
    snap = load_snapshot(d, blog=False)
    assert "olake v0.12.1 (2026-10-15)" in snap.facts_line
    assert "olake-ui v0.7.1 (2026-10-15)" in snap.facts_line


def test_index_info_for_healthz(snapshot):
    info = index_info(snapshot)
    assert info == {
        "version": VERSION,
        "built_at": "2026-10-17T00:00:00Z",
        "pages": 19,
        "chunks": 25,
        "docs_lastmod_max": "2026-10-09",
        "repos": {"olake": "0123456", "olake-helm": "89abcde"},
    }


def test_index_dir_may_point_at_a_version_dir(index_dir):
    snap = load_snapshot(index_dir / VERSION, blog=False)
    assert snap.version == VERSION


def test_missing_current_is_a_clear_error(tmp_path):
    with pytest.raises(IndexLoadError, match="CURRENT"):
        load_snapshot(tmp_path, blog=False)


def test_row_count_mismatch_is_an_error(tmp_path):
    d = build_fixture_index(tmp_path)
    emb = np.load(d / VERSION / "embeddings.npy")
    np.save(d / VERSION / "embeddings.npy", emb[:-1])
    with pytest.raises(IndexLoadError, match="rows"):
        load_snapshot(d, blog=False)


def test_bm25_only_index_without_embeddings_loads(tmp_path):
    d = build_fixture_index(tmp_path, with_embeddings=False)
    snap = load_snapshot(d, blog=False, require_embeddings=False)
    assert snap.embeddings is None
    with pytest.raises(IndexLoadError, match="embeddings"):
        load_snapshot(d, blog=False, require_embeddings=True)


def test_blog_chunks_are_ineligible_when_blog_off(index_dir):
    off = load_snapshot(index_dir, blog=False)
    on = load_snapshot(index_dir, blog=True)
    i = next(i for i, c in enumerate(off.chunks) if c["source_type"] == "blog")
    assert not off.ranking.eligible[i]
    assert on.ranking.eligible[i]
    assert on.ranking.static_weight[i] == pytest.approx(0.5)


def test_release_notes_older_than_the_latest_two_minors_are_demoted(snapshot):
    w = {c["doc_url"]: snapshot.ranking.static_weight[i] for i, c in enumerate(snapshot.chunks)}
    assert w["https://olake.io/docs/release/ingestion/v0.12.0/"] == pytest.approx(1.0)
    assert w["https://olake.io/docs/release/ingestion/v0.11.0/"] == pytest.approx(1.0)
    assert w["https://olake.io/docs/release/ingestion/v0.9.0/"] == pytest.approx(0.3)
    assert w["https://github.com/datazip-inc/olake/releases/tag/v0.12.1"] == pytest.approx(1.0)
    assert w["https://olake.io/docs/connectors/postgres/"] == pytest.approx(1.0)


def test_holder_swap_keeps_old_reference_valid(index_dir, tmp_path):
    holder = IndexHolder()
    assert holder.current is None
    first = load_snapshot(index_dir, blog=False)
    holder.swap(first)
    in_flight = holder.current
    d2 = tmp_path / "idx2"
    shutil.copytree(index_dir, d2)
    (d2 / VERSION).rename(d2 / "20261017T0100Z")
    m = json.loads((d2 / "20261017T0100Z" / "manifest.json").read_text())
    m["version"] = "20261017T0100Z"
    (d2 / "20261017T0100Z" / "manifest.json").write_text(json.dumps(m))
    (d2 / "CURRENT").write_text("20261017T0100Z")
    old = holder.swap(load_snapshot(d2, blog=False))
    assert old is first and in_flight is first
    assert holder.current.version == "20261017T0100Z"
    assert len(in_flight.chunks) == 25  # the in-flight request still sees a complete index


def test_release_series_are_grouped_by_repo_and_tag_prefix():
    from app.retrieval import old_release_mask

    def gh(repo, tag):
        return {"source_type": "release-gh", "doc_url": f"https://github.com/datazip-inc/{repo}/releases/tag/{tag}"}

    chunks = [gh("olake-helm", "v0.4.0"), gh("olake-helm", "v0.3.11"), gh("olake-helm", "v0.2.0"),
              gh("olake-helm", "olake-0.0.30"), gh("olake-helm", "olake-0.0.24"),
              {"source_type": "release", "doc_url": "https://olake.io/docs/release/ingestion/v0.2.2-v0.2.4/"},
              {"source_type": "release", "doc_url": "https://olake.io/docs/release/ingestion/v0.12.0/"},
              {"source_type": "release", "doc_url": "https://olake.io/docs/release/ingestion/v0.11.0/"},
              {"source_type": "release", "doc_url": "https://olake.io/docs/release/ingestion/28-04-2025/"},
              {"source_type": "release", "doc_url": "https://olake.io/docs/fusion/release/maintenance/v0.1.0/"}]
    # the chart series (olake-0.0.x) has one minor, so none of it is demoted; v0.2.0 is older than v0.4 and v0.3;
    # Fusion's own notes (v0.1.0) are compared with Fusion's, never with Go's v0.12
    assert old_release_mask(chunks) == [False, False, True, False, False, True, False, False, False, False]
