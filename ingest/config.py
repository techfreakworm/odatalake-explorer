"""Corpus definition and cache locations for the index builder.

Everything that decides WHAT goes into the index lives here (plan Appendix A, "Corpus"), so a
change of scope is a one-line edit: the docs denylist, the repo Tier A allowlist, the curated
issues, the curated outside pages and the FAQ pages.

Paths: the cache defaults to `.cache/` at the repo root (gitignored). `ASK_OLAKE_CACHE`,
`FASTEMBED_CACHE_PATH` and `TIKTOKEN_CACHE_DIR` override it; a relative value is resolved
against the repo root, so no absolute personal path ever has to appear in a tracked file.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(value: str | os.PathLike) -> Path:
    """An env-provided path: absolute as given, relative to the repo root otherwise."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


CACHE_DIR = repo_path(os.environ.get("ASK_OLAKE_CACHE") or ".cache")
HTML_DIR = CACHE_DIR / "html"            # raw fetched HTML + response metadata (untrusted data)
REPOS_DIR = CACHE_DIR / "repos"          # shallow clones (untrusted data, never executed)
GITHUB_DIR = CACHE_DIR / "github"        # cached GitHub REST responses
EMBED_CACHE_DIR = CACHE_DIR / "embeddings"  # (model, chunk hash) -> vector, survives rebuilds
MODELS_DIR = repo_path(os.environ.get("FASTEMBED_CACHE_PATH") or CACHE_DIR / "models")
TIKTOKEN_DIR = repo_path(os.environ.get("TIKTOKEN_CACHE_DIR") or CACHE_DIR / "tiktoken")
REFRESH_STATE = CACHE_DIR / "refresh_state.json"  # poll state (sitemap ETag, tag sets); never content

# fastembed and tiktoken read these when they first load a model or an encoding
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(MODELS_DIR))
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(TIKTOKEN_DIR))

# ----------------------------------------------------------------------------- HTTP politeness
USER_AGENT = ("Mozilla/5.0 (compatible; ask-olake-indexer/0.1; cited docs assistant index builder; "
              "polite: max 4 concurrent requests)")
MAX_CONCURRENCY = 4
HTTP_TIMEOUT_S = 20.0
HTTP_RETRIES = 2

# ----------------------------------------------------------------------------- docs
SITE = "https://olake.io"
SITEMAP_URL = "https://olake.io/sitemap.xml"
DOCS_PREFIX = "https://olake.io/docs/"
# Pages under these prefixes are release notes: source_type "release" instead of "docs".
RELEASE_PREFIXES = ("https://olake.io/docs/release/", "https://olake.io/docs/fusion/release/")
FUSION_PREFIX = "https://olake.io/docs/fusion/"

# Stub or stale pages (decision D12). Excluded from the index and logged; delete a line to reverse.
DENYLIST: tuple[str, ...] = (
    "/docs/connectors/overview/",
    "/docs/connectors/kafka/overview/",
    "/docs/tutorials/enable-oplogs/",
    "/docs/archive/kubernetes/",
    "/docs/core/configs/catalog/",
    "/docs/core/configs/state/",
    "/docs/core/architecture/",
    "/docs/fusion/core/architecture/",
    "/docs/fusion/community/issues-and-prs/",
    "/docs/fusion/community/code-of-conduct/",
    "/docs/fusion/community/contributing/",
    "/docs/fusion/community/channels/",
    "/docs/fusion/core/terminologies/",
    "/docs/fusion/core/compatibility/query-engines/",
    "/docs/core/configs/source/",
    "/docs/core/configs/writer/",
)

# ----------------------------------------------------------------------------- product FAQs
FAQ_PAGES: tuple[tuple[str, str], ...] = (
    ("https://olake.io/olake-go/", "OLake Go product FAQ"),
    ("https://olake.io/olake-fusion/", "OLake Fusion product FAQ"),
)

# ----------------------------------------------------------------------------- GitHub
GITHUB_ORG = "datazip-inc"
REPOS: tuple[str, ...] = ("olake", "olake-ui", "olake-helm", "olake-fusion")
RELEASES_PER_REPO = 10

