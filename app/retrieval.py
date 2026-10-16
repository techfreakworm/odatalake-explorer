"""Hybrid retrieval (ported from poc/retrieval/index.py) plus the CLAUDE.md "Corpus" ranking rules.

BM25 (bm25s + Snowball stemmer) and dense cosine over the numpy matrix, each side's top 50 fused with reciprocal rank
fusion (k=60). Then: tier weights (tier 3-4 never outrank a tier-1 chunk that passes the gate), release notes older
than the latest two minors x0.3, the connector page named in the question x1.6, product=fusion preferred among
near-duplicate twins when the question names Fusion or compaction (else product=go), synonym expansion and an
exact-match boost for identifiers in the BM25 query. Optional rerank of the fused top 20, then max 3 chunks per page
and the top 10 go to the LLM. RETRIEVAL_MODE=bm25 uses the same chunks and rules without the dense side.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import numpy as np

from app.citations import source_url as plain_source_url

RRF_K = 60
CONNECTOR_BOOST = 1.6
OLD_RELEASE_WEIGHT = 0.3
BLOG_WEIGHT = 0.5  # decision D4: the blog is opt-in only, at a x0.5 rank weight
IDENT_BOOST_STEP = 0.5  # BM25 score x(1 + 0.5 per identifier found in the chunk), capped below
IDENT_BOOST_MAX = 2.0
TWIN_COSINE = 0.95  # near-duplicate go/fusion twin pages (install, quickstart, ...)
TWIN_DEMOTE = 0.5
MAX_CARD_SOURCES = 2  # cite_urls one cited fact card may add to sources

TIER_BY_TYPE = {"docs": 1, "release": 1, "release-gh": 1, "faq": 1, "factcard": 1, "repo": 2, "issue": 2,
                "blog": 3, "outside": 4}

_CONNECTOR_PATTERNS = {
    "postgres": r"\b(?:postgres(?:ql)?|psql|pg ?\d{2}|supabase)\b",
    "mysql": r"\b(?:mysql|mariadb)\b",
    "mongodb": r"\bmongo(?:db)?\b",
    "oracle": r"\boracle\b",
    "mssql": r"\b(?:mssql|sql ?server)\b",
    "db2": r"\bdb2\b",
    "kafka": r"\b(?:kafka|msk)\b",
    # S3 is also a destination; only an explicit S3 *source* names the connector page
    "s3": r"\bs3 source\b|\bsource:? (?:aws |amazon )?s3\b|\bfrom (?:an? |aws |amazon )?s3\b",
}
_CONNECTOR_RES = {k: re.compile(v, re.I) for k, v in _CONNECTOR_PATTERNS.items()}
_DOCS_CONNECTOR_RE = re.compile(r"://olake\.io/docs/connectors/([a-z0-9]+)/")
_REPO_DRIVER_RE = re.compile(r"github\.com/datazip-inc/olake/blob/[^/]+/drivers/([a-z0-9]+)/")
_FUSION_RE = re.compile(r"\bfusion\b|\bcompact(?:ion|ions|ing|ed)?\b|\bmaintenance\b", re.I)

# query expansion (CLAUDE.md "Synonyms"): OLake = OLake Go = OLake ingestion; Fusion = OLake Fusion = Maintenance;
# Strict CDC = strict_cdc = CDC Only; MariaDB -> MySQL (the MySQL connector covers MariaDB)
_SYNONYMS = [
    (re.compile(r"\bolake[ -](?:go|ingestion)\b", re.I), "OLake"),
    (re.compile(r"\bfusion\b", re.I), "Fusion maintenance"),
    (re.compile(r"\bmaintenance\b", re.I), "Fusion"),
    (re.compile(r"\bstrict[ _-]?cdc\b|\bcdc[ _-]only\b", re.I), "strict_cdc strict CDC only"),
    (re.compile(r"\bmariadb\b", re.I), "MySQL"),
]

_TYPE_NAMES = {
    "jsonb", "bytea", "timestamptz", "timetz", "numeric", "decimal", "bigint", "smallint", "tinyint", "mediumint",
    "varchar", "varbinary", "uuid", "hstore", "inet", "cidr", "macaddr", "interval", "money", "enum", "objectid",
    "decimal128", "int32", "int64", "float32", "float64", "datetime", "geometry", "geography", "citext", "tsvector",
    "xml", "bson",
}
_IDENT_RES = [
    re.compile(r"`([^`\n]{3,80})`"),  # anything quoted as code in the question
    re.compile(r"(?<![\w-])(--[a-zA-Z0-9][a-zA-Z0-9-]{2,})"),  # CLI flags
    re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*\.[a-z]+[A-Z][A-Za-z0-9]*)\b"),  # a.b.camelCase
    re.compile(r"\b([A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)\b"),  # snake_case and UPPER_SNAKE keys
    re.compile(r"\b([a-z]+[A-Z][A-Za-z0-9]*)\b"),  # camelCase keys
    re.compile(r"\b([A-Z]{2,}-?\d{3,}[A-Z]?)\b"),  # error codes: ORA-01031, SQL0668N
]


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> np.ndarray: ...


class Reranker(Protocol):
    def rerank(self, query: str, chunks: Sequence[Mapping[str, Any]]) -> list[float]: ...


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "hybrid"  # hybrid | bm25
    k: int = 10
    per_page: int = 3
    fuse_n: int = 50
    rerank_n: int = 20
    gate_threshold: float = 0.69  # also decides which tier-1 chunks "pass the gate" for the tier rule
    source_url_style: str = "branch"


DEFAULT_CONFIG = RetrievalConfig()


@dataclass(frozen=True)
class Hit:
    idx: int
    chunk: Mapping[str, Any]
    score: float
    dense: float | None
    bm25: float
    source_url: str
    source_urls: tuple[str, ...] = ()  # fact cards: the cite_urls that go into sources (source_url first)


@dataclass
class RetrievalResult:
    hits: list[Hit]  # what goes to the LLM: top k after the per-page cap
    ranked: list[Hit]  # every candidate in final order, before the cap (debugging, tests)
    gate_score: float | None  # the highest dense cosine (None without the dense side)
    timings_ms: dict[str, float] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- BM25

_local = threading.local()


def _stemmer():
    # PyStemmer objects are not thread-safe: one per thread (queries run in the threadpool)
    st = getattr(_local, "stemmer", None)
    if st is None:
        import Stemmer

        st = _local.stemmer = Stemmer.Stemmer("english")
    return st


def _tokenize(texts: list[str]) -> list[list[str]]:
    import bm25s

    return bm25s.tokenize(texts, stopwords="en", stemmer=_stemmer(), return_ids=False, show_progress=False)


class BM25Index:
    def __init__(self, texts: Sequence[str]):
        import bm25s

        self.n = len(texts)
        self.model = bm25s.BM25()
        self.model.index(_tokenize(list(texts)), show_progress=False)

    def scores(self, query: str) -> np.ndarray:
        """BM25 score of every chunk for the query (zeros when no query term is in the vocabulary)."""
        ids = self.model.get_tokens_ids(_tokenize([query])[0]) if self.n else []
        if not ids:
            return np.zeros(self.n, dtype=np.float32)
        return np.asarray(self.model.get_scores_from_ids(ids), dtype=np.float32)


# ---------------------------------------------------------------- per-index precomputation


@dataclass(frozen=True)
class RankingData:
    eligible: np.ndarray  # bool: blog chunks are out unless BLOG=on
    static_weight: np.ndarray  # tier weight x release demotion
    tier: np.ndarray
    page_key: tuple[str, ...]
    connector: tuple[str | None, ...]
    product: tuple[str | None, ...]
    texts_lower: tuple[str, ...]
    page_index: Mapping[str, tuple[int, ...]]  # doc_url -> chunk indices (fact card cite_url choice)


def _parse_version(s: str) -> tuple[int, int, int] | None:
    found = re.findall(r"(\d+)\.(\d+)(?:\.(\d+))?", s)
    if not found:
        return None
    return max((int(a), int(b), int(c or 0)) for a, b, c in found)


def release_group_version(chunk: Mapping[str, Any]) -> tuple[str, tuple[int, int, int]] | None:
    url = str(chunk.get("doc_url") or "")
    st = chunk.get("source_type")
    if st == "release-gh":
        m = re.search(r"github\.com/datazip-inc/([^/]+)/releases/tag/([^/?#]+)", url)
        if m:
            v = _parse_version(m.group(2))
            # one repo can carry several tag series (olake-helm: worker v0.4.0 and chart olake-0.0.30)
            series = re.split(r"\d", m.group(2), maxsplit=1)[0]
            return (f"gh:{m.group(1)}:{series}", v) if v else None
    elif st == "release":
        head, _, last = urlparse(url).path.rstrip("/").rpartition("/")
        v = _parse_version(last)
        return (head, v) if v else None
    return None


def old_release_mask(chunks: Sequence[Mapping[str, Any]]) -> list[bool]:
    """True for release notes older than the latest two minor versions of their release series."""
    keys = [release_group_version(c) for c in chunks]
    minors: dict[str, set[tuple[int, int]]] = {}
    for k in keys:
        if k:
            minors.setdefault(k[0], set()).add(k[1][:2])
    keep = {g: set(sorted(ms, reverse=True)[:2]) for g, ms in minors.items()}
    return [bool(k) and k[1][:2] not in keep[k[0]] for k in keys]


def chunk_connector(chunk: Mapping[str, Any]) -> str | None:
    url = str(chunk.get("doc_url") or "")
    m = _DOCS_CONNECTOR_RE.search(url) or _REPO_DRIVER_RE.search(url)
    if m and m.group(1) in _CONNECTOR_PATTERNS:
        return m.group(1)
    return None


def page_key(chunk: Mapping[str, Any]) -> str:
    if chunk.get("source_type") == "factcard":
        return "factcard:" + str(chunk.get("id", "")).split("#", 1)[0]
    return str(chunk.get("doc_url") or chunk.get("id"))


def precompute(chunks: Sequence[Mapping[str, Any]], *, blog: bool) -> RankingData:
    tier = np.array([int(c.get("tier") or TIER_BY_TYPE.get(str(c.get("source_type")), 1)) for c in chunks],
                    dtype=np.int16)
    eligible = np.array([blog or c.get("source_type") != "blog" for c in chunks], dtype=bool)
    weight = np.ones(len(chunks), dtype=np.float32)
    weight[tier == 3] = BLOG_WEIGHT
    weight[np.array(old_release_mask(chunks), dtype=bool)] *= OLD_RELEASE_WEIGHT
    pages: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        if c.get("source_type") != "factcard":
            pages.setdefault(str(c.get("doc_url")), []).append(i)
    return RankingData(
        eligible=_readonly(eligible),
        static_weight=_readonly(weight),
        tier=_readonly(tier),
        page_key=tuple(page_key(c) for c in chunks),
        connector=tuple(chunk_connector(c) for c in chunks),
        product=tuple(c.get("product") for c in chunks),
        texts_lower=tuple(str(c.get("text") or "").lower() for c in chunks),
        page_index={k: tuple(v) for k, v in pages.items()},
    )


def _readonly(a: np.ndarray) -> np.ndarray:
    a.setflags(write=False)
    return a


# ---------------------------------------------------------------- query analysis


def expand_query(question: str) -> str:
    extra = [terms for pat, terms in _SYNONYMS if pat.search(question)]
    return question if not extra else question + " " + " ".join(extra)


def extract_identifiers(question: str) -> list[str]:
    """Identifiers worth an exact-match boost: `quoted code`, --flags, snake_case / camelCase / dotted keys, error
    codes and data type names (lowercased, in order of appearance)."""
    found: list[tuple[int, str]] = []
    for rx in _IDENT_RES:
        for m in rx.finditer(question):
            found.append((m.start(1), m.group(1)))
    for m in re.finditer(r"\b([A-Za-z0-9]+)\b", question):
        if m.group(1).lower() in _TYPE_NAMES:
            found.append((m.start(1), m.group(1)))
    out: list[str] = []
    for _, s in sorted(found):
        s = s.strip().lower()
        if (len(s) >= 4 or s in _TYPE_NAMES) and s not in out:
            out.append(s)
    return out


def detect_connectors(question: str) -> set[str]:
    return {name for name, rx in _CONNECTOR_RES.items() if rx.search(question)}


def names_fusion(question: str) -> bool:
    return bool(_FUSION_RE.search(question))


# ---------------------------------------------------------------- ranking helpers


def rrf(*ranked_lists: Iterable[tuple[int, float]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, (idx, _) in enumerate(lst, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def per_page_cap(items: Sequence[Any], key: Callable[[Any], str], per_page: int, k: int) -> list[Any]:
    out, counts = [], {}
    for it in items:
        p = key(it)
        if counts.get(p, 0) >= per_page:
            continue
        counts[p] = counts.get(p, 0) + 1
        out.append(it)
        if len(out) >= k:
            break
    return out


def _top(scores: np.ndarray, n: int, positive_only: bool) -> list[tuple[int, float]]:
    idx = np.flatnonzero(scores > 0) if positive_only else np.flatnonzero(np.isfinite(scores))
    if len(idx) > n:
        idx = idx[np.argpartition(-scores[idx], n - 1)[:n]]
    idx = idx[np.lexsort((idx, -scores[idx]))]
    return [(int(i), float(scores[i])) for i in idx]


def _enforce_tier_rule(order: list[int], tier: np.ndarray, ok: set[int]) -> list[int]:
    """Move tier 3-4 chunks below the last tier-1 chunk that passes the gate, keeping relative order."""
    last_ok = max((pos for pos, i in enumerate(order) if i in ok), default=-1)
    if last_ok < 0:
        return order
    head, tail = order[:last_ok + 1], order[last_ok + 1:]
    return [i for i in head if tier[i] < 3] + [i for i in head if tier[i] >= 3] + tail


def choose_cite_urls(chunk: Mapping[str, Any], page_scores: Callable[[str], float], connectors: set[str],
                     limit: int = MAX_CARD_SOURCES) -> tuple[str, ...]:
    """The cite_urls a cited fact card puts into sources: the page of a connector named in the question first, then
    the pages whose chunks best match the question, at most `limit` (some cards list six pages, and a single
    citation must not fill the five-source cap)."""
    urls = list(dict.fromkeys(u for u in (chunk.get("cite_urls") or []) if u)) or [str(chunk.get("doc_url"))]
    if len(urls) == 1:
        return (urls[0],)

    def key(u: str) -> tuple[int, float, int]:
        m = _DOCS_CONNECTOR_RE.search(u)
        return (1 if m and m.group(1) in connectors else 0, page_scores(u), -urls.index(u))

    return tuple(sorted(urls, key=key, reverse=True)[:limit])


# ---------------------------------------------------------------- retrieve


def retrieve(snapshot, query: str, *, embedder: QueryEmbedder | None = None, reranker: Reranker | None = None,
             cfg: RetrievalConfig = DEFAULT_CONFIG) -> RetrievalResult:
    t0 = time.perf_counter()
    rd: RankingData = snapshot.ranking
    chunks = snapshot.chunks
    n = len(chunks)

    idents = extract_identifiers(query)
    connectors = detect_connectors(query)
    prefer = "fusion" if names_fusion(query) else "go"
    bm_query = expand_query(query)
    if idents:
        bm_query += " " + " ".join(idents)
    bm = snapshot.bm25.scores(bm_query).copy() if n else np.zeros(0, dtype=np.float32)
    if idents and n:
        boost = np.ones(n, dtype=np.float32)
        for ident in idents:
            boost += IDENT_BOOST_STEP * np.fromiter((ident in t for t in rd.texts_lower), dtype=bool, count=n)
        bm *= np.minimum(boost, IDENT_BOOST_MAX)
    bm[~rd.eligible] = 0.0
    bm_top = _top(bm, cfg.fuse_n, positive_only=True)

    sims: np.ndarray | None = None
    gate: float | None = None
    if cfg.mode == "hybrid" and embedder is not None and snapshot.embeddings is not None and n:
        q = np.asarray(embedder.embed_query(snapshot.query_prefix + query), dtype=np.float32)
        norm = float(np.linalg.norm(q))
        q = q / norm if norm else q
        sims = snapshot.embeddings @ q
        masked = np.where(rd.eligible, sims, -np.inf)
        gate = float(masked.max())
        fused = rrf(bm_top, _top(masked, cfg.fuse_n, positive_only=False))
    else:
        fused = bm_top

    adjusted: dict[int, float] = {}
    for i, s in fused:
        w = float(rd.static_weight[i])
        if connectors and rd.connector[i] in connectors:
            w *= CONNECTOR_BOOST
        adjusted[i] = s * w
    _prefer_twins(adjusted, rd, snapshot.embeddings, prefer)

    order = sorted(adjusted, key=lambda i: (-adjusted[i], i))
    ok = {i for i in order if rd.tier[i] == 1 and (sims is None or sims[i] >= cfg.gate_threshold)}
    order = _enforce_tier_rule(order, rd.tier, ok)
    final_score = dict(adjusted)
    timings = {"retrieve": round((time.perf_counter() - t0) * 1000, 2)}

    if reranker is not None and order:
        t1 = time.perf_counter()
        top = order[:cfg.rerank_n]
        rs = reranker.rerank(query, [chunks[i] for i in top])
        reranked = [i for _, i in sorted(zip(rs, top, strict=True), key=lambda p: -p[0])]
        final_score.update({i: float(s) for i, s in zip(top, rs, strict=True)})
        order = _enforce_tier_rule(reranked, rd.tier, ok) + order[cfg.rerank_n:]
        timings["rerank"] = round((time.perf_counter() - t1) * 1000, 2)

    page_cache: dict[str, float] = {}

    def page_scores(url: str) -> float:
        if url not in page_cache:
            idxs = rd.page_index.get(url, ())
            src = sims if sims is not None else bm
            page_cache[url] = max((float(src[i]) for i in idxs), default=float("-inf"))
        return page_cache[url]

    def hit(i: int) -> Hit:
        c = chunks[i]
        if c.get("source_type") == "factcard":
            urls = choose_cite_urls(c, page_scores, connectors)
        else:
            urls = (plain_source_url(c, cfg.source_url_style),)
        return Hit(idx=i, chunk=c, score=final_score[i], dense=None if sims is None else float(sims[i]),
                   bm25=float(bm[i]), source_url=urls[0], source_urls=urls)

    ranked = [hit(i) for i in order]
    hits = per_page_cap(ranked, key=lambda h: rd.page_key[h.idx], per_page=cfg.per_page, k=cfg.k)
    return RetrievalResult(hits=hits, ranked=ranked, gate_score=gate, timings_ms=timings,
                           info={"connectors": sorted(connectors), "identifiers": idents, "prefer": prefer})


def _prefer_twins(adjusted: dict[int, float], rd: RankingData, emb: np.ndarray | None, prefer: str) -> None:
    """Among near-duplicate go/fusion twin chunks, rank the preferred product's chunk above the other one."""
    if emb is None:
        return
    idxs = [i for i in adjusted if rd.product[i] in ("go", "fusion")]
    if len(idxs) < 2:
        return
    sim = emb[idxs] @ emb[idxs].T
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            i, j = idxs[a], idxs[b]
            if rd.product[i] == rd.product[j] or sim[a, b] < TWIN_COSINE:
                continue
            keep, drop = (i, j) if rd.product[i] == prefer else (j, i)
            adjusted[drop] = min(adjusted[drop] * TWIN_DEMOTE, adjusted[keep] * 0.99)
