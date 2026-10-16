"""Freshness: the in-app poller calls index.refresh.refresh_once() and the runtime hot-swaps a new CURRENT."""

import json
import shutil
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.refresh import RefreshPoller
from tests.app.fakes import VERSION, FakeLLM, HashEmbedder, build_fixture_index

NEW = "20261017T0100Z"


def publish_new_version(index_dir, version=NEW):
    """What ingest's refresh does: write a new version dir, then swap CURRENT."""
    shutil.copytree(index_dir / VERSION, index_dir / version)
    m = json.loads((index_dir / version / "manifest.json").read_text())
    m["version"] = version
    (index_dir / version / "manifest.json").write_text(json.dumps(m))
    tmp = index_dir / "CURRENT.tmp"
    tmp.write_text(version)
    tmp.replace(index_dir / "CURRENT")


def poller(index_dir, refresh_fn, current=VERSION, reloads=None):
    reloads = [] if reloads is None else reloads
    return RefreshPoller(interval_min=1, index_dir=index_dir, refresh_fn=refresh_fn,
                         current_version=lambda: current, reload=lambda: reloads.append(True)), reloads


def test_tick_runs_refresh_and_reloads_when_current_changes(tmp_path):
    d = build_fixture_index(tmp_path)
    calls = []

    def refresh_once(index_dir):
        calls.append(index_dir)
        publish_new_version(index_dir)
        return {"changed": True, "version": NEW}

    p, reloads = poller(d, refresh_once)
    p.tick()
    assert calls == [d] and reloads == [True]


def test_tick_without_a_new_version_does_not_reload(tmp_path):
    d = build_fixture_index(tmp_path)
    p, reloads = poller(d, lambda index_dir: {"changed": False})
    p.tick()
    assert reloads == []


def test_refresh_failure_is_survived_and_current_is_still_checked(tmp_path, capsys):
    d = build_fixture_index(tmp_path)
    publish_new_version(d)  # e.g. a manual `python -m index.refresh` ran meanwhile

    def broken(index_dir):
        raise ConnectionError("sitemap fetch failed")

    p, reloads = poller(d, broken)
    p.tick()
    assert reloads == [True]
    assert "refresh_failed" in capsys.readouterr().out


def test_refresh_fn_without_parameters_and_no_refresh_fn(tmp_path):
    d = build_fixture_index(tmp_path)
    called = []
    p, _ = poller(d, lambda: called.append(True))
    p.tick()
    assert called == [True]
    p2, reloads = poller(d, None)
    p2.tick()  # only watches CURRENT
    assert reloads == []


def test_runtime_hot_swaps_the_index(tmp_path):
    d = build_fixture_index(tmp_path)
    llm = FakeLLM("Run the compose one-liner [1].")
    app = create_app(Settings(index_dir=d, abstain_threshold=0.18), llm=llm,
                     embedder_factory=lambda m, threads, cache_dir: HashEmbedder())
    with TestClient(app) as c:
        end = time.time() + 5
        while c.get("/readyz").status_code != 200 and time.time() < end:
            time.sleep(0.02)
        rt = app.state.rt
        q = {"question": "How do I install OLake UI with docker compose?"}
        assert c.post("/ask", json=q).status_code == 200
        in_flight = rt.holder.current
        publish_new_version(d)
        rt.load()
        assert c.get("/healthz").json()["index"]["version"] == NEW
        assert in_flight.version == VERSION and len(in_flight.chunks) == 25
        r = c.post("/ask", json=q)  # the cache is keyed by index version: a new version is a miss
        assert r.headers["x-ask-cache"] == "miss" and len(llm.calls) == 2
        rt.load()  # same version again: no reload
        assert rt.holder.current.version == NEW


def test_poller_thread_runs_and_stops(tmp_path):
    d = build_fixture_index(tmp_path)
    calls = []
    p = RefreshPoller(interval_min=0.001, index_dir=d, refresh_fn=lambda index_dir: calls.append(1),
                      current_version=lambda: VERSION, reload=lambda: None)
    p.start()
    end = time.time() + 3
    while not calls and time.time() < end:
        time.sleep(0.02)
    p.stop()
    assert calls