# Tier A allowlist (plan Appendix A). fnmatch patterns on repo-relative paths.
# Never: tests, olake-fusion Java/Scala, site/ and docs/ (upstream Amoro), helm templates other
# than NOTES.txt, lockfiles, images, .github, the stale root docker-compose.yml in olake.
REPO_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "olake": (
        "README.md",
        "drivers/*/README.md",
        "destination/iceberg/README.md",
        "protocol/root.go",
        "drivers/*/resources/spec.json",
        "destination/iceberg/resources/spec.json",
        "destination/parquet/resources/spec.json",
    ),
    "olake-ui": ("README.md", "docker-compose-v1.yml", "server/conf/app.yaml"),
    "olake-helm": (
        "README.md",
        "helm/olake/README.md",
        "helm/olake/UNINSTALL_GUIDE.md",
        "helm/olake/values.yaml",
        "helm/olake/Chart.yaml",
        "helm/olake/templates/NOTES.txt",
    ),
    "olake-fusion": ("README.md", "CLAUDE.md"),
}
REPO_DENY: tuple[str, ...] = (
    ".github/*", "*/test/*", "*/tests/*", "*/testdata/*", "*_test.go", "*/vendor/*", "*/node_modules/*",
    "*.lock", "*-lock.json", "*-lock.yaml", "go.sum", "*.png", "*.svg", "*.jpg", "docs/*", "site/*",
)
# olake-fusion CLAUDE.md: keep only "## 1." .. "## 4." (other lines blanked, so line anchors stay valid)
FUSION_CLAUDE_SECTIONS = (1, 4)

# Curated issues (decision D5): one chunk each, cited as the issue or comment permalink.
CURATED_ISSUES: tuple[str, ...] = (
    "https://github.com/datazip-inc/olake/issues/811#issuecomment-3895500238",
    "https://github.com/datazip-inc/olake/issues/867",
    "https://github.com/datazip-inc/olake/issues/877",
    "https://github.com/datazip-inc/olake/issues/955",
    "https://github.com/datazip-inc/olake/issues/1080",
    "https://github.com/datazip-inc/olake/issues/1292",
    "https://github.com/datazip-inc/olake-helm/issues/100",
    "https://github.com/datazip-inc/olake-fusion/issues/23",
    "https://github.com/datazip-inc/olake-fusion/issues/29",
    "https://github.com/datazip-inc/olake-ui/issues/93",
)

# ----------------------------------------------------------------------------- outside pages (tier 4)
OUTSIDE_LABEL = "outside OLake docs"
AMORO_LABEL = "upstream Amoro; Fusion may differ"
OUTSIDE_PAGES: tuple[tuple[str, str], ...] = (
    ("https://iceberg.apache.org/docs/latest/maintenance/", OUTSIDE_LABEL),
    ("https://iceberg.apache.org/docs/latest/spark-procedures/", OUTSIDE_LABEL),
    ("https://iceberg.apache.org/spec/", OUTSIDE_LABEL),
    ("https://amoro.apache.org/docs/latest/self-optimizing/", AMORO_LABEL),
    ("https://amoro.apache.org/docs/latest/configurations/", AMORO_LABEL),
    ("https://www.postgresql.org/docs/current/runtime-config-replication.html", OUTSIDE_LABEL),
    ("https://www.postgresql.org/docs/current/logicaldecoding-explanation.html", OUTSIDE_LABEL),
    ("https://www.postgresql.org/docs/current/sql-altertable.html", OUTSIDE_LABEL),
    ("https://dev.mysql.com/doc/refman/8.4/en/replication-options-binary-log.html", OUTSIDE_LABEL),
    ("https://www.mongodb.com/docs/manual/core/replica-set-oplog/", OUTSIDE_LABEL),
    ("https://www.mongodb.com/docs/manual/changeStreams/", OUTSIDE_LABEL),
    ("https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server",
     OUTSIDE_LABEL),
    ("https://kafka.apache.org/43/configuration/consumer-configs/", OUTSIDE_LABEL),
    ("https://kafka.apache.org/43/operations/basic-kafka-operations/", OUTSIDE_LABEL),
    ("https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html", OUTSIDE_LABEL),
    ("https://docs.databricks.com/aws/en/external-access/iceberg", OUTSIDE_LABEL),
    ("https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html", OUTSIDE_LABEL),
    ("https://docs.lakekeeper.io/", OUTSIDE_LABEL),
    ("https://polaris.apache.org/", OUTSIDE_LABEL),
    ("https://projectnessie.org/", OUTSIDE_LABEL),
    ("https://cloud.google.com/bigquery/docs/blms-rest-catalog", OUTSIDE_LABEL),
    ("https://docs.snowflake.com/en/user-guide/tables-iceberg-query-using-external-query-engine-snowflake-horizon",
     OUTSIDE_LABEL),
    ("https://docs.temporal.io/", OUTSIDE_LABEL),
)

# ----------------------------------------------------------------------------- tiers
TIERS: dict[str, int] = {
    "docs": 1, "release": 1, "release-gh": 1, "faq": 1, "factcard": 1,
    "repo": 2, "issue": 2,
    "blog": 3,
    "outside": 4,
}
