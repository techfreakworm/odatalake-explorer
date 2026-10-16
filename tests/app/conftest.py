from pathlib import Path

import pytest

from tests.app.fakes import HashEmbedder, build_fixture_index


@pytest.fixture(scope="session")
def index_dir(tmp_path_factory) -> Path:
    """The tiny fixture index (tests/app/fixtures/index_src) built with the hashing embedder."""
    return build_fixture_index(tmp_path_factory.mktemp("index"))


@pytest.fixture(scope="session")
def snapshot(index_dir):
    from app.index_store import load_snapshot

    return load_snapshot(index_dir, blog=False)


@pytest.fixture
def embedder():
    return HashEmbedder()
